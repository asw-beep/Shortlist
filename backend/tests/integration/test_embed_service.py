"""run_embedding: only relevant, open, changed postings get (re-)embedded."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.embed.service import run_embedding
from tests.fakes import FakeEmbedder
from tests.integration.factories import make_features, make_posting

pytestmark = pytest.mark.integration


def test_run_embedding_only_relevant_open_and_changed(db: Session) -> None:
    relevant = make_posting(db, title="Backend Intern", summary_text="x")
    make_features(db, relevant, relevant=True, summary="Build APIs.")
    irrelevant = make_posting(db, title="Sales")
    make_features(db, irrelevant, relevant=False)
    closed = make_posting(db, status="closed", closed_at=datetime.now(UTC))
    make_features(db, closed, relevant=True)
    embedder = FakeEmbedder()

    assert run_embedding(db, embedder) == 1
    for p in (relevant, irrelevant, closed):
        db.refresh(p)
    assert len(relevant.embedding) == 384 and relevant.embedded_hash == relevant.content_hash
    assert relevant.embedded_at is not None
    assert irrelevant.embedding is None and closed.embedding is None
    assert "Build APIs." in embedder.documents[0]
    assert run_embedding(db, embedder) == 0  # nothing changed


def test_reembed_after_content_change(db: Session) -> None:
    posting = make_posting(db)
    make_features(db, posting, relevant=True)
    run_embedding(db, FakeEmbedder())
    posting.content_hash = "changed"
    db.commit()
    assert run_embedding(db, FakeEmbedder()) == 1


def test_batches_cover_everything(db: Session) -> None:
    for i in range(5):
        make_features(db, make_posting(db, external_id=f"p{i}"), relevant=True)
    assert run_embedding(db, FakeEmbedder(), batch_size=2) == 5
