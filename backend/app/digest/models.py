"""One row per student per digest run: what was sent, or why nothing was."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey, one_of

DIGEST_STATUSES = ("sent", "skipped_empty", "failed")


class DigestRun(UUIDPrimaryKey, Base):
    __tablename__ = "digest_runs"
    __table_args__ = (
        CheckConstraint(one_of("status", DIGEST_STATUSES), name="status"),
        Index("ix_digest_runs_user_id_sent_at", "user_id", "sent_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    sent_at: Mapped[datetime]
    posting_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    status: Mapped[str]
