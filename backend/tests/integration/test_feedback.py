"""Feedback events, the taste vector they train, and signed one-click links."""

import math
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.feedback.links import sign_link
from app.feedback.models import Interaction
from app.feedback.service import recompute_taste, record, undo
from app.profiles.models import Profile
from tests.fakes import FakeEmbedder
from tests.integration.api import bearer, problem_code, registered_and_logged_in
from tests.integration.search_helpers import job, profile

pytestmark = pytest.mark.integration


def count(db: Session, user_id: uuid.UUID, kind: str) -> int:
    return db.scalar(
        select(func.count()).where(Interaction.user_id == user_id, Interaction.kind == kind)
    )


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


@pytest.fixture
def feed_app(db_app: FastAPI) -> FastAPI:
    db_app.state.embedder = FakeEmbedder()
    return db_app


@pytest.fixture
def student(api: TestClient, feed_app: FastAPI) -> tuple[uuid.UUID, dict[str, str]]:
    user, tokens = registered_and_logged_in(api)
    headers = bearer(tokens["access_token"])
    body = {"target_roles": ["software"], "locations": ["Bengaluru"], "skills": []}
    assert api.put("/api/v1/profile", json=body, headers=headers).status_code == 200
    return uuid.UUID(user["id"]), headers


def feedback(api: TestClient, headers: dict, posting_id: uuid.UUID, kind: str):
    return api.post(f"/api/v1/postings/{posting_id}/feedback", json={"kind": kind}, headers=headers)


def test_save_is_idempotent(api: TestClient, db: Session, student) -> None:
    user_id, headers = student
    posting = job(db, "Python Backend Intern")
    assert feedback(api, headers, posting.id, "saved").status_code == 204
    assert feedback(api, headers, posting.id, "saved").status_code == 204
    assert count(db, user_id, "saved") == 1


def test_clicks_are_not_deduplicated(api: TestClient, db: Session, student) -> None:
    user_id, headers = student
    posting = job(db, "Python Backend Intern")
    feedback(api, headers, posting.id, "clicked")
    feedback(api, headers, posting.id, "clicked")
    assert count(db, user_id, "clicked") == 2


def test_feedback_on_unknown_posting_is_404(api: TestClient, student) -> None:
    _, headers = student
    response = feedback(api, headers, uuid.uuid4(), "saved")
    assert response.status_code == 404 and problem_code(response) == "posting-missing"


def test_shown_is_not_a_feedback_kind(api: TestClient, db: Session, student) -> None:
    _, headers = student
    posting = job(db, "Python Backend Intern")
    assert feedback(api, headers, posting.id, "shown").status_code == 422


def test_dismissed_posting_leaves_feed(api: TestClient, db: Session, student) -> None:
    _, headers = student
    posting = job(db, "Python Backend Intern")
    before = api.get("/api/v1/feed", headers=headers).json()["items"]
    assert [item["posting_id"] for item in before] == [str(posting.id)]
    feedback(api, headers, posting.id, "dismissed")
    assert api.get("/api/v1/feed", headers=headers).json()["items"] == []


def test_save_then_dismiss_keeps_only_the_latest(api: TestClient, db: Session, student) -> None:
    user_id, headers = student
    posting = job(db, "Python Backend Intern")
    feedback(api, headers, posting.id, "saved")
    feedback(api, headers, posting.id, "dismissed")
    assert (count(db, user_id, "saved"), count(db, user_id, "dismissed")) == (0, 1)


def test_undo_save(api: TestClient, db: Session, student) -> None:
    user_id, headers = student
    posting = job(db, "Python Backend Intern")
    feedback(api, headers, posting.id, "saved")
    response = api.delete(f"/api/v1/postings/{posting.id}/feedback/saved", headers=headers)
    assert response.status_code == 204
    assert count(db, user_id, "saved") == 0
    again = api.delete(f"/api/v1/postings/{posting.id}/feedback/saved", headers=headers)
    assert again.status_code == 204


def test_saved_list_newest_first(api: TestClient, db: Session, student) -> None:
    _, headers = student
    first = job(db, "Python Backend Intern", company="First")
    second = job(db, "Go Backend Intern", company="Second")
    feedback(api, headers, first.id, "saved")
    feedback(api, headers, second.id, "saved")
    items = api.get("/api/v1/saved", headers=headers).json()["items"]
    assert [item["posting_id"] for item in items] == [str(second.id), str(first.id)]
    assert set(items[0]) >= {"title", "company", "url", "status", "saved_at"}


def test_feed_logs_impressions_with_rank(api: TestClient, db: Session, student) -> None:
    user_id, headers = student
    for i in range(3):
        job(db, f"Python Backend Intern {i}")
    items = api.get("/api/v1/feed", headers=headers).json()["items"]
    shown = db.execute(
        select(Interaction.posting_id, Interaction.rank, Interaction.surface)
        .where(Interaction.user_id == user_id, Interaction.kind == "shown")
        .order_by(Interaction.rank)
    ).all()
    assert [(str(p), r, s) for p, r, s in shown] == [
        (item["posting_id"], rank, "feed") for rank, item in enumerate(items, start=1)
    ]


def test_taste_vector_moves_toward_saved(db: Session) -> None:
    uid = profile(db)
    liked = job(db, "Python Backend Intern", summary="django postgres apis")
    disliked = job(db, "Sales Engineer Intern", summary="quota pipeline demos")
    record(db, user_id=uid, posting_id=liked.id, kind="saved", surface="feed")
    record(db, user_id=uid, posting_id=disliked.id, kind="dismissed", surface="feed")
    recompute_taste(db, uid)
    taste = list(db.get(Profile, uid).taste_vector)
    assert cosine(taste, liked.embedding) > cosine(taste, disliked.embedding)
    assert math.isclose(math.sqrt(sum(x * x for x in taste)), 1.0, rel_tol=1e-5)


def test_feedback_count_counts_saves_and_dismisses_only(db: Session) -> None:
    uid = profile(db)
    postings = [job(db, f"Python Backend Intern {i}") for i in range(4)]
    record(db, user_id=uid, posting_id=postings[0].id, kind="saved", surface="feed")
    record(db, user_id=uid, posting_id=postings[1].id, kind="dismissed", surface="feed")
    record(db, user_id=uid, posting_id=postings[2].id, kind="applied", surface="feed")
    record(db, user_id=uid, posting_id=postings[3].id, kind="clicked", surface="feed")
    recompute_taste(db, uid)
    assert db.get(Profile, uid).feedback_count == 2


def test_undo_everything_clears_taste(db: Session) -> None:
    uid = profile(db)
    posting = job(db, "Python Backend Intern")
    record(db, user_id=uid, posting_id=posting.id, kind="saved", surface="feed")
    recompute_taste(db, uid)
    assert db.get(Profile, uid).taste_vector is not None
    assert undo(db, user_id=uid, posting_id=posting.id, kind="saved") is True
    recompute_taste(db, uid)
    row = db.get(Profile, uid)
    assert row.taste_vector is None and row.feedback_count == 0


def link(api: TestClient, user_id: uuid.UUID, posting_id: uuid.UUID, action: str, **kw) -> str:
    secret = api.app.state.settings.feedback_link_secret.get_secret_value()
    expires_at = kw.get("expires_at", datetime.now(UTC) + timedelta(days=14))
    token = sign_link(
        secret, user_id=user_id, posting_id=posting_id, action=action, expires_at=expires_at
    )
    return f"/api/v1/l/{token}"


def test_signed_link_is_idempotent(api: TestClient, db: Session, student) -> None:
    user_id, _ = student
    posting = job(db, "Python Backend Intern")
    url = link(api, user_id, posting.id, "save")
    for _ in range(2):
        response = api.get(url, follow_redirects=False)
        assert response.status_code == 303
        location = urlparse(response.headers["location"])
        assert location.path == "/thanks" and location.query == "action=save"
    assert count(db, user_id, "saved") == 1
    assert db.get(Profile, user_id).feedback_count == 1


def test_open_link_records_click_and_redirects_to_posting(
    api: TestClient, db: Session, student
) -> None:
    user_id, _ = student
    posting = job(db, "Python Backend Intern", url="https://jobs.example.com/42")
    response = api.get(link(api, user_id, posting.id, "open"), follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == posting.url
    [surface] = db.scalars(
        select(Interaction.surface).where(
            Interaction.user_id == user_id, Interaction.kind == "clicked"
        )
    ).all()
    assert surface == "digest"


def test_bad_and_expired_links(api: TestClient, db: Session, student) -> None:
    user_id, _ = student
    posting = job(db, "Python Backend Intern")
    bad = api.get("/api/v1/l/not-a-token", follow_redirects=False)
    assert bad.status_code == 400 and problem_code(bad) == "invalid-link"
    past = datetime.now(UTC) - timedelta(minutes=1)
    expired = api.get(link(api, user_id, posting.id, "save", expires_at=past))
    assert expired.status_code == 410 and problem_code(expired) == "expired-link"


def test_link_for_a_deleted_user_is_invalid(api: TestClient, db: Session) -> None:
    posting = job(db, "Python Backend Intern")
    response = api.get(link(api, uuid.uuid4(), posting.id, "save"), follow_redirects=False)
    assert response.status_code == 400 and problem_code(response) == "invalid-link"


def test_many_saves_on_one_connection(db: Session) -> None:
    """psycopg prepares a statement after 5 runs and Postgres soon plans it generically; the
    ON CONFLICT predicate must still match the partial unique index (a bound parameter fails)."""
    uid = profile(db)
    postings = [job(db, f"Python Backend Intern {i}") for i in range(15)]
    for posting in postings:
        assert record(db, user_id=uid, posting_id=posting.id, kind="saved", surface="feed")
    assert record(db, user_id=uid, posting_id=postings[0].id, kind="saved", surface="feed") is False
    assert count(db, uid, "saved") == 15
