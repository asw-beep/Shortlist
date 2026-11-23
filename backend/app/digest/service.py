"""The weekly digest: each opted-in student's top 5 new matches, emailed with one-click links.

Each student is committed on their own, so an email that went out is never followed by a
rolled-back record of it (which would send it again next run).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.digest.models import DigestRun
from app.digest.render import render_digest
from app.embed.model import Embedder
from app.feedback.links import Action, sign_link
from app.feedback.service import record_impressions
from app.identity.models import User
from app.notify.email import EmailError, EmailMessage, EmailSender
from app.profiles.models import Profile
from app.search.config import RankingConfig
from app.search.service import RankedJob, search

log = structlog.get_logger(__name__)

DIGEST_SIZE = 5
RESEND_GAP = timedelta(hours=24)
DEFAULT_WINDOW = timedelta(days=7)
LINK_LIFETIME = timedelta(days=14)


@dataclass
class DigestSummary:
    sent: int = 0
    skipped_recent: int = 0
    skipped_empty: int = 0
    failed: int = 0


def run_digest(
    db: Session,
    sender: EmailSender,
    embedder: Embedder,
    config: RankingConfig,
    settings: Settings,
    *,
    now: datetime,
) -> DigestSummary:
    summary = DigestSummary()
    students = db.execute(
        select(User.id, User.email, User.full_name)
        .join(Profile, Profile.user_id == User.id)
        .where(Profile.digest_opt_in)
        .order_by(User.created_at)
    ).all()
    base = settings.frontend_url.rstrip("/")
    secret = settings.feedback_link_secret.get_secret_value()

    for user_id, email, full_name in students:
        mine = (DigestRun.user_id == user_id, DigestRun.status == "sent")
        last_sent = db.scalar(select(func.max(DigestRun.sent_at)).where(*mine))
        if last_sent is not None and now - last_sent < RESEND_GAP:
            summary.skipped_recent += 1
            continue
        already_sent = db.scalars(select(func.unnest(DigestRun.posting_ids)).where(*mine)).all()

        def link(item: RankedJob, action: Action, user_id=user_id) -> str:
            token = sign_link(
                secret,
                user_id=user_id,
                posting_id=item.posting_id,
                action=action,
                expires_at=now + LINK_LIFETIME,
            )
            return f"{base}{settings.api_prefix}/l/{token}"

        savepoint = db.begin_nested()
        try:
            items = search(
                db,
                embedder,
                config,
                user_id=user_id,
                query=None,
                limit=DIGEST_SIZE,
                since=last_sent or now - DEFAULT_WINDOW,
                now=now,
                exclude_ids=already_sent,
            )
            if not items:
                db.add(
                    DigestRun(user_id=user_id, sent_at=now, posting_ids=[], status="skipped_empty")
                )
                db.commit()
                summary.skipped_empty += 1
                continue
            name = full_name.split()[0] if full_name.strip() else "there"
            text, html = render_digest(
                name,
                items,
                link,
                weights=config.weights.as_dict(),
                manage_url=f"{base}/profile",
            )
            noun = "match" if len(items) == 1 else "matches"
            sender.send(
                EmailMessage(
                    to=email,
                    subject=f"{len(items)} new {noun} on Shortlist this week",
                    body=text,
                    html=html,
                )
            )
        except Exception as error:  # one student's failure must not stop the others
            savepoint.rollback()
            log.error(
                "digest.failed",
                user_id=str(user_id),
                error=f"{type(error).__name__}: {error}"[:300],
                email_error=isinstance(error, EmailError),
            )
            db.add(DigestRun(user_id=user_id, sent_at=now, posting_ids=[], status="failed"))
            db.commit()
            summary.failed += 1
            continue

        savepoint.commit()
        db.add(
            DigestRun(
                user_id=user_id,
                sent_at=now,
                posting_ids=[item.posting_id for item in items],
                status="sent",
            )
        )
        record_impressions(db, user_id=user_id, items=items, surface="digest")
        db.commit()
        summary.sent += 1
    return summary
