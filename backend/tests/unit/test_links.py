"""Signed one-click links: HMAC-SHA256 over a base64url JSON payload, with an expiry."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.feedback.links import ExpiredLinkError, InvalidLinkError, sign_link, verify_link

SECRET = "test-link-secret"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
USER, POSTING = uuid.uuid4(), uuid.uuid4()


def token(action: str = "save", expires_in: timedelta = timedelta(days=14)) -> str:
    return sign_link(
        SECRET, user_id=USER, posting_id=POSTING, action=action, expires_at=NOW + expires_in
    )


def test_sign_verify_roundtrip() -> None:
    claims = verify_link(SECRET, token("dismiss"), now=NOW)
    assert (claims.user_id, claims.posting_id, claims.action) == (USER, POSTING, "dismiss")
    assert claims.expires_at == NOW + timedelta(days=14)


def test_token_is_url_safe() -> None:
    assert all(c.isalnum() or c in "-_." for c in token())


def test_tampered_payload_rejected() -> None:
    good = token()
    payload, signature = good.split(".")
    flipped = payload[:5] + ("A" if payload[5] != "A" else "B") + payload[6:]
    with pytest.raises(InvalidLinkError):
        verify_link(SECRET, f"{flipped}.{signature}", now=NOW)


def test_wrong_secret_rejected() -> None:
    with pytest.raises(InvalidLinkError):
        verify_link("another-secret", token(), now=NOW)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "!!!.???", "e30.e30"])
def test_garbage_rejected(garbage: str) -> None:
    with pytest.raises(InvalidLinkError):
        verify_link(SECRET, garbage, now=NOW)


def test_expired_link_rejected() -> None:
    with pytest.raises(ExpiredLinkError):
        verify_link(SECRET, token(expires_in=timedelta(seconds=-1)), now=NOW)
