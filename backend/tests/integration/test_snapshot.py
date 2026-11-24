"""Frozen corpora for evaluation: export relevant open postings, load them anywhere."""

from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.catalog.models import Board, Company, Posting, PostingFeatures, PostingSkill
from evals.snapshot import export_snapshot, load_snapshot
from tests.integration.search_helpers import job

pytestmark = pytest.mark.integration


def test_snapshot_roundtrip(db: Session, tmp_path: Path) -> None:
    kept = [
        job(db, "Python Backend Intern", company="Acme", required=("Python",), nice=("Docker",)),
        job(db, "Data Intern", company="Beta", role_family="data", min_years=1.5),
    ]
    job(db, "Sales Lead", company="Gamma", relevant=False)  # not exported
    job(db, "Old Intern", company="Delta", status="closed", closed_at=kept[0].first_seen_at)
    db.flush()
    db.expire_all()  # read vectors back as stored (float32), not as the factory built them
    before = {p.id: (list(p.embedding), p.title) for p in kept}
    path = tmp_path / "corpus.jsonl.gz"

    assert export_snapshot(db, path) == 2

    ids = list(before)
    db.execute(delete(PostingSkill).where(PostingSkill.posting_id.in_(ids)))
    db.execute(delete(PostingFeatures).where(PostingFeatures.posting_id.in_(ids)))
    db.execute(delete(Posting))
    db.execute(delete(Board))
    db.execute(delete(Company))
    db.flush()
    db.expire_all()

    assert load_snapshot(db, path) == 2
    loaded = {p.id: p for p in db.scalars(select(Posting))}
    assert set(loaded) == set(ids)
    for posting_id, (vector, title) in before.items():
        assert loaded[posting_id].title == title
        assert list(loaded[posting_id].embedding) == vector
    features = db.get(PostingFeatures, ids[1])
    assert (features.role_family, float(features.min_years), features.relevant) == (
        "data",
        1.5,
        True,
    )
    skills = db.execute(select(PostingSkill.kind).where(PostingSkill.posting_id == ids[0])).all()
    assert sorted(kind for (kind,) in skills) == ["nice", "required"]


def test_loading_twice_is_idempotent(db: Session, tmp_path: Path) -> None:
    job(db, "Python Backend Intern", company="Acme")
    path = tmp_path / "corpus.jsonl.gz"
    export_snapshot(db, path)
    assert load_snapshot(db, path) == 0  # already there
