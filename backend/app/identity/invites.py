"""Invite codes: `uv run python -m app.cli invite-create --count 50` prints fresh ones."""

import secrets

from sqlalchemy.orm import Session

from app.identity.models import Invite


def create_invites(db: Session, count: int) -> list[str]:
    """Add `count` unused invites to the session and return their codes. The caller commits."""
    codes = [secrets.token_urlsafe(9) for _ in range(count)]  # 12 URL-safe characters
    db.add_all(Invite(code=code) for code in codes)
    db.flush()
    return codes
