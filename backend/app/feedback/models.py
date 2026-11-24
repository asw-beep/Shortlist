"""What a student did with a posting: shown, clicked, saved, dismissed, applied."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey, one_of

INTERACTION_KINDS = ("shown", "clicked", "saved", "dismissed", "applied")
UNIQUE_KINDS = ("saved", "dismissed", "applied")
UNIQUE_PREDICATE = "kind IN ('saved', 'dismissed', 'applied')"
SURFACES = ("feed", "digest", "chat")


class Interaction(UUIDPrimaryKey, Base):
    __tablename__ = "interactions"
    __table_args__ = (
        CheckConstraint(one_of("kind", INTERACTION_KINDS), name="kind"),
        CheckConstraint(one_of("surface", SURFACES), name="surface"),
        CheckConstraint("rank IS NULL OR rank >= 1", name="rank"),
        Index(
            "uq_interactions_user_posting_kind",
            "user_id",
            "posting_id",
            "kind",
            unique=True,
            postgresql_where=text(UNIQUE_PREDICATE),
        ),
        Index("ix_interactions_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    posting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"))
    kind: Mapped[str]
    surface: Mapped[str]
    rank: Mapped[int | None]
    # clock_timestamp(), not now(): events are an ordered log, and now() is the same for every
    # event in one transaction (two saves in one request, or a test's single transaction).
    created_at: Mapped[datetime] = mapped_column(
        server_default=text("clock_timestamp()"), sort_order=100
    )
