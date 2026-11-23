"""Build small search corpora: postings with features, skills and fake embeddings."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Board, Company, Posting, PostingSkill, Skill
from app.embed.model import document_text
from app.feedback.models import Interaction
from app.profiles.models import Profile, ProfileSkill
from tests.fakes import FakeEmbedder
from tests.integration.factories import (
    make_board,
    make_company,
    make_features,
    make_posting,
    make_user,
)

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def skill_id(db: Session, name: str) -> uuid.UUID:
    found = db.scalar(select(Skill.id).where(Skill.name == name))
    if found is None:
        skill = Skill(name=name, aliases=[])
        db.add(skill)
        db.flush()
        found = skill.id
    return found


def job(
    db: Session,
    title: str,
    *,
    company: str | None = None,
    city: str | None = "Bengaluru",
    country: str | None = "IN",
    remote_scope: str = "onsite",
    required: tuple[str, ...] = (),
    nice: tuple[str, ...] = (),
    min_years: float | None = None,
    seniority: str = "intern",
    role_family: str = "software",
    relevant: bool = True,
    first_seen_at: datetime = NOW,
    summary: str | None = None,
    embedding: list[float] | None = None,
    board: Board | None = None,
    **posting_fields,
) -> Posting:
    if board is None:
        board = make_board(db, make_company(db, name=company) if company else None)
    company_name = company or db.get(Company, board.company_id).name
    posting = make_posting(
        db,
        board,
        title=title,
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
        summary_text=" ".join(filter(None, [title, company_name, summary])),
        **posting_fields,
    )
    make_features(
        db,
        posting,
        role_family=role_family,
        seniority=seniority,
        is_internship=seniority == "intern",
        country=country,
        city=city,
        remote_scope=remote_scope,
        min_years=Decimal(str(min_years)) if min_years is not None else None,
        relevant=relevant,
        summary=summary,
    )
    for kind, names in (("required", required), ("nice", nice)):
        for name in names:
            db.add(PostingSkill(posting_id=posting.id, skill_id=skill_id(db, name), kind=kind))
    text = document_text(
        title=title,
        company=company_name,
        city=city,
        remote_scope=remote_scope,
        summary=summary,
        skills=list(required),
    )
    posting.embedding = embedding or FakeEmbedder.vector(text)
    posting.embedded_hash = posting.content_hash
    db.flush()
    return posting


def interact(db: Session, user_id: uuid.UUID, posting: Posting, kind: str) -> None:
    db.add(Interaction(user_id=user_id, posting_id=posting.id, kind=kind, surface="feed"))
    db.flush()


def profile(
    db: Session,
    *,
    roles: tuple[str, ...] = ("software",),
    skills: dict[str, int] | None = None,
    locations: tuple[str, ...] = ("Bengaluru",),
    open_to_relocate: bool = False,
    remote_ok: bool = True,
    years: float = 0,
    seniority_ok: tuple[str, ...] = ("intern", "new_grad", "entry"),
    avoid: tuple[str, ...] = (),
    **fields,
) -> uuid.UUID:
    user = make_user(db)
    db.add(
        Profile(
            user_id=user.id,
            target_roles=list(roles),
            seniority_ok=list(seniority_ok),
            years_experience=Decimal(str(years)),
            locations=list(locations),
            open_to_relocate=open_to_relocate,
            remote_ok=remote_ok,
            avoid_companies=list(avoid),
            **fields,
        )
    )
    db.flush()
    for name, level in (skills or {"Python": 3}).items():
        db.add(ProfileSkill(user_id=user.id, skill_id=skill_id(db, name), level=level))
    db.flush()
    return user.id
