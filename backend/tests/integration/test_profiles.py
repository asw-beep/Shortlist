"""GET/PUT /profile and POST /profile/resume."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.extract.service import seed_skills
from tests.fakes import FakeLLM
from tests.integration.api import bearer, problem_code, registered_and_logged_in
from tests.unit.test_resume import tiny_pdf

pytestmark = pytest.mark.integration

PROFILE = {
    "target_roles": ["software"],
    "years_experience": 0,
    "locations": ["Bengaluru"],
    "open_to_relocate": False,
    "remote_ok": True,
    "skills": [{"name": "Python", "level": 3}],
    "avoid_companies": [],
    "notes": "",
}


@pytest.fixture(autouse=True)
def skills(db: Session) -> None:
    seed_skills(db, REPO_ROOT / "taxonomy" / "skills.yaml")


@pytest.fixture
def auth(api: TestClient) -> dict[str, str]:
    _, tokens = registered_and_logged_in(api)
    return bearer(tokens["access_token"])


def test_get_profile_before_creating_is_404(api: TestClient, auth: dict) -> None:
    response = api.get("/api/v1/profile", headers=auth)
    assert response.status_code == 404 and problem_code(response) == "profile-missing"


def test_put_then_get_profile_roundtrip(api: TestClient, auth: dict) -> None:
    put = api.put("/api/v1/profile", json=PROFILE, headers=auth)
    assert put.status_code == 200, put.text
    got = api.get("/api/v1/profile", headers=auth).json()
    assert got["target_roles"] == ["software"] and got["locations"] == ["Bengaluru"]
    assert got["skills"] == [{"name": "Python", "level": 3}]
    assert got["seniority_ok"] == ["intern", "new_grad", "entry"]
    assert got["digest_opt_in"] is True


def test_skill_aliases_canonicalised_and_unknown_reported(api: TestClient, auth: dict) -> None:
    body = PROFILE | {"skills": [{"name": "k8s", "level": 2}, {"name": "Fortran77x", "level": 1}]}
    out = api.put("/api/v1/profile", json=body, headers=auth).json()
    assert out["skills"] == [{"name": "Kubernetes", "level": 2}]
    assert out["unrecognized_skills"] == ["Fortran77x"]


def test_unknown_target_role_is_422(api: TestClient, auth: dict) -> None:
    body = PROFILE | {"target_roles": ["sales"]}
    assert api.put("/api/v1/profile", json=body, headers=auth).status_code == 422


def test_city_alias_canonicalised(api: TestClient, auth: dict) -> None:
    out = api.put("/api/v1/profile", json=PROFILE | {"locations": ["Bangalore"]}, headers=auth)
    assert out.json()["locations"] == ["Bengaluru"]


def test_unknown_city_is_422(api: TestClient, auth: dict) -> None:
    response = api.put("/api/v1/profile", json=PROFILE | {"locations": ["Atlantis"]}, headers=auth)
    assert response.status_code == 422 and problem_code(response) == "unknown-location"


def test_put_replaces_skills(api: TestClient, auth: dict) -> None:
    api.put("/api/v1/profile", json=PROFILE, headers=auth)
    body = PROFILE | {"skills": [{"name": "Go", "level": 1}]}
    assert api.put("/api/v1/profile", json=body, headers=auth).json()["skills"] == [
        {"name": "Go", "level": 1}
    ]


def test_profile_needs_login(api: TestClient) -> None:
    assert api.get("/api/v1/profile").status_code == 401


def resume_llm(db_app: FastAPI, answer: dict | Exception | None) -> FakeLLM | None:
    llm = None if answer is None else FakeLLM([answer])
    db_app.state.resume_llm_factory = lambda db: llm
    return llm


RESUME_ANSWER = {
    "target_roles": ["software"],
    "years_experience": 0,
    "cities": ["Pune"],
    "skills": [{"name": "Python", "level": 3}],
}


def test_resume_returns_draft_and_stores_nothing(
    api: TestClient, db_app: FastAPI, db: Session, auth: dict
) -> None:
    sentinel = "SENTINEL-7Q2X-resume-text"
    resume_llm(db_app, RESUME_ANSWER)
    response = api.post(
        "/api/v1/profile/resume",
        files={"file": ("cv.pdf", tiny_pdf(f"Python {sentinel}"), "application/pdf")},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["locations"] == ["Pune"]
    columns = db.execute(
        text(
            "select table_name, column_name from information_schema.columns "
            "where table_schema = 'public' and data_type in ('text', 'character varying', 'jsonb')"
        )
    ).all()
    for table, column in columns:
        hits = db.execute(
            text(f'select count(*) from "{table}" where "{column}"::text like :s'),
            {"s": f"%{sentinel}%"},
        ).scalar()
        assert hits == 0, f"{table}.{column} holds résumé text"


def test_resume_accepts_pasted_text(api: TestClient, db_app: FastAPI, auth: dict) -> None:
    llm = resume_llm(db_app, RESUME_ANSWER)
    response = api.post("/api/v1/profile/resume", data={"text": "Python dev"}, headers=auth)
    assert response.status_code == 200 and "Python dev" in llm.calls[0][-1]["content"]


def test_resume_pdf_over_2mb_is_413(api: TestClient, db_app: FastAPI, auth: dict) -> None:
    resume_llm(db_app, RESUME_ANSWER)
    big = b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024 + 1)
    response = api.post(
        "/api/v1/profile/resume", files={"file": ("cv.pdf", big, "application/pdf")}, headers=auth
    )
    assert response.status_code == 413


def test_resume_without_llm_is_503(api: TestClient, db_app: FastAPI, auth: dict) -> None:
    resume_llm(db_app, None)
    response = api.post("/api/v1/profile/resume", data={"text": "Python dev"}, headers=auth)
    assert response.status_code == 503 and problem_code(response) == "llm-unavailable"


def test_resume_with_nothing_is_422(api: TestClient, db_app: FastAPI, auth: dict) -> None:
    resume_llm(db_app, RESUME_ANSWER)
    assert api.post("/api/v1/profile/resume", data={}, headers=auth).status_code == 422
