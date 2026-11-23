"""Résumé intake: read the text, ask the résumé model for profile facts, canonicalise.

The text goes to Groq only (spec §6.9: user text never goes to a free tier that may train
on it) and is never stored: not the file, not the text, not the prompt.
"""

import io
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.extract.taxonomy import SkillMatcher
from app.llm.base import JsonLLM
from app.profiles.errors import UnreadableResumeError
from app.profiles.schemas import ProfileDraft, SkillOut
from app.profiles.service import canonical_city, canonical_skills

MAX_PDF_BYTES = 2 * 1024 * 1024
MAX_PAGES = 6
MAX_TEXT = 12_000

PROMPT = """From this résumé, extract: which of software, ml, data roles the person is aiming
for (target_roles), total years of paid work experience excluding internships
(years_experience, 0 for a student with only internships), Indian cities they mention as
preferred or current (cities), and their technical skills with a level from 1 (familiar) to 3
(strong, used in real projects). Use only what the résumé says.

Résumé:
"""

__all__ = ["UnreadableResumeError", "draft_from_resume", "pdf_text", "MAX_PDF_BYTES"]


class _Skill(BaseModel):
    name: str
    level: int = Field(ge=1, le=3)


class _ResumeFacts(BaseModel):
    target_roles: list[Literal["software", "ml", "data"]]
    years_experience: float | None
    cities: list[str]
    skills: list[_Skill]


def pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = reader.pages[:MAX_PAGES]
        text = "\n".join(page.extract_text() or "" for page in pages)
    except (PyPdfError, ValueError, TypeError, KeyError) as error:
        raise UnreadableResumeError() from error
    if not text.strip():
        raise UnreadableResumeError()
    return text


def draft_from_resume(llm: JsonLLM, matcher: SkillMatcher, text: str) -> ProfileDraft:
    messages = [{"role": "user", "content": PROMPT + text[:MAX_TEXT]}]
    facts, _ = llm.complete_json(messages, _ResumeFacts, "resume_profile")
    levels, unknown = canonical_skills(matcher, [(s.name, s.level) for s in facts.skills])
    cities = list(dict.fromkeys(c for c in map(canonical_city, facts.cities) if c))
    return ProfileDraft(
        target_roles=list(dict.fromkeys(facts.target_roles)),
        years_experience=facts.years_experience,
        locations=cities,
        skills=[SkillOut(name=n, level=lv) for n, lv in sorted(levels.items())],
        unrecognized_skills=unknown,
    )
