"""scripts/smoke.py: the post-deploy check, run here against the real app on the test DB."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.identity.models import User
from scripts import smoke
from tests.fakes import FakeEmbedder
from tests.integration.api import new_invite
from tests.integration.search_helpers import job

pytestmark = pytest.mark.integration


@pytest.fixture
def smoke_api(api: TestClient, db_app: FastAPI) -> TestClient:
    db_app.state.embedder = FakeEmbedder()
    return api


def test_smoke_passes_and_cleans_up(smoke_api: TestClient, db: Session) -> None:
    job(db, "Python Backend Intern")
    users_before = db.scalar(select(func.count()).select_from(User))
    code = new_invite(smoke_api)

    assert smoke.main(["--base-url", "http://testserver", "--invite", code], client=smoke_api) == 0
    assert db.scalar(select(func.count()).select_from(User)) == users_before  # smoke user deleted


def test_smoke_fails_with_a_bad_invite(smoke_api: TestClient, capsys) -> None:
    argv = ["--base-url", "http://testserver", "--invite", "not-a-code"]
    assert smoke.main(argv, client=smoke_api) == 1
    assert "register" in capsys.readouterr().out
