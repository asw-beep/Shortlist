"""The text a posting is embedded as: short and about matching, not the whole description."""

from app.embed.model import document_text


def test_document_text_format() -> None:
    text = document_text(
        title="Backend Intern",
        company="Acme",
        city="Pune",
        remote_scope="onsite",
        summary="Build APIs.",
        skills=["Python", "PostgreSQL"],
    )
    assert text == "Backend Intern | Acme | Pune | Build APIs. | Python, PostgreSQL"


def test_document_text_uses_remote_scope_without_city_and_skips_empty_parts() -> None:
    text = document_text(
        title="SWE",
        company="Acme",
        city=None,
        remote_scope="remote_global",
        summary=None,
        skills=[],
    )
    assert text == "SWE | Acme | remote_global"


def test_document_text_caps_skills_at_twelve() -> None:
    skills = [f"S{i}" for i in range(20)]
    text = document_text(
        title="T", company="C", city="X", remote_scope="onsite", summary=None, skills=skills
    )
    assert text.endswith(", ".join(skills[:12]))
