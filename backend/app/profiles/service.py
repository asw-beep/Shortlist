"""Save and read profiles. Skills are stored as canonical taxonomy names; cities as the
canonical Indian city names postings are matched against."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.models import Skill
from app.extract.rules import parse_location
from app.extract.taxonomy import SkillMatcher
from app.profiles.errors import UnknownLocationError
from app.profiles.models import Profile, ProfileSkill
from app.profiles.schemas import ProfileIn, ProfileOut, SkillOut


def canonical_skills(
    matcher: SkillMatcher, named: list[tuple[str, int]]
) -> tuple[dict[str, int], list[str]]:
    """{canonical name: highest level given} and the names the taxonomy doesn't know."""
    levels: dict[str, int] = {}
    unknown: list[str] = []
    for name, level in named:
        exact = matcher.canonical(name)
        found = {exact} if exact else matcher.match(name)
        if not found:
            unknown.append(name)
        for canonical in found:
            levels[canonical] = max(level, levels.get(canonical, 0))
    return levels, unknown


def canonical_city(raw: str) -> str | None:
    return parse_location(raw).city


def upsert_profile(
    db: Session, matcher: SkillMatcher, user_id: uuid.UUID, data: ProfileIn
) -> ProfileOut:
    cities = []
    for raw in data.locations:
        city = canonical_city(raw)
        if city is None:
            raise UnknownLocationError(f"{raw!r} is not a city we recognise")
        if city not in cities:
            cities.append(city)
    levels, unknown = canonical_skills(matcher, [(s.name, s.level) for s in data.skills])
    skill_ids = dict(db.execute(select(Skill.name, Skill.id).where(Skill.name.in_(levels))).all())
    unknown += sorted(set(levels) - set(skill_ids))  # known to the taxonomy, not yet seeded

    values = {
        "target_roles": list(dict.fromkeys(data.target_roles)),
        "seniority_ok": list(dict.fromkeys(data.seniority_ok)),
        "years_experience": data.years_experience,
        "locations": cities,
        "open_to_relocate": data.open_to_relocate,
        "remote_ok": data.remote_ok,
        "avoid_companies": list(dict.fromkeys(data.avoid_companies)),
        "notes": data.notes,
        "digest_opt_in": data.digest_opt_in,
    }
    stmt = insert(Profile).values(user_id=user_id, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=[Profile.user_id], set_=values))
    db.execute(delete(ProfileSkill).where(ProfileSkill.user_id == user_id))
    rows = [
        {"user_id": user_id, "skill_id": skill_ids[name], "level": level}
        for name, level in levels.items()
        if name in skill_ids
    ]
    if rows:
        db.execute(insert(ProfileSkill).values(rows))
    db.flush()
    out = get_profile(db, user_id)
    assert out is not None
    return out.model_copy(update={"unrecognized_skills": unknown})


def get_profile(db: Session, user_id: uuid.UUID) -> ProfileOut | None:
    profile = db.get(Profile, user_id, populate_existing=True)
    if profile is None:
        return None
    skills = db.execute(
        select(Skill.name, ProfileSkill.level)
        .join(ProfileSkill, ProfileSkill.skill_id == Skill.id)
        .where(ProfileSkill.user_id == user_id)
        .order_by(ProfileSkill.level.desc(), Skill.name)
    ).all()
    return ProfileOut(
        target_roles=profile.target_roles,
        seniority_ok=profile.seniority_ok,
        years_experience=float(profile.years_experience),
        locations=profile.locations,
        open_to_relocate=profile.open_to_relocate,
        remote_ok=profile.remote_ok,
        skills=[SkillOut(name=n, level=lv) for n, lv in skills],
        avoid_companies=profile.avoid_companies,
        notes=profile.notes,
        digest_opt_in=profile.digest_opt_in,
        feedback_count=profile.feedback_count,
        updated_at=profile.updated_at,
    )
