"""Signup needs an invite code, and each code works once."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.invites import create_invites
from app.identity.models import Invite, User
from tests.integration.api import PASSWORD, new_email, new_invite, problem_code, register

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"


def body(**fields) -> dict:
    return {"email": new_email(), "password": PASSWORD, "full_name": "Asha"} | fields


def test_create_invites_makes_unique_codes(db: Session) -> None:
    codes = create_invites(db, 5)
    assert len(set(codes)) == 5 and all(len(c) >= 12 for c in codes)


def test_register_without_invite_is_422(api: TestClient) -> None:
    assert api.post(REGISTER, json=body()).status_code == 422


def test_register_with_unknown_invite_is_400(api: TestClient) -> None:
    response = api.post(REGISTER, json=body(invite_code="not-a-code"))
    assert response.status_code == 400 and problem_code(response) == "invalid-invite"


def test_invite_single_use(api: TestClient) -> None:
    code = new_invite(api)
    register(api, invite_code=code)
    response = api.post(REGISTER, json=body(invite_code=code))
    assert response.status_code == 400 and problem_code(response) == "invalid-invite"


def test_register_marks_invite_used(api: TestClient, db: Session) -> None:
    code = new_invite(api)
    user = register(api, invite_code=code)
    invite = db.scalar(select(Invite).where(Invite.code == code))
    assert str(invite.used_by) == user["id"] and invite.used_at is not None


def test_failed_register_does_not_burn_the_invite(api: TestClient, db: Session) -> None:
    taken = register(api)["email"]
    code = new_invite(api)
    assert api.post(REGISTER, json=body(email=taken, invite_code=code)).status_code == 409
    register(api, invite_code=code)  # still usable


def test_delete_me_removes_user(api: TestClient, db: Session) -> None:
    from tests.integration.api import bearer, login

    user = register(api)
    token = login(api, user["email"])["access_token"]
    assert api.delete("/api/v1/users/me", headers=bearer(token)).status_code == 204
    assert db.scalar(select(User).where(User.email == user["email"])) is None
