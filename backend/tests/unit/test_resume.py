"""Résumé intake: text from a PDF, then an LLM draft with canonical skills and cities."""

import pytest

from app.core.config import REPO_ROOT
from app.extract.taxonomy import SkillMatcher
from app.profiles.resume import UnreadableResumeError, draft_from_resume, pdf_text
from tests.fakes import FakeLLM

M = SkillMatcher.from_yaml(REPO_ROOT / "taxonomy" / "skills.yaml")


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF with `text` in Helvetica, built by hand (no PDF library needed)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out


def test_pdf_text_extracts_words() -> None:
    assert "Python developer" in pdf_text(tiny_pdf("Python developer"))


def test_pdf_text_rejects_non_pdf() -> None:
    with pytest.raises(UnreadableResumeError):
        pdf_text(b"not a pdf at all")


def test_draft_canonicalises_skills_and_cities() -> None:
    llm = FakeLLM(
        [
            {
                "target_roles": ["software", "ml"],
                "years_experience": 0.5,
                "cities": ["Bangalore", "Atlantis"],
                "skills": [
                    {"name": "python3", "level": 3},
                    {"name": "k8s", "level": 1},
                    {"name": "Zorblang", "level": 2},
                ],
            }
        ]
    )
    draft = draft_from_resume(llm, M, "résumé text")
    assert draft.target_roles == ["software", "ml"]
    assert draft.locations == ["Bengaluru"]
    assert {(s.name, s.level) for s in draft.skills} == {("Python", 3), ("Kubernetes", 1)}
    assert draft.unrecognized_skills == ["Zorblang"]


def test_draft_truncates_long_text() -> None:
    llm = FakeLLM([{"target_roles": [], "years_experience": None, "cities": [], "skills": []}])
    draft_from_resume(llm, M, "x" * 20_000)
    assert "x" * 12_000 in llm.calls[0][-1]["content"]
    assert "x" * 12_001 not in llm.calls[0][-1]["content"]
