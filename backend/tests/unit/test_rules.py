"""Stage A extraction: location, role family, seniority, years, skills, relevance — no LLM."""

import pytest

from app.core.config import REPO_ROOT
from app.extract.rules import Location, extract_rules, is_relevant, parse_location
from app.extract.taxonomy import SkillMatcher

M = SkillMatcher.from_yaml(REPO_ROOT / "taxonomy" / "skills.yaml")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bengaluru, Karnataka, India", Location("IN", "Bengaluru", "onsite")),
        ("Bangalore", Location("IN", "Bengaluru", "onsite")),
        ("Gurgaon, Haryana", Location("IN", "Gurugram", "onsite")),
        ("Remote - India", Location("IN", None, "remote_country")),
        ("Remote (India)", Location("IN", None, "remote_country")),
        ("India - Remote", Location("IN", None, "remote_country")),
        ("Remote", Location(None, None, "remote_global")),
        ("Hyderabad, Telangana (Hybrid)", Location("IN", "Hyderabad", "hybrid")),
        ("San Francisco, CA", Location("US", None, "onsite")),
        ("Remote - US", Location("US", None, "remote_country")),
        ("San Francisco; Bengaluru", Location("IN", "Bengaluru", "onsite")),
        ("New Delhi", Location("IN", "Delhi", "onsite")),
        ("Trivandrum, Kerala", Location("IN", "Thiruvananthapuram", "onsite")),
        ("", Location(None, None, "unknown")),
    ],
)
def test_parse_location(raw: str, expected: Location) -> None:
    assert parse_location(raw) == expected


def test_remote_flag_without_remote_word() -> None:
    assert parse_location("Pune", is_remote_flag=True) == Location("IN", "Pune", "remote_country")


@pytest.mark.parametrize(
    ("title", "family", "seniority", "intern", "new_grad"),
    [
        ("Software Engineer Intern", "software", "intern", True, False),
        ("Machine Learning Engineer, New Grad", "ml", "new_grad", False, True),
        ("Senior Data Engineer", "data", "senior", False, False),
        ("SDE I - Backend", "software", "entry", False, False),
        ("SDE II", "software", "mid", False, False),
        ("Staff Software Engineer", "software", "senior", False, False),
        ("Data Scientist Intern", "data", "intern", True, False),
        ("Account Executive", "other", "unknown", False, False),
    ],
)
def test_title_rules(title: str, family: str, seniority: str, intern: bool, new_grad: bool) -> None:
    f = extract_rules(title, "Bengaluru", "", M)
    assert (f.role_family, f.seniority, f.is_internship, f.is_new_grad) == (
        family,
        seniority,
        intern,
        new_grad,
    )


def test_min_years_plus() -> None:
    assert extract_rules("SWE", "", "3+ years of experience in Go", M).min_years == 3


def test_min_years_range() -> None:
    assert extract_rules("SWE", "", "2-4 years", M).min_years == 2


def test_min_years_prefers_experience_mentions() -> None:
    text = "We have 25 years of history. You bring 1+ years of experience."
    assert extract_rules("SWE", "", text, M).min_years == 1


def test_min_years_none_when_absent() -> None:
    assert extract_rules("SWE", "", "Build APIs.", M).min_years is None


def test_skills_from_title_and_description() -> None:
    f = extract_rules("Python Developer", "", "Experience with k8s and postgres", M)
    assert f.skills == {"Python", "Kubernetes", "PostgreSQL"}


def test_relevance_gate() -> None:
    def rel(**kw: object) -> bool:
        args = {
            "role_family": "software",
            "seniority": "intern",
            "min_years": None,
            "country": "IN",
            "remote_scope": "onsite",
        }
        args.update(kw)
        return is_relevant(**args)  # type: ignore[arg-type]

    assert rel() is True
    assert rel(seniority="senior") is False
    assert rel(country="US") is False
    assert rel(country=None, remote_scope="remote_global") is True
    assert rel(country="US", remote_scope="remote_country") is False
    assert rel(min_years=4) is False
    assert rel(min_years=3) is True
    assert rel(role_family="other") is False


def test_confident_false_when_title_other_but_description_is_engineering() -> None:
    f = extract_rules("Member of Technical Staff", "Pune", "Python, Kubernetes, PostgreSQL", M)
    assert f.role_family == "other" and f.confident is False


def test_confident_false_when_years_missing_for_non_intern() -> None:
    assert extract_rules("Software Engineer", "Pune", "Build APIs", M).confident is False


def test_confident_true_for_clear_intern_posting() -> None:
    assert extract_rules("Software Engineer Intern", "Pune", "Python", M).confident is True


def test_bare_in_code_counts_only_as_whole_part() -> None:
    assert parse_location("Remote, IN").country == "IN"
    assert parse_location("Work in Berlin").country == "DE"


@pytest.mark.parametrize(
    "title",
    ["Customer Success Engineer - II", "Sales Engineer", "Account Manager", "Support Engineer"],
)
def test_customer_facing_titles_are_not_engineering(title: str) -> None:
    assert extract_rules(title, "Pune", "", M).role_family == "other"


def test_title_skills_kept_apart_from_description_skills() -> None:
    f = extract_rules("Python Developer", "", "Experience with k8s", M)
    assert f.title_skills == {"Python"} and f.skills == {"Python", "Kubernetes"}


@pytest.mark.parametrize(
    "title",
    [
        "Enterprise Solutions Engineer",
        "Solutions Architect",
        "Pre-Sales Engineer",
        "Implementation Engineer",
        "Technical Account Manager",
    ],
)
def test_presales_and_implementation_titles_are_customer_facing(title: str) -> None:
    assert extract_rules(title, "Remote", "", M).role_family == "other"


@pytest.mark.parametrize(
    ("title", "country"),
    [
        ("Enterprise Solutions Engineer - Sweden", "SE"),
        ("Backend Engineer (Remote, Brazil)", "BR"),
        ("Software Engineer – Colombia", "CO"),
        ("Platform Engineer | Germany", "DE"),
    ],
)
def test_country_named_at_the_end_of_the_title(title: str, country: str) -> None:
    location = extract_rules(title, "Remote", "", M).location
    assert (location.country, location.remote_scope, location.city) == (
        country,
        "remote_country",
        None,
    )


@pytest.mark.parametrize(
    "title", ["Software Engineer, US Payments", "Backend Engineer - Payments", "Engineer (L4)"]
)
def test_title_words_that_are_not_a_place_are_ignored(title: str) -> None:
    location = extract_rules(title, "Remote", "", M).location
    assert (location.country, location.remote_scope) == (None, "remote_global")


def test_location_field_wins_over_the_title() -> None:
    location = extract_rules("Software Engineer - Sweden", "Bengaluru, India", "", M).location
    assert (location.country, location.city) == ("IN", "Bengaluru")


def test_india_at_the_end_of_the_title() -> None:
    location = extract_rules("Backend Engineer - India (Remote)", "Remote", "", M).location
    assert (location.country, location.remote_scope) == ("IN", "remote_country")
