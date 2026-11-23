"""Search and rank postings for one student, explaining every score."""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.embed.model import Embedder
from app.profiles.models import Profile
from app.profiles.schemas import ProfileOut
from app.profiles.service import get_profile
from app.search.config import RankingConfig
from app.search.errors import ProfileIncompleteError
from app.search.sql import search_statement
from app.tracing.spans import DbSpanSink, span

Variant = Literal["fts", "dense", "hybrid", "utility", "full"]

FACTORS = ("skill", "rrf", "experience", "location", "recency", "personal")
ROLE_WORDS = {
    "software": "software engineer",
    "ml": "machine learning engineer",
    "data": "data engineer analyst",
}
FEED_SKILLS = 8


@dataclass(frozen=True)
class RankedJob:
    posting_id: uuid.UUID
    title: str
    company: str
    url: str
    city: str | None
    remote_scope: str
    first_seen_at: datetime
    score: float
    factors: dict[str, float]
    matched_skills: list[str]
    missing_skills: list[str]


def feed_query_text(profile: ProfileOut) -> str:
    """Target role words plus the student's top skills by level: the feed's implicit query."""
    roles = [ROLE_WORDS[role] for role in profile.target_roles if role in ROLE_WORDS]
    ranked = sorted(enumerate(profile.skills), key=lambda pair: (-pair[1].level, pair[0]))
    skills = [skill.name for _, skill in ranked[:FEED_SKILLS]]
    return " ".join(roles + skills)


def effective_query(query: str | None) -> str | None:
    """The typed query if it has any word in it; otherwise None (use the profile's)."""
    if query is None or not re.search(r"\w", query):
        return None
    return query.strip()


def search(
    db: Session,
    embedder: Embedder,
    config: RankingConfig,
    *,
    user_id: uuid.UUID,
    query: str | None,
    limit: int = 20,
    variant: Variant = "full",
    since: datetime | None = None,
    now: datetime | None = None,
    exclude_ids: Sequence[uuid.UUID] = (),
) -> list[RankedJob]:
    profile = db.get(Profile, user_id)
    if profile is None:
        raise ProfileIncompleteError()
    query_text = effective_query(query)
    if query_text is None:
        query_text = feed_query_text(get_profile(db, user_id))
    weights = config.weights.as_dict()
    if variant == "utility":
        weights["personal"] = 0.0
    params = {
        "user_id": user_id,
        "q": query_text,
        "qvec": embedder.embed_query(query_text),
        "taste": profile.taste_vector,
        "roles": list(profile.target_roles),
        "seniority": list(profile.seniority_ok),
        "remote_ok": profile.remote_ok,
        "relocate": profile.open_to_relocate,
        "locations": list(profile.locations),
        "avoid": [name.lower() for name in profile.avoid_companies],
        "since": since,
        "exclude": list(exclude_ids),
        "candidates": config.candidates,
        "k": config.rrf_k,
        "years": float(profile.years_experience),
        "now": now or datetime.now(UTC),
        "recency_days": config.recency_days,
        "feedback_count": profile.feedback_count,
        "ramp": config.personal_ramp,
        "limit": limit,
        **{f"w_{name}": value for name, value in weights.items()},
    }
    with span(DbSpanSink(db), "sql", "search"):
        rows = db.execute(search_statement(variant), params).mappings().all()
    return [
        RankedJob(
            posting_id=row["id"],
            title=row["title"],
            company=row["company"],
            url=row["url"],
            city=row["city"],
            remote_scope=row["remote_scope"],
            first_seen_at=row["first_seen_at"],
            score=float(row["score"]),
            factors={name: float(row[f"f_{name}"]) for name in FACTORS},
            matched_skills=list(row["matched_skills"]),
            missing_skills=list(row["missing_skills"]),
        )
        for row in rows
    ]
