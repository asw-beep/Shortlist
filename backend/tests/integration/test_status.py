"""GET /status: is the pipeline healthy, fresh and fast, and do digests get used?"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import IngestRun
from app.digest.models import DigestRun
from app.feedback.models import Interaction
from app.tracing.models import Span
from tests.integration.factories import make_board, make_company
from tests.integration.search_helpers import job, profile

pytestmark = pytest.mark.integration


def span(db: Session, kind: str, name: str, *, latency: int = 5, model: str | None = None, **kw):
    db.add(Span(kind=kind, name=name, latency_ms=latency, status="ok", model=model, **kw))


def test_status_with_an_empty_database(api: TestClient) -> None:
    body = api.get("/api/v1/status").json()
    assert body["last_ingest"] is None and body["open_postings"] == 0
    assert body["freshness_hours_p50"] is None
    assert body["search_latency_ms"] == {"p50": None, "p95": None}
    assert body["failing_boards"] == [] and body["digests"] == [] and body["llm_calls_today"] == {}


def test_status_reports_failing_boards_and_llm_calls(api: TestClient, db: Session) -> None:
    now = datetime.now(UTC)
    db.add(
        IngestRun(
            started_at=now - timedelta(minutes=9), finished_at=now, boards_ok=120, boards_failed=7
        )
    )
    make_board(
        db, make_company(db, name="Flaky Co"), ats="lever", slug="flaky", consecutive_failures=3
    )
    make_board(db)  # healthy
    job(db, "Python Backend Intern")
    job(db, "Sales Lead", relevant=False)
    for model in ("gemini:flash-lite", "gemini:flash-lite", "groq:gpt-oss-20b"):
        span(db, "llm", "extract", model=model)
    span(
        db, "llm", "extract", model="groq:gpt-oss-20b", created_at=now - timedelta(days=1, hours=1)
    )
    db.flush()
    body = api.get("/api/v1/status").json()
    assert body["last_ingest"]["boards_ok"] == 120 and body["last_ingest"]["boards_failed"] == 7
    assert (body["open_postings"], body["relevant_postings"]) == (2, 1)
    assert body["failing_boards"] == [
        {"company": "Flaky Co", "ats": "lever", "slug": "flaky", "consecutive_failures": 3}
    ]
    assert body["llm_calls_today"] == {"gemini:flash-lite": 2, "groq:gpt-oss-20b": 1}


def test_status_freshness_latency_and_digest_save_rate(api: TestClient, db: Session) -> None:
    now = datetime.now(UTC)
    for hours in (1, 3, 5):
        posting = job(db, f"Python Backend Intern {hours}", first_seen_at=now - timedelta(days=2))
        posting.embedded_at = posting.first_seen_at + timedelta(hours=hours)
    stale = job(db, "Python Backend Intern stale", first_seen_at=now - timedelta(days=10))
    stale.embedded_at = stale.first_seen_at + timedelta(hours=100)
    for latency in (10, 20, 30, 40, 100):
        span(db, "sql", "search", latency=latency)
    span(db, "sql", "search", latency=9999, created_at=now - timedelta(days=2))
    uid = profile(db)
    db.add(DigestRun(user_id=uid, sent_at=now, posting_ids=[], status="sent"))
    shown = [job(db, f"Go Intern {i}") for i in range(5)]
    for rank, posting in enumerate(shown, start=1):
        db.add(
            Interaction(
                user_id=uid, posting_id=posting.id, kind="shown", surface="digest", rank=rank
            )
        )
    db.flush()
    for posting, kind in ((shown[0], "saved"), (shown[3], "saved"), (shown[4], "dismissed")):
        db.add(Interaction(user_id=uid, posting_id=posting.id, kind=kind, surface="digest"))
    db.flush()
    body = api.get("/api/v1/status").json()
    assert body["freshness_hours_p50"] == pytest.approx(3.0)
    assert body["search_latency_ms"] == {"p50": 30.0, "p95": pytest.approx(88.0)}
    [week] = body["digests"]
    assert week["sent"] == 1
    assert week["save_rate_at5"] == pytest.approx(0.4) and week["dismiss_rate"] == pytest.approx(
        0.2
    )
    monday = (now - timedelta(days=now.weekday())).date().isoformat()
    assert week["week"] == monday
