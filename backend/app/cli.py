"""Command-line entry points for the batch jobs GitHub Actions runs.

uv run python -m app.cli ingest          sync sources/boards.yaml, then read every board
uv run python -m app.cli check-boards    fetch every listed board once; exit 1 if any fail
"""

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TextIO

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.engine import create_db_engine
from app.db.session import create_session_factory
from app.embed.model import FastEmbedder
from app.embed.service import run_embedding
from app.extract.service import run_extraction, seed_skills
from app.extract.taxonomy import SkillMatcher
from app.ingest.ats import Ats, BoardFetchError, RawPosting, fetch_board
from app.ingest.boards import BoardSpec, load_boards_file, sync_boards
from app.ingest.service import purge_closed, run_ingest
from app.llm.chain import build_chain
from app.tracing.spans import DbSpanSink

log = structlog.get_logger(__name__)
Fetch = Callable[[Ats, str], list[RawPosting]]


def http_fetch(client: httpx.Client) -> Fetch:
    return lambda ats, slug: fetch_board(client, ats, slug)


def check_boards(specs: list[BoardSpec], fetch: Fetch, out: TextIO) -> int:
    failed = False
    for spec in specs:
        try:
            count = len(fetch(spec.ats, spec.slug))
            print(f"{spec.ats} {spec.slug} {spec.company} {count}", file=out)
        except BoardFetchError as error:
            failed = True
            print(f"{spec.ats} {spec.slug} {spec.company} ERROR {error.reason}", file=out)
    return 1 if failed else 0


def cmd_ingest(settings: Settings) -> int:
    session_factory = create_session_factory(create_db_engine(settings))
    specs = load_boards_file(settings.repo_path(settings.boards_path))
    with session_factory() as db, httpx.Client(follow_redirects=True) as client:
        sync_boards(db, specs)
        summary = run_ingest(db, http_fetch(client), now=datetime.now(UTC))
    log.info("ingest.done", **vars(summary))
    return 0


def cmd_check_boards(settings: Settings) -> int:
    specs = load_boards_file(settings.repo_path(settings.boards_path))
    with httpx.Client(follow_redirects=True) as client:
        return check_boards(specs, http_fetch(client), sys.stdout)


def cmd_seed_skills(settings: Settings) -> int:
    session_factory = create_session_factory(create_db_engine(settings))
    with session_factory() as db:
        count = seed_skills(db, settings.repo_path(settings.taxonomy_path))
    log.info("seed_skills.done", skills=count)
    return 0


def cmd_extract(settings: Settings) -> int:
    session_factory = create_session_factory(create_db_engine(settings))
    matcher = SkillMatcher.from_yaml(settings.repo_path(settings.taxonomy_path))
    with session_factory() as db, httpx.Client() as client:
        chain = build_chain(settings.extract_models, settings, client, DbSpanSink(db))
        summary = run_extraction(db, chain, matcher)
    log.info("extract.done", llm_configured=chain is not None, **vars(summary))
    return 0


def cmd_embed(settings: Settings) -> int:
    session_factory = create_session_factory(create_db_engine(settings))
    # The batch worker has cores to spare, unlike the API: let ONNX pick (all cores).
    embedder = FastEmbedder(settings.embed_model, settings.embed_cache_dir, threads=None)
    with session_factory() as db:
        count = run_embedding(db, embedder)
    log.info("embed.done", embedded=count)
    return 0


def cmd_pipeline(settings: Settings) -> int:
    for step in (cmd_ingest, cmd_extract, cmd_embed):
        step(settings)
    session_factory = create_session_factory(create_db_engine(settings))
    with session_factory() as db:
        purged = purge_closed(db, now=datetime.now(UTC))
    log.info("pipeline.done", purged=purged)
    return 0


COMMANDS: dict[str, Callable[[Settings], int]] = {
    "ingest": cmd_ingest,
    "check-boards": cmd_check_boards,
    "seed-skills": cmd_seed_skills,
    "extract": cmd_extract,
    "embed": cmd_embed,
    "pipeline": cmd_pipeline,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    return COMMANDS[args.command](settings)


if __name__ == "__main__":
    sys.exit(main())
