"""GET /feed: the student's ranked postings, each with the reasons for its score."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.core.schemas import ResponseModel
from app.db.session import DbSession
from app.feedback.service import record_impressions
from app.identity.dependencies import CurrentUser
from app.profiles.service import get_profile
from app.search.errors import ProfileIncompleteError
from app.search.service import effective_query, feed_query_text, search

router = APIRouter(tags=["feed"])


class RankedJobOut(ResponseModel):
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


class FeedOut(ResponseModel):
    items: list[RankedJobOut]
    query_used: str


@router.get("/feed", response_model=FeedOut)
def feed(
    user: CurrentUser,
    db: DbSession,
    request: Request,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> FeedOut:
    profile = get_profile(db, user.id)
    if profile is None:
        raise ProfileIncompleteError()
    query_used = effective_query(q) or feed_query_text(profile)
    state = request.app.state
    items = search(
        db, state.embedder, state.ranking_config, user_id=user.id, query=query_used, limit=limit
    )
    record_impressions(db, user_id=user.id, items=items, surface="feed")
    return FeedOut(
        items=[RankedJobOut.model_validate(item) for item in items], query_used=query_used
    )
