"""Feedback on postings, the saved list, and the signed one-click links from digests."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Path, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Board, Company, Posting
from app.core.exceptions import NotFoundError
from app.core.schemas import RequestModel, ResponseModel
from app.db.session import DbSession
from app.feedback import service
from app.feedback.links import ExpiredLinkError, InvalidLinkError, verify_link
from app.feedback.models import Interaction
from app.identity.dependencies import CurrentUser
from app.identity.models import User

router = APIRouter(tags=["feedback"])

TASTE_KINDS = ("saved", "dismissed")
LINK_KINDS = {"save": "saved", "dismiss": "dismissed"}


class PostingMissingError(NotFoundError):
    code = "posting-missing"
    title = "Posting not found"


class FeedbackIn(RequestModel):
    kind: Literal["saved", "dismissed", "applied", "clicked"]
    surface: Literal["feed", "chat"] = "feed"


class SavedItem(ResponseModel):
    posting_id: uuid.UUID
    title: str
    company: str
    url: str
    status: str
    saved_at: datetime


class SavedOut(ResponseModel):
    items: list[SavedItem]


def _require_posting(db: Session, posting_id: uuid.UUID) -> Posting:
    posting = db.get(Posting, posting_id)
    if posting is None:
        raise PostingMissingError()
    return posting


@router.post("/postings/{posting_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def give_feedback(
    posting_id: uuid.UUID, body: FeedbackIn, user: CurrentUser, db: DbSession
) -> Response:
    _require_posting(db, posting_id)
    service.record(db, user_id=user.id, posting_id=posting_id, kind=body.kind, surface=body.surface)
    if body.kind in TASTE_KINDS:
        service.recompute_taste(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/postings/{posting_id}/feedback/{kind}", status_code=status.HTTP_204_NO_CONTENT)
def undo_feedback(
    posting_id: uuid.UUID,
    kind: Annotated[Literal["saved", "dismissed"], Path()],
    user: CurrentUser,
    db: DbSession,
) -> Response:
    if service.undo(db, user_id=user.id, posting_id=posting_id, kind=kind):
        service.recompute_taste(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/saved", response_model=SavedOut)
def saved(user: CurrentUser, db: DbSession) -> SavedOut:
    rows = db.execute(
        select(
            Posting.id.label("posting_id"),
            Posting.title,
            Company.name.label("company"),
            Posting.url,
            Posting.status,
            Interaction.created_at.label("saved_at"),
        )
        .join(Interaction, Interaction.posting_id == Posting.id)
        .join(Board, Board.id == Posting.board_id)
        .join(Company, Company.id == Board.company_id)
        .where(Interaction.user_id == user.id, Interaction.kind == "saved")
        .order_by(Interaction.created_at.desc(), Interaction.id.desc())
    ).mappings()
    return SavedOut(items=[SavedItem.model_validate(dict(row)) for row in rows])


@router.get("/l/{token}", status_code=status.HTTP_303_SEE_OTHER)
def follow_link(token: str, db: DbSession, request: Request) -> RedirectResponse:
    settings = request.app.state.settings
    claims = verify_link(
        settings.feedback_link_secret.get_secret_value(), token, now=datetime.now(UTC)
    )
    if db.get(User, claims.user_id) is None:
        raise InvalidLinkError()
    posting = db.get(Posting, claims.posting_id)
    if posting is None:
        raise ExpiredLinkError()
    if claims.action == "open":
        service.record(
            db, user_id=claims.user_id, posting_id=posting.id, kind="clicked", surface="digest"
        )
        return RedirectResponse(posting.url, status_code=status.HTTP_303_SEE_OTHER)
    service.record(
        db,
        user_id=claims.user_id,
        posting_id=posting.id,
        kind=LINK_KINDS[claims.action],
        surface="digest",
    )
    service.recompute_taste(db, claims.user_id)
    thanks = f"{settings.frontend_url}/thanks?{urlencode({'action': claims.action})}"
    return RedirectResponse(thanks, status_code=status.HTTP_303_SEE_OTHER)
