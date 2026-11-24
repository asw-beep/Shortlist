"""Freeze the evaluation corpus: relevant open postings with features, skills and embeddings.

A snapshot is gzipped JSON lines. The first line is a header (when it was taken); every other
line is one posting with its company, board, features and skills. Loading is idempotent:
postings already present (same id) are skipped, companies, boards and skills are reused.

Snapshots hold companies' job-description text, so they stay out of git; reports record each
snapshot's SHA-256 instead.
"""

import gzip
import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Numeric, Uuid, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.models import Board, Company, Posting, PostingFeatures, PostingSkill, Skill

POSTING_SKIP = {"board_id", "search_tsv"}
FEATURES_SKIP = {"posting_id"}


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if hasattr(value, "tolist"):  # numpy arrays from pgvector
        return [float(x) for x in value.tolist()]
    return value


def _decode(column: Column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Numeric):
        return Decimal(value)
    if isinstance(column.type, Uuid):
        return uuid.UUID(value)
    return value


def _row(obj: Any, skip: set[str]) -> dict[str, Any]:
    return {c.key: _encode(getattr(obj, c.key)) for c in obj.__table__.columns if c.key not in skip}


def _values(model: Any, data: dict[str, Any]) -> dict[str, Any]:
    columns = {c.key: c for c in model.__table__.columns}
    return {key: _decode(columns[key], value) for key, value in data.items() if key in columns}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_snapshot(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    header = lines[0].get("_snapshot", {}) if lines else {}
    return header, [line for line in lines if "_snapshot" not in line]


def export_snapshot(db: Session, path: Path) -> int:
    rows = db.execute(
        select(Posting, PostingFeatures, Board, Company)
        .join(PostingFeatures, PostingFeatures.posting_id == Posting.id)
        .join(Board, Board.id == Posting.board_id)
        .join(Company, Company.id == Board.company_id)
        .where(Posting.status == "open", PostingFeatures.relevant)
        .order_by(Posting.id)
    ).all()
    skills: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for posting_id, name, aliases, kind in db.execute(
        select(PostingSkill.posting_id, Skill.name, Skill.aliases, PostingSkill.kind)
        .join(Skill, Skill.id == PostingSkill.skill_id)
        .order_by(Skill.name)
    ):
        skills.setdefault(posting_id, []).append({"name": name, "aliases": aliases, "kind": kind})

    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        header = {"exported_at": datetime.now(UTC).isoformat(), "postings": len(rows)}
        handle.write(json.dumps({"_snapshot": header}) + "\n")
        for posting, features, board, company in rows:
            line = _row(posting, POSTING_SKIP) | {
                "company": {"name": company.name, "slug": company.slug},
                "board": {"ats": board.ats, "slug": board.slug},
                "features": _row(features, FEATURES_SKIP),
                "skills": skills.get(posting.id, []),
            }
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return len(rows)


def _id(db: Session, statement: Any, lookup: Any) -> uuid.UUID:
    db.execute(statement.on_conflict_do_nothing())
    return db.scalar(lookup)


def load_snapshot(db: Session, path: Path) -> int:
    """Insert the snapshot's postings that are not already present; returns how many."""
    _, postings = read_snapshot(path)
    loaded = 0
    for item in postings:
        posting_id = uuid.UUID(item["id"])
        if db.get(Posting, posting_id) is not None:
            continue
        company_id = _id(
            db,
            insert(Company).values(**item["company"]),
            select(Company.id).where(Company.slug == item["company"]["slug"]),
        )
        board_id = _id(
            db,
            insert(Board).values(company_id=company_id, **item["board"]),
            select(Board.id).where(
                Board.ats == item["board"]["ats"], Board.slug == item["board"]["slug"]
            ),
        )
        db.add(Posting(board_id=board_id, **_values(Posting, item)))
        db.flush()
        db.add(PostingFeatures(posting_id=posting_id, **_values(PostingFeatures, item["features"])))
        for skill in item["skills"]:
            skill_id = _id(
                db,
                insert(Skill).values(name=skill["name"], aliases=skill["aliases"]),
                select(Skill.id).where(Skill.name == skill["name"]),
            )
            db.add(PostingSkill(posting_id=posting_id, skill_id=skill_id, kind=skill["kind"]))
        loaded += 1
    db.commit()
    return loaded
