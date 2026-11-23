"""Signed one-click links for digest emails: save or dismiss without logging in.

A token is base64url(JSON payload) + "." + base64url(HMAC-SHA256(secret, payload part)).
The signature is checked before the payload is parsed, and in constant time.
"""

import base64
import binascii
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.core.exceptions import AppError

Action = Literal["open", "save", "dismiss"]
ACTIONS = ("open", "save", "dismiss")


class InvalidLinkError(AppError):
    status = 400
    code = "invalid-link"
    title = "This link is not valid"


class ExpiredLinkError(AppError):
    status = 410
    code = "expired-link"
    title = "This link has expired; open Shortlist to see the posting"


@dataclass(frozen=True)
class LinkClaims:
    user_id: uuid.UUID
    posting_id: uuid.UUID
    action: Action
    expires_at: datetime


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode("ascii"), hashlib.sha256).digest())


def sign_link(
    secret: str,
    *,
    user_id: uuid.UUID,
    posting_id: uuid.UUID,
    action: Action,
    expires_at: datetime,
) -> str:
    body = {"u": str(user_id), "p": str(posting_id), "a": action, "e": int(expires_at.timestamp())}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_signature(secret, payload)}"


def verify_link(secret: str, token: str, *, now: datetime) -> LinkClaims:
    payload, dot, signature = token.partition(".")
    if not dot or not payload.isascii() or not signature.isascii():
        raise InvalidLinkError()
    if not hmac.compare_digest(signature, _signature(secret, payload)):
        raise InvalidLinkError()
    try:
        body = json.loads(_unb64(payload))
        claims = LinkClaims(
            user_id=uuid.UUID(body["u"]),
            posting_id=uuid.UUID(body["p"]),
            action=body["a"],
            expires_at=datetime.fromtimestamp(int(body["e"]), UTC),
        )
    except (binascii.Error, ValueError, KeyError, TypeError) as error:
        raise InvalidLinkError() from error
    if claims.action not in ACTIONS:
        raise InvalidLinkError()
    if now >= claims.expires_at:
        raise ExpiredLinkError()
    return claims
