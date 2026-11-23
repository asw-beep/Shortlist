"""The weekly digest: top 5 new matches per student, with signed one-click links."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, Settings
from app.digest.models import DigestRun
from app.digest.service import run_digest
from app.feedback.links import verify_link
from app.feedback.models import Interaction
from app.identity.models import User
from app.notify.email import EmailError, EmailMessage, InMemoryEmailSender
from app.profiles.models import Profile
from app.search.config import load_ranking_config
from tests.fakes import FakeEmbedder
from tests.integration.search_helpers import job, profile

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 23, 4, 0, tzinfo=UTC)
CONFIG = load_ranking_config(REPO_ROOT / "config" / "ranking.yaml")


@pytest.fixture
def fake_email() -> InMemoryEmailSender:
    return InMemoryEmailSender()


def digest(db: Session, sender, settings: Settings, now: datetime = NOW):
    return run_digest(db, sender, FakeEmbedder(), CONFIG, settings, now=now)


def runs(db: Session, user_id: uuid.UUID) -> list[DigestRun]:
    return list(db.scalars(select(DigestRun).where(DigestRun.user_id == user_id)))


def link_tokens(message: EmailMessage, settings: Settings) -> list[str]:
    prefix = re.escape(f"{settings.frontend_url}{settings.api_prefix}/l/")
    return re.findall(prefix + r"([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)", message.body)


def test_digest_sends_top5_new_since_last(db: Session, fake_email, test_settings) -> None:
    uid = profile(db)
    new = [
        job(db, f"Python Backend Intern {i}", first_seen_at=NOW - timedelta(days=1))
        for i in range(7)
    ]
    old = job(db, "Python Backend Intern old", first_seen_at=NOW - timedelta(days=8))
    summary = digest(db, fake_email, test_settings)
    assert (summary.sent, summary.skipped_empty, summary.failed) == (1, 0, 0)
    [message] = fake_email.sent
    assert message.to == db.get(User, uid).email and message.html
    [run] = runs(db, uid)
    assert run.status == "sent" and run.sent_at == NOW and len(run.posting_ids) == 5
    assert set(run.posting_ids) <= {p.id for p in new} and old.id not in run.posting_ids
    shown = db.execute(
        select(Interaction.posting_id, Interaction.rank)
        .where(Interaction.user_id == uid, Interaction.surface == "digest")
        .order_by(Interaction.rank)
    ).all()
    assert [(p, r) for p, r in shown] == [(p, r) for r, p in enumerate(run.posting_ids, start=1)]


def test_since_is_the_last_sent_digest(db: Session, fake_email, test_settings) -> None:
    uid = profile(db)
    db.add(DigestRun(user_id=uid, sent_at=NOW - timedelta(days=3), posting_ids=[], status="sent"))
    db.flush()
    before = job(db, "Python Backend Intern before", first_seen_at=NOW - timedelta(days=4))
    after = job(db, "Python Backend Intern after", first_seen_at=NOW - timedelta(days=2))
    digest(db, fake_email, test_settings)
    latest = max(runs(db, uid), key=lambda r: r.sent_at)
    assert latest.posting_ids == [after.id] and before.id not in latest.posting_ids


def test_digest_not_sent_twice_within_24h(db: Session, fake_email, test_settings) -> None:
    profile(db)
    job(db, "Python Backend Intern", first_seen_at=NOW - timedelta(hours=5))
    digest(db, fake_email, test_settings)
    again = digest(db, fake_email, test_settings, now=NOW + timedelta(hours=23))
    assert (again.sent, again.skipped_recent) == (0, 1)
    assert len(fake_email.sent) == 1


def test_user_with_no_matches_gets_no_email(db: Session, fake_email, test_settings) -> None:
    uid = profile(db)
    summary = digest(db, fake_email, test_settings)
    assert summary.skipped_empty == 1 and fake_email.sent == []
    [run] = runs(db, uid)
    assert run.status == "skipped_empty" and run.posting_ids == []


def test_opted_out_and_profileless_users_are_skipped(
    db: Session, fake_email, test_settings
) -> None:
    profile(db, digest_opt_in=False)
    job(db, "Python Backend Intern", first_seen_at=NOW - timedelta(hours=5))
    summary = digest(db, fake_email, test_settings)
    assert (summary.sent, summary.skipped_empty) == (0, 0) and fake_email.sent == []


def test_digest_links_verify_and_point_to_l_route(db: Session, fake_email, test_settings) -> None:
    uid = profile(db)
    posting = job(db, "Python Backend Intern", first_seen_at=NOW - timedelta(hours=5))
    digest(db, fake_email, test_settings)
    [message] = fake_email.sent
    secret = test_settings.feedback_link_secret.get_secret_value()
    claims = [verify_link(secret, t, now=NOW) for t in link_tokens(message, test_settings)]
    assert sorted(c.action for c in claims) == ["dismiss", "open", "save"]
    assert {(c.user_id, c.posting_id) for c in claims} == {(uid, posting.id)}
    assert {c.expires_at for c in claims} == {NOW + timedelta(days=14)}
    assert all(f"/l/{t}" in message.html for t in link_tokens(message, test_settings))


def test_digest_excludes_previously_sent_postings(db: Session, fake_email, test_settings) -> None:
    uid = profile(db)
    relisted = job(db, "Python Backend Intern relisted", first_seen_at=NOW - timedelta(hours=2))
    fresh = job(db, "Python Backend Intern fresh", first_seen_at=NOW - timedelta(hours=2))
    db.add(
        DigestRun(
            user_id=uid, sent_at=NOW - timedelta(days=2), posting_ids=[relisted.id], status="sent"
        )
    )
    db.flush()
    digest(db, fake_email, test_settings)
    latest = max(runs(db, uid), key=lambda r: r.sent_at)
    assert latest.posting_ids == [fresh.id]


class BrokenSender:
    def send(self, message: EmailMessage) -> None:
        raise EmailError("provider down")


def test_failed_send_is_recorded_and_retried_next_run(
    db: Session, fake_email, test_settings
) -> None:
    uid = profile(db)
    job(db, "Python Backend Intern", first_seen_at=NOW - timedelta(hours=5))
    assert digest(db, BrokenSender(), test_settings).failed == 1
    assert [r.status for r in runs(db, uid)] == ["failed"]
    assert digest(db, fake_email, test_settings, now=NOW + timedelta(hours=1)).sent == 1


def test_digest_mentions_why_each_job_matched(db: Session, fake_email, test_settings) -> None:
    profile(db, skills={"Python": 3})
    job(
        db,
        "Python Backend Intern",
        company="Acme",
        required=("Python",),
        first_seen_at=NOW - timedelta(hours=5),
    )
    digest(db, fake_email, test_settings)
    [message] = fake_email.sent
    assert "Python Backend Intern" in message.body and "Acme" in message.body
    assert "Bengaluru" in message.body and "matches your skills" in message.body


def test_profile_feedback_is_untouched(db: Session, fake_email, test_settings) -> None:
    uid = profile(db)
    job(db, "Python Backend Intern", first_seen_at=NOW - timedelta(hours=5))
    digest(db, fake_email, test_settings)
    assert db.get(Profile, uid).feedback_count == 0
