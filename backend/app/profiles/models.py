"""What a student wants: roles, places, skills. Its taste vector learns from feedback."""

import uuid
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.catalog.models import EMBEDDING_DIM
from app.db.base import Base, Timestamps

ROLES = ("software", "ml", "data")
SENIORITY_OK = ("intern", "new_grad", "entry", "mid")


class Profile(Timestamps, Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("cardinality(target_roles) > 0", name="has_target_role"),
        CheckConstraint("target_roles <@ ARRAY['software','ml','data']", name="target_roles"),
        CheckConstraint(
            "seniority_ok <@ ARRAY['intern','new_grad','entry','mid']", name="seniority_ok"
        ),
        CheckConstraint("years_experience BETWEEN 0 AND 10", name="years_experience"),
        CheckConstraint("char_length(notes) <= 200", name="notes_length"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    target_roles: Mapped[list[str]] = mapped_column(ARRAY(Text))
    seniority_ok: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("ARRAY['intern','new_grad','entry']")
    )
    years_experience: Mapped[Decimal] = mapped_column(Numeric(3, 1), server_default=text("0"))
    locations: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    open_to_relocate: Mapped[bool] = mapped_column(server_default=text("true"))
    remote_ok: Mapped[bool] = mapped_column(server_default=text("true"))
    avoid_companies: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    notes: Mapped[str] = mapped_column(server_default="")
    digest_opt_in: Mapped[bool] = mapped_column(server_default=text("true"))
    taste_vector: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    feedback_count: Mapped[int] = mapped_column(server_default=text("0"))


class ProfileSkill(Base):
    __tablename__ = "profile_skills"
    __table_args__ = (CheckConstraint("level BETWEEN 1 AND 3", name="level"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.user_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id"), primary_key=True)
    level: Mapped[int]
