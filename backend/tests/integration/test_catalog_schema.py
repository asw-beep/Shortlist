"""The catalog's constraints hold the rules, so bad rows can't be written at all."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.orm import Session

from tests.integration.factories import make_board, make_features, make_posting

pytestmark = pytest.mark.integration


def test_duplicate_posting_per_board_rejected(db: Session) -> None:
    board = make_board(db)
    make_posting(db, board, external_id="42")
    with pytest.raises(IntegrityError):
        make_posting(db, board, external_id="42")


def test_closed_requires_closed_at(db: Session) -> None:
    with pytest.raises(IntegrityError):
        make_posting(db, status="closed", closed_at=None)


def test_open_posting_cannot_have_closed_at(db: Session) -> None:
    from datetime import UTC, datetime

    with pytest.raises(IntegrityError):
        make_posting(db, status="open", closed_at=datetime.now(UTC))


def test_search_tsv_generated_from_title_and_summary(db: Session) -> None:
    posting = make_posting(db, title="Backend Engineer Intern", summary_text="FastAPI PostgreSQL")
    matched = db.execute(
        text(
            "select search_tsv @@ websearch_to_tsquery('english', 'postgresql') "
            "from postings where id = :id"
        ),
        {"id": posting.id},
    ).scalar()
    assert matched is True


def test_title_weighs_more_than_summary(db: Session) -> None:
    in_title = make_posting(db, title="Kubernetes Intern", summary_text="cloud work")
    in_summary = make_posting(db, title="Platform Intern", summary_text="Kubernetes work")
    ranks = dict(
        db.execute(
            text(
                "select id, ts_rank_cd(search_tsv, websearch_to_tsquery('english', 'kubernetes')) "
                "from postings where id in (:a, :b)"
            ),
            {"a": in_title.id, "b": in_summary.id},
        ).all()
    )
    assert ranks[in_title.id] > ranks[in_summary.id]


def test_embedding_accepts_384_dims(db: Session) -> None:
    posting = make_posting(db, embedding=[0.1] * 384)
    db.refresh(posting)
    assert len(posting.embedding) == 384


def test_embedding_rejects_other_dims(db: Session) -> None:
    with pytest.raises((DataError, StatementError)):
        make_posting(db, embedding=[0.1] * 383)


def test_feature_enums_enforced(db: Session) -> None:
    posting = make_posting(db)
    with pytest.raises(IntegrityError):
        make_features(db, posting, role_family="sales")


def test_board_ats_enforced(db: Session) -> None:
    with pytest.raises(IntegrityError):
        make_board(db, ats="workday")
