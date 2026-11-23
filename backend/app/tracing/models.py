"""spans: one row per LLM call, tool call, search query or batch job step."""

import uuid

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.orm import Mapped

from app.db.base import Base, CreatedAt, UUIDPrimaryKey, one_of

SPAN_KINDS = ("llm", "tool", "sql", "http", "job")
SPAN_STATUSES = ("ok", "error")


class Span(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "spans"
    __table_args__ = (
        CheckConstraint(one_of("kind", SPAN_KINDS), name="kind"),
        CheckConstraint(one_of("status", SPAN_STATUSES), name="status"),
        Index("ix_spans_kind_created_at", "kind", "created_at"),
    )

    trace_id: Mapped[uuid.UUID | None]
    parent_id: Mapped[uuid.UUID | None]
    kind: Mapped[str]
    name: Mapped[str]
    model: Mapped[str | None]
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    latency_ms: Mapped[int]
    status: Mapped[str]
    error: Mapped[str | None]
