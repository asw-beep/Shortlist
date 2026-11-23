"""sources/boards.yaml: which ATS boards to read, and keeping the boards table in step with it."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import ATS_NAMES, Board, Company
from app.ingest.ats import Ats

# A board disabled after this many failures in a row stays off until someone fixes it.
FAILURE_LIMIT = 5


@dataclass(frozen=True)
class BoardSpec:
    company: str
    ats: Ats
    slug: str


def company_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_boards_file(path: Path) -> list[BoardSpec]:
    """Read and validate the board list: a YAML list of {company, ats, slug}."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    specs: list[BoardSpec] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        ats, slug = entry["ats"], str(entry["slug"])
        if ats not in ATS_NAMES:
            raise ValueError(f"unknown ats {ats!r} for {slug!r}")
        if (ats, slug) in seen:
            raise ValueError(f"duplicate board {ats}/{slug}")
        seen.add((ats, slug))
        specs.append(BoardSpec(str(entry["company"]), ats, slug))
    return specs


def sync_boards(db: Session, specs: list[BoardSpec]) -> None:
    """Create companies and boards for new specs, disable boards no longer listed, and
    re-enable listed boards unless they were switched off for failing. Never deletes."""
    boards = {(b.ats, b.slug): b for b in db.scalars(select(Board))}
    companies = {c.slug: c for c in db.scalars(select(Company))}
    listed: set[tuple[str, str]] = set()
    for spec in specs:
        listed.add((spec.ats, spec.slug))
        board = boards.get((spec.ats, spec.slug))
        if board is None:
            slug = company_slug(spec.company)
            company = companies.get(slug)
            if company is None:
                company = Company(name=spec.company, slug=slug)
                db.add(company)
                db.flush()
                companies[slug] = company
            db.add(Board(company_id=company.id, ats=spec.ats, slug=spec.slug))
        elif board.consecutive_failures < FAILURE_LIMIT:
            board.enabled = True
    for key, board in boards.items():
        if key not in listed:
            board.enabled = False
    db.commit()
