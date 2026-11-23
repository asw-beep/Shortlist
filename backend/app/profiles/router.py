"""/profile: read and save a profile, and draft one from a résumé."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.db.session import DbSession
from app.identity.dependencies import CurrentUser
from app.llm.base import LLMError
from app.profiles import service
from app.profiles.errors import (
    LlmUnavailableError,
    ProfileMissingError,
    ResumeMissingError,
    ResumeTooLargeError,
)
from app.profiles.resume import MAX_PDF_BYTES, draft_from_resume, pdf_text
from app.profiles.schemas import ProfileDraft, ProfileIn, ProfileOut

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
def read_profile(user: CurrentUser, db: DbSession) -> ProfileOut:
    profile = service.get_profile(db, user.id)
    if profile is None:
        raise ProfileMissingError()
    return profile


@router.put("", response_model=ProfileOut)
def save_profile(body: ProfileIn, user: CurrentUser, db: DbSession, request: Request) -> ProfileOut:
    return service.upsert_profile(db, request.app.state.skill_matcher, user.id, body)


@router.post("/resume", response_model=ProfileDraft)
def draft_profile(
    user: CurrentUser,
    db: DbSession,
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form(max_length=50_000)] = None,
) -> ProfileDraft:
    if file is not None:
        data = file.file.read(MAX_PDF_BYTES + 1)
        if len(data) > MAX_PDF_BYTES:
            raise ResumeTooLargeError()
        resume = pdf_text(data)
    elif text and text.strip():
        resume = text
    else:
        raise ResumeMissingError()
    llm = request.app.state.resume_llm_factory(db)
    if llm is None:
        raise LlmUnavailableError()
    try:
        return draft_from_resume(llm, request.app.state.skill_matcher, resume)
    except LLMError as error:
        raise LlmUnavailableError() from error
