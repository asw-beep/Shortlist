"""Board discovery: slug guesses and the keep rule, without the network."""

from app.ingest.ats import RawPosting
from scripts.discover_boards import keeps_board, parse_candidate_line, slug_candidates


def test_slug_candidates() -> None:
    assert slug_candidates("Razor Pay Labs") == ["razorpaylabs", "razor-pay-labs"]
    assert slug_candidates("CRED") == ["cred"]
    assert slug_candidates("Swiggy (Bundl)") == ["swiggybundl", "swiggy-bundl"]


def test_candidate_line_with_explicit_slugs() -> None:
    assert parse_candidate_line("Physics Wallah | pw, physicswallah") == (
        "Physics Wallah",
        ["pw", "physicswallah"],
    )
    assert parse_candidate_line("Groww") == ("Groww", ["groww"])
    assert parse_candidate_line("# fintech") is None
    assert parse_candidate_line("   ") is None


def posting(location: str) -> RawPosting:
    return RawPosting("1", "https://x.test", "SWE", location, "", {})


def test_keeps_board_with_an_india_or_remote_posting() -> None:
    assert keeps_board([posting("London"), posting("Bengaluru, India")]) is True
    assert keeps_board([posting("Remote")]) is True
    assert keeps_board([posting("San Francisco, CA"), posting("Remote - US")]) is False
    assert keeps_board([]) is False


def test_dedupe_boards_keeps_first_per_ats_slug() -> None:
    from scripts.discover_boards import dedupe_boards

    boards = [
        {"company": "Stripe", "ats": "greenhouse", "slug": "stripe"},
        {"company": "Stripe again", "ats": "greenhouse", "slug": "stripe"},
        {"company": "Stripe", "ats": "ashby", "slug": "stripe"},
    ]
    assert dedupe_boards(boards) == [boards[0], boards[2]]
