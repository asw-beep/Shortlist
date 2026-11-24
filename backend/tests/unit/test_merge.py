"""Merging rules (Stage A) with the LLM (Stage B) into the stored features."""

from decimal import Decimal

import pytest

from app.core.config import REPO_ROOT
from app.extract.llm import JobRequirements
from app.extract.merge import merge_features
from app.extract.rules import Location, RuleFeatures
from app.extract.taxonomy import SkillMatcher

M = SkillMatcher.from_yaml(REPO_ROOT / "taxonomy" / "skills.yaml")


def rules(**kw) -> RuleFeatures:
    base = dict(
        role_family="software",
        seniority="unknown",
        is_internship=False,
        is_new_grad=False,
        min_years=None,
        location=Location("IN", "Pune", "onsite"),
        skills={"Python", "Go"},
        confident=False,
        title_skills={"Python"},
    )
    base.update(kw)
    return RuleFeatures(**base)


def llm(**kw) -> JobRequirements:
    base = dict(
        required_skills=["Python 3", "postgres"],
        nice_to_have_skills=["k8s", "Quantum Basket Weaving"],
        min_years=2,
        seniority="entry",
        is_internship=False,
        is_new_grad=False,
        remote_policy="remote_country",
        stipend_or_salary="₹50k/month",
        education=None,
        one_line_summary="Entry-level backend role.",
    )
    base.update(kw)
    return JobRequirements(**base)


def test_merge_llm_overrides_rules_but_location_from_rules() -> None:
    final = merge_features(rules(), llm(), M)
    assert (final.seniority, final.min_years) == ("entry", Decimal(2))
    assert (final.country, final.city, final.remote_scope) == ("IN", "Pune", "onsite")
    assert final.summary == "Entry-level backend role."
    assert final.stipend_or_salary == "₹50k/month"


def test_merge_remote_scope_from_llm_only_when_rules_unknown() -> None:
    final = merge_features(rules(location=Location(None, None, "unknown")), llm(), M)
    assert final.remote_scope == "remote_country"


def test_merge_skills_canonicalised_and_unknown_collected() -> None:
    final = merge_features(rules(), llm(), M)
    assert final.required == {"Python", "PostgreSQL"}
    assert final.nice == {"Kubernetes"}
    assert final.unknown == {"Quantum Basket Weaving"}


def test_merge_keeps_only_title_skills_from_rules_when_llm_present() -> None:
    final = merge_features(rules(title_skills={"Rust"}, skills={"Rust", "Go"}), llm(), M)
    assert "Rust" in final.required and "Go" not in final.required | final.nice


def test_merge_without_llm_uses_rule_skills_as_required() -> None:
    final = merge_features(rules(), None, M)
    assert final.required == {"Python", "Go"} and final.nice == set()
    assert final.stage == "rules"


def test_merge_intern_title_wins_over_llm() -> None:
    final = merge_features(rules(seniority="intern", is_internship=True), llm(seniority="entry"), M)
    assert (final.seniority, final.is_internship) == ("intern", True)


def test_merge_recomputes_relevance() -> None:
    assert merge_features(rules(), llm(min_years=2), M).relevant is True
    assert merge_features(rules(), llm(min_years=5), M).relevant is False


@pytest.mark.parametrize("years", [150, 99.96, 30.5, -1])
def test_merge_ignores_impossible_years_from_the_llm(years: float) -> None:
    """numeric(3,1) can't hold them, and no internship asks for them: keep the rules' value."""
    final = merge_features(rules(min_years=Decimal("2")), llm(min_years=years), M)
    assert final.min_years == Decimal("2")


def test_merge_keeps_plausible_years_from_the_llm() -> None:
    final = merge_features(rules(min_years=None), llm(min_years=2.5), M)
    assert final.min_years == Decimal("2.5")
