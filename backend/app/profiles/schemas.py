"""Profile request and response bodies."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.core.schemas import RequestModel, ResponseModel

Role = Literal["software", "ml", "data"]
SeniorityOk = Literal["intern", "new_grad", "entry", "mid"]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class SkillIn(RequestModel):
    name: Short
    level: int = Field(default=2, ge=1, le=3)


class SkillOut(ResponseModel):
    name: str
    level: int


class ProfileIn(RequestModel):
    target_roles: list[Role] = Field(min_length=1)
    seniority_ok: list[SeniorityOk] = Field(
        default_factory=lambda: ["intern", "new_grad", "entry"], min_length=1
    )
    years_experience: float = Field(default=0, ge=0, le=10)
    locations: list[Short] = Field(default_factory=list, max_length=10)
    open_to_relocate: bool = True
    remote_ok: bool = True
    skills: list[SkillIn] = Field(default_factory=list, max_length=40)
    avoid_companies: list[Short] = Field(default_factory=list, max_length=50)
    notes: Annotated[str, StringConstraints(max_length=200)] = ""
    digest_opt_in: bool = True


class ProfileOut(ResponseModel):
    target_roles: list[str]
    seniority_ok: list[str]
    years_experience: float
    locations: list[str]
    open_to_relocate: bool
    remote_ok: bool
    skills: list[SkillOut]
    avoid_companies: list[str]
    notes: str
    digest_opt_in: bool
    feedback_count: int
    unrecognized_skills: list[str] = []
    updated_at: datetime


class ProfileDraft(ResponseModel):
    """What a résumé suggests. Nothing is saved until the student PUTs a profile."""

    target_roles: list[str]
    years_experience: float | None
    locations: list[str]
    skills: list[SkillOut]
    unrecognized_skills: list[str]
