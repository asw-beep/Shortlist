"""The CLI's commands, tested through their injectable cores."""

import io

from app.cli import check_boards
from app.ingest.ats import BoardFetchError, RawPosting
from app.ingest.boards import BoardSpec


def test_check_boards_reports_and_fails_on_any_error() -> None:
    def fetch(ats: str, slug: str) -> list[RawPosting]:
        if slug == "gone":
            raise BoardFetchError("not_found")
        return [RawPosting("1", "https://x.test", "SWE", "Pune", "", {})]

    out = io.StringIO()
    code = check_boards(
        [BoardSpec("Acme", "lever", "acme"), BoardSpec("Gone", "ashby", "gone")], fetch, out
    )
    lines = out.getvalue().splitlines()
    assert code == 1
    assert lines == ["lever acme Acme 1", "ashby gone Gone ERROR not_found"]


def test_check_boards_ok_is_zero() -> None:
    out = io.StringIO()
    assert check_boards([BoardSpec("Acme", "lever", "acme")], lambda a, s: [], out) == 0
