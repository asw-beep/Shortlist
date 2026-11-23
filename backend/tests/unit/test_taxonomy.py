"""SkillMatcher: canonical skill names from free text, without false hits inside words."""

from pathlib import Path

import pytest

from app.core.config import REPO_ROOT
from app.extract.taxonomy import SkillMatcher

TAXONOMY = REPO_ROOT / "taxonomy" / "skills.yaml"


@pytest.fixture(scope="module")
def m() -> SkillMatcher:
    return SkillMatcher.from_yaml(TAXONOMY)


def test_committed_taxonomy_has_core_engineering_skills(m: SkillMatcher) -> None:
    for name in ["Python", "Java", "JavaScript", "Kubernetes", "PostgreSQL", "C++", "C#", "React"]:
        assert m.canonical(name) == name


def test_skills_aliases(m: SkillMatcher) -> None:
    assert m.match("Python, k8s and postgres") == {"Python", "Kubernetes", "PostgreSQL"}


def test_skills_symbols(m: SkillMatcher) -> None:
    assert m.match("C++/C# and .NET") == {"C++", "C#", ".NET"}


def test_java_not_in_javascript(m: SkillMatcher) -> None:
    assert m.match("JavaScript developer") == {"JavaScript"}


def test_node_js_with_trailing_punctuation(m: SkillMatcher) -> None:
    assert "Node.js" in m.match("We use Node.js.")


def test_go_is_case_sensitive(m: SkillMatcher) -> None:
    assert "Go" in m.match("Services in Go and Python")
    assert "Go" not in m.match("ready to go live, go-to-market")


def test_onet_names_are_renamed(m: SkillMatcher) -> None:
    assert m.canonical("Oracle Java") == "Java"
    assert m.canonical("Structured query language SQL") == "SQL"


def test_canonical_unknown_is_none(m: SkillMatcher) -> None:
    assert m.canonical("Fortran77x") is None


def test_longest_match_wins(tmp_path: Path) -> None:
    path = tmp_path / "skills.yaml"
    path.write_text(
        "- {name: Spring, aliases: []}\n- {name: Spring Boot, aliases: []}\n", encoding="utf-8"
    )
    assert SkillMatcher.from_yaml(path).match("Spring Boot services") == {"Spring Boot"}


def test_go_at_sentence_start_is_not_the_language(m: SkillMatcher) -> None:
    assert "Go" not in m.match("Go above and beyond. Go-getter attitude.\nGo the extra mile")
    assert "Go" in m.match("Experience with Go, Python")


def test_excel_the_verb_is_not_the_spreadsheet(m: SkillMatcher) -> None:
    assert "Excel" not in m.match("You excel at communication")
    assert "Excel" in m.match("Advanced Excel and SQL")


def test_prose_words_are_not_skills(m: SkillMatcher) -> None:
    assert m.match("guard rails, ROR targets, clever algorithms") == set()
