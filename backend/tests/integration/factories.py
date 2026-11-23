"""Build rows for tests with sensible defaults; any column can be overridden by keyword."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.catalog.models import Board, Company, Posting, PostingFeatures
from app.core.security import hash_opaque_token, new_opaque_token
from app.identity.models import PasswordResetToken, RefreshToken, User


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_company(db: Session, **kw: Any) -> Company:
    name = kw.pop("name", _unique("Company"))
    company = Company(name=name, slug=kw.pop("slug", name.lower()), **kw)
    db.add(company)
    db.flush()
    return company


def make_board(db: Session, company: Company | None = None, **kw: Any) -> Board:
    company = company or make_company(db)
    board = Board(
        company_id=company.id,
        ats=kw.pop("ats", "greenhouse"),
        slug=kw.pop("slug", _unique("board")),
        **kw,
    )
    db.add(board)
    db.flush()
    return board


def make_posting(db: Session, board: Board | None = None, **kw: Any) -> Posting:
    board = board or make_board(db)
    now = kw.pop("now", datetime.now(UTC))
    posting = Posting(
        board_id=board.id,
        external_id=kw.pop("external_id", _unique("ext")),
        url=kw.pop("url", "https://example.com/job"),
        title=kw.pop("title", "Software Engineer Intern"),
        location_raw=kw.pop("location_raw", "Bengaluru, India"),
        description=kw.pop("description", "Build things with Python."),
        source_metadata=kw.pop("source_metadata", {}),
        content_hash=kw.pop("content_hash", uuid.uuid4().hex),
        first_seen_at=kw.pop("first_seen_at", now),
        last_seen_at=kw.pop("last_seen_at", now),
        **kw,
    )
    db.add(posting)
    db.flush()
    return posting


def make_features(db: Session, posting: Posting, **kw: Any) -> PostingFeatures:
    defaults: dict[str, Any] = {
        "extractor_version": 1,
        "stage": "llm",
        "role_family": "software",
        "seniority": "intern",
        "is_internship": True,
        "is_new_grad": False,
        "min_years": None,
        "country": "IN",
        "city": "Bengaluru",
        "remote_scope": "onsite",
        "relevant": True,
        "summary": None,
    }
    defaults.update(kw)
    features = PostingFeatures(posting_id=posting.id, **defaults)
    db.add(features)
    db.flush()
    return features


def make_user(db: Session, **fields: Any) -> User:
    defaults: dict[str, Any] = {
        "email": f"user-{uuid.uuid4().hex[:8]}@example.in",
        "password_hash": "not-a-real-hash",
        "full_name": "Test User",
    }
    user = User(**(defaults | fields))
    db.add(user)
    db.flush()
    return user


def make_refresh_token(db: Session, **fields: Any) -> RefreshToken:
    defaults: dict[str, Any] = {
        "family_id": uuid.uuid4(),
        "token_hash": hash_opaque_token(new_opaque_token()),
        "expires_at": datetime.now(UTC) + timedelta(days=7),
    }
    if "user_id" not in fields:
        defaults["user_id"] = make_user(db).id
    token = RefreshToken(**(defaults | fields))
    db.add(token)
    db.flush()
    return token


def make_password_reset_token(db: Session, **fields: Any) -> PasswordResetToken:
    defaults: dict[str, Any] = {
        "token_hash": hash_opaque_token(new_opaque_token()),
        "expires_at": datetime.now(UTC) + timedelta(minutes=30),
    }
    if "user_id" not in fields:
        defaults["user_id"] = make_user(db).id
    token = PasswordResetToken(**(defaults | fields))
    db.add(token)
    db.flush()
    return token
