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


def test_digest_refuses_without_an_email_provider(monkeypatch, capsys) -> None:
    """Without Brevo the digest would 'send' into memory and mark every student as sent."""
    from app import cli
    from app.core.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, environment="test"))
    assert cli.main(["digest"]) == 1
