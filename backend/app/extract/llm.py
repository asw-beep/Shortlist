"""Stage B: ask an LLM for the fields rules can't read reliably, 8 postings per call.

Each posting goes in tagged with its id; answers are matched back by id, and any answer for
an id we didn't send, or a posting the model skipped, is simply absent from the result.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.llm.base import JsonLLM

MAX_DESCRIPTION = 6_000

SYSTEM_PROMPT = """You read job postings and extract facts as JSON.
Extract only what each posting states. If a posting does not say, use null, or "unknown"
for the enumerated fields. List skills as the posting writes them (languages, frameworks,
databases, cloud services, tools, ML methods); put "preferred", "bonus" or "nice to have"
skills in nice_to_have_skills. min_years is the smallest number of years of experience the
posting asks for. one_line_summary: what the job is, in at most 20 words, no company praise.
Answer every posting, using its id exactly as given."""


class JobRequirements(BaseModel):
    required_skills: list[str]
    nice_to_have_skills: list[str]
    min_years: float | None
    seniority: Literal["intern", "new_grad", "entry", "mid", "senior", "unknown"]
    is_internship: bool
    is_new_grad: bool
    remote_policy: Literal["onsite", "hybrid", "remote_country", "remote_global", "unknown"]
    stipend_or_salary: str | None
    education: str | None
    one_line_summary: str


class _Item(JobRequirements):
    id: str


class _Batch(BaseModel):
    items: list[_Item]


@dataclass(frozen=True)
class ExtractionItem:
    id: str
    title: str
    company: str
    location_raw: str
    description: str


def _render(item: ExtractionItem) -> str:
    return (
        f'<posting id="{item.id}">\n'
        f"Title: {item.title}\nCompany: {item.company}\nLocation: {item.location_raw}\n"
        f"{item.description[:MAX_DESCRIPTION]}\n</posting>"
    )


def extract_batch(llm: JsonLLM, items: list[ExtractionItem]) -> dict[str, JobRequirements]:
    if not items:
        return {}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(_render(i) for i in items)},
    ]
    batch, _ = llm.complete_json(messages, _Batch, "job_requirements_batch")
    wanted = {i.id for i in items}
    return {
        answer.id: JobRequirements(**answer.model_dump(exclude={"id"}))
        for answer in batch.items
        if answer.id in wanted
    }
