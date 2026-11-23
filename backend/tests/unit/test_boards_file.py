"""sources/boards.yaml: the list of boards to read, validated before anything is fetched."""

from pathlib import Path

import pytest

from app.ingest.boards import BoardSpec, company_slug, load_boards_file


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "boards.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_specs(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "- {company: Stripe, ats: greenhouse, slug: stripe}\n"
        "- {company: CRED, ats: lever, slug: cred}\n",
    )
    assert load_boards_file(path) == [
        BoardSpec("Stripe", "greenhouse", "stripe"),
        BoardSpec("CRED", "lever", "cred"),
    ]


def test_boards_file_rejects_duplicates(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "- {company: A, ats: lever, slug: a}\n- {company: A again, ats: lever, slug: a}\n",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_boards_file(path)


def test_boards_file_rejects_unknown_ats(tmp_path: Path) -> None:
    path = write(tmp_path, "- {company: A, ats: workday, slug: a}\n")
    with pytest.raises(ValueError, match="ats"):
        load_boards_file(path)


def test_empty_file_is_no_boards(tmp_path: Path) -> None:
    assert load_boards_file(write(tmp_path, "")) == []


def test_company_slug() -> None:
    assert company_slug("Razor Pay (India)") == "razor-pay-india"
