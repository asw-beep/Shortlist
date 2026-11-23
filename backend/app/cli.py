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
from app.ingest.ats import Ats, BoardFetchError, RawPosting, fetch_board
from app.ingest.boards import BoardSpec, load_boards_file, sync_boards
from app.ingest.service import run_ingest

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


COMMANDS: dict[str, Callable[[Settings], int]] = {
    "ingest": cmd_ingest,
    "check-boards": cmd_check_boards,
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
