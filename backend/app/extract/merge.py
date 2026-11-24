"""Combine Stage A (rules) and Stage B (LLM) into the features a posting is stored with.

Where they disagree: the LLM read the whole posting, so its seniority, years and summary win
when it gives one; the location always comes from rules (structured source fields and city
lists beat a model's guess); an intern or new-grad title is decisive. Skills come from the
LLM when it answered, plus any skill named in the title. Description matches by rules are
used only without an LLM answer, because loose prose ("Go above and beyond") makes them
noisier than the model's list.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.extract.llm import JobRequirements
from app.extract.rules import RuleFeatures, is_relevant
from app.extract.taxonomy import SkillMatcher


@dataclass(frozen=True)
class FinalFeatures:
    stage: str
    role_family: str
    seniority: str
    is_internship: bool
    is_new_grad: bool
    min_years: Decimal | None
    country: str | None
    city: str | None
    remote_scope: str
    relevant: bool
    summary: str | None
    stipend_or_salary: str | None
    education: str | None
    required: set[str]
    nice: set[str]
    unknown: set[str]


def _canonical(names: list[str], matcher: SkillMatcher) -> tuple[set[str], set[str]]:
    known, unknown = set(), set()
    for name in names:
        exact = matcher.canonical(name)
        found = {exact} if exact else matcher.match(name)
        if found:
            known |= found
        elif name.strip():
            unknown.add(name.strip())
    return known, unknown


MAX_YEARS = 30  # beyond any real posting, and inside the column's numeric(3,1)


def _plausible_years(llm_years: float | None, rules_years: Decimal | None) -> Decimal | None:
    """The LLM's figure when it is a believable number of years; otherwise the rules' value."""
    if llm_years is None or not 0 <= llm_years <= MAX_YEARS:
        return rules_years
    return Decimal(str(round(llm_years, 1)))


def merge_features(
    rules: RuleFeatures, llm: JobRequirements | None, matcher: SkillMatcher
) -> FinalFeatures:
    loc = rules.location
    if llm is None:
        seniority, min_years = rules.seniority, rules.min_years
        is_internship, is_new_grad = rules.is_internship, rules.is_new_grad
        required, nice, unknown = set(rules.skills), set(), set()
        remote_scope, summary, stipend, education = loc.remote_scope, None, None, None
    else:
        is_internship = rules.is_internship or llm.is_internship
        is_new_grad = (rules.is_new_grad or llm.is_new_grad) and not is_internship
        if is_internship:
            seniority = "intern"
        elif is_new_grad:
            seniority = "new_grad"
        else:
            seniority = llm.seniority if llm.seniority != "unknown" else rules.seniority
        min_years = _plausible_years(llm.min_years, rules.min_years)
        required, unknown_req = _canonical(llm.required_skills, matcher)
        nice, unknown_nice = _canonical(llm.nice_to_have_skills, matcher)
        required |= rules.title_skills
        nice -= required
        unknown = unknown_req | unknown_nice
        remote_scope = llm.remote_policy if loc.remote_scope == "unknown" else loc.remote_scope
        summary, stipend, education = llm.one_line_summary, llm.stipend_or_salary, llm.education
    relevant = is_relevant(
        role_family=rules.role_family,
        seniority=seniority,
        min_years=min_years,
        country=loc.country,
        remote_scope=remote_scope,
    )
    return FinalFeatures(
        stage="rules" if llm is None else "llm",
        role_family=rules.role_family,
        seniority=seniority,
        is_internship=is_internship,
        is_new_grad=is_new_grad,
        min_years=min_years,
        country=loc.country,
        city=loc.city,
        remote_scope=remote_scope,
        relevant=relevant,
        summary=summary,
        stipend_or_salary=stipend,
        education=education,
        required=required,
        nice=nice,
        unknown=unknown,
    )
