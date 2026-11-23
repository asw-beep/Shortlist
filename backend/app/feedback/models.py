"""What a student did with a posting: shown, clicked, saved, dismissed, applied."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPrimaryKey, one_of

INTERACTION_KINDS = ("shown", "clicked", "saved", "dismissed", "applied")
UNIQUE_KINDS = ("saved", "dismissed", "applied")
SURFACES = ("feed", "digest", "chat")


class Interaction(UUIDPrimaryKey, CreatedAt, Base):
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
            postgresql_where=text("kind IN ('saved', 'dismissed', 'applied')"),
        ),
        Index("ix_interactions_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    posting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"))
    kind: Mapped[str]
    surface: Mapped[str]
    rank: Mapped[int | None]
