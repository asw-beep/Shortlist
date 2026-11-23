"""The job catalog: companies, their ATS boards, the postings read from them, what extraction
learned about each posting, the skill taxonomy, and a record of every ingest run.

Constraints carry the rules (a closed posting has a close time, a board's ATS is one of the
three we read), so code that breaks one fails loudly at the database instead of later.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, one_of

EMBEDDING_DIM = 384
ATS_NAMES = ("greenhouse", "lever", "ashby")
POSTING_STATUSES = ("open", "closed")
STAGES = ("rules", "llm")
ROLE_FAMILIES = ("software", "ml", "data", "other")
SENIORITIES = ("intern", "new_grad", "entry", "mid", "senior", "unknown")
REMOTE_SCOPES = ("onsite", "hybrid", "remote_country", "remote_global", "unknown")
SKILL_KINDS = ("required", "nice")
RUN_STATUSES = ("ok", "failed")

# Title counts most (A), then the extracted summary line (B). English stemming.
SEARCH_TSV = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(summary_text, '')), 'B')"
)


class Company(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("slug"),)

    name: Mapped[str]
    slug: Mapped[str]


class Board(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "boards"
    __table_args__ = (
        UniqueConstraint("ats", "slug"),
        CheckConstraint(one_of("ats", ATS_NAMES), name="ats"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    ats: Mapped[str]
    slug: Mapped[str]
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    consecutive_failures: Mapped[int] = mapped_column(server_default=text("0"))


class Posting(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("board_id", "external_id"),
        CheckConstraint(one_of("status", POSTING_STATUSES), name="status"),
        CheckConstraint("(status = 'closed') = (closed_at IS NOT NULL)", name="closed_at"),
        Index("ix_postings_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_postings_status", "status"),
    )

    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boards.id"))
    external_id: Mapped[str]
    url: Mapped[str]
    title: Mapped[str]
    location_raw: Mapped[str]
    # Purged 30 days after the posting closes; the row stays for its interactions.
    description: Mapped[str | None]
    source_metadata: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    # sha256 of title, location and description. processed_hash and embedded_hash record the
    # content that extraction and embedding last saw, so only changed postings are redone.
    content_hash: Mapped[str]
    processed_hash: Mapped[str | None]
    embedded_hash: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="open")
    missed_runs: Mapped[int] = mapped_column(server_default=text("0"))
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    closed_at: Mapped[datetime | None]
    # Title, company and extracted summary: what full-text search reads besides the title.
    summary_text: Mapped[str | None]
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(SEARCH_TSV, persisted=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedded_at: Mapped[datetime | None]


class PostingFeatures(Base):
    __tablename__ = "posting_features"
    __table_args__ = (
        CheckConstraint(one_of("stage", STAGES), name="stage"),
        CheckConstraint(one_of("role_family", ROLE_FAMILIES), name="role_family"),
        CheckConstraint(one_of("seniority", SENIORITIES), name="seniority"),
        CheckConstraint(one_of("remote_scope", REMOTE_SCOPES), name="remote_scope"),
        Index(
            "ix_posting_features_relevant_role_seniority", "relevant", "role_family", "seniority"
        ),
    )

    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("postings.id", ondelete="CASCADE"), primary_key=True
    )
    extractor_version: Mapped[int]
    stage: Mapped[str]
    # True when the LLM stage was skipped (quota, outage) and should be retried next run.
    llm_pending: Mapped[bool] = mapped_column(server_default=text("false"))
    role_family: Mapped[str]
    seniority: Mapped[str]
    is_internship: Mapped[bool]
    is_new_grad: Mapped[bool]
    min_years: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    country: Mapped[str | None]  # ISO 3166-1 alpha-2
    city: Mapped[str | None]
    remote_scope: Mapped[str]
    relevant: Mapped[bool]
    summary: Mapped[str | None]
    stipend_or_salary: Mapped[str | None]
    education: Mapped[str | None]


class Skill(UUIDPrimaryKey, Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("name"),)

    name: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))


class PostingSkill(Base):
    __tablename__ = "posting_skills"
    __table_args__ = (CheckConstraint(one_of("kind", SKILL_KINDS), name="kind"),)

    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("postings.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id"), primary_key=True)
    kind: Mapped[str]


class UnknownSkill(UUIDPrimaryKey, Base):
    """Skill names the LLM returned that the taxonomy doesn't know: a list to review by hand."""

    __tablename__ = "unknown_skills"
    __table_args__ = (UniqueConstraint("name"),)

    name: Mapped[str]
    seen_count: Mapped[int] = mapped_column(server_default=text("1"))
    first_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class IngestRun(UUIDPrimaryKey, Base):
    __tablename__ = "ingest_runs"

    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    boards_ok: Mapped[int] = mapped_column(server_default=text("0"))
    boards_failed: Mapped[int] = mapped_column(server_default=text("0"))
    postings_new: Mapped[int] = mapped_column(server_default=text("0"))
    postings_changed: Mapped[int] = mapped_column(server_default=text("0"))
    postings_closed: Mapped[int] = mapped_column(server_default=text("0"))


class BoardRun(UUIDPrimaryKey, Base):
    __tablename__ = "board_runs"
    __table_args__ = (CheckConstraint(one_of("status", RUN_STATUSES), name="status"),)

    ingest_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingest_runs.id"), index=True)
    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boards.id"), index=True)
    status: Mapped[str]
    failure_reason: Mapped[str | None]
    postings_seen: Mapped[int] = mapped_column(server_default=text("0"))
    latency_ms: Mapped[int]
