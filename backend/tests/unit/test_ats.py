"""ATS payloads (real samples from Phase 0) become one RawPosting shape."""

import json
from pathlib import Path

import httpx
import pytest

from app.ingest.ats import (
    BoardFetchError,
    RawPosting,
    content_hash,
    fetch_board,
    html_to_text,
    parse_ashby,
    parse_greenhouse,
    parse_lever,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ats"
PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}


def load(ats: str, slug: str) -> object:
    return json.loads((FIXTURES / ats / f"{slug}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("ats", sorted(PARSERS))
def test_fixture_boards_parse(ats: str) -> None:
    files = sorted((FIXTURES / ats).glob("*.json"))
    assert files
    for path in files:
        postings = PARSERS[ats](json.loads(path.read_text(encoding="utf-8")))
        assert postings, path.name
        for p in postings:
            assert p.external_id and p.title and p.url.startswith("https://"), path.name


def test_greenhouse_html_content_is_unescaped_text() -> None:
    payload = {
        "jobs": [
            {
                "id": 1,
                "absolute_url": "https://x.test/1",
                "title": "SWE Intern",
                "location": {"name": "Bengaluru"},
                "content": "&lt;p&gt;Python &amp;amp; SQL&lt;/p&gt;",
            }
        ]
    }
    [posting] = parse_greenhouse(payload)
    assert posting.description_text == "Python & SQL"
    assert posting.location_raw == "Bengaluru"


def test_lever_description_includes_lists() -> None:
    [posting] = parse_lever(
        [
            {
                "id": "a",
                "hostedUrl": "https://jobs.lever.co/x/a",
                "text": "Backend Intern",
                "categories": {"location": "Pune"},
                "descriptionPlain": "Intro.",
                "lists": [{"text": "Requirements", "content": "<li>Go</li><li>Postgres</li>"}],
                "additionalPlain": "Benefits.",
            }
        ]
    )
    assert "Intro." in posting.description_text
    assert "Requirements" in posting.description_text
    assert "Go" in posting.description_text and "Postgres" in posting.description_text
    assert "Benefits." in posting.description_text


def test_lever_all_locations_joined() -> None:
    [posting] = parse_lever(
        [
            {
                "id": "a",
                "hostedUrl": "https://jobs.lever.co/x/a",
                "text": "SWE",
                "categories": {"location": "Bengaluru", "allLocations": ["Bengaluru", "Pune"]},
            }
        ]
    )
    assert posting.location_raw == "Bengaluru; Pune"


def test_ashby_secondary_locations_joined_and_remote_kept() -> None:
    payload = {
        "jobs": [
            {
                "id": "b",
                "jobUrl": "https://jobs.ashbyhq.com/x/b",
                "title": "ML Engineer",
                "location": "San Francisco",
                "secondaryLocations": [{"location": "Bengaluru"}],
                "isRemote": True,
                "descriptionPlain": "Train models.",
            }
        ]
    }
    [posting] = parse_ashby(payload)
    assert posting.location_raw == "San Francisco; Bengaluru"
    assert posting.source_metadata["isRemote"] is True
    assert "descriptionPlain" not in posting.source_metadata


def test_html_to_text_keeps_paragraph_breaks_and_drops_scripts() -> None:
    text = html_to_text("<p>One</p><p>Two<br>Three</p><script>alert(1)</script><style>p{}</style>")
    assert text == "One\nTwo\nThree"


def test_html_to_text_caps_length() -> None:
    assert len(html_to_text("a" * 300_000)) == 100_000


def test_content_hash_changes_with_description_only() -> None:
    base = RawPosting("1", "https://x.test", "SWE", "Pune", "old", {})
    changed = RawPosting("1", "https://x.test", "SWE", "Pune", "new", {"other": 1})
    assert content_hash(base) != content_hash(changed)
    same_text = RawPosting("1", "https://x.test", "SWE", "Pune", "old", {"other": 1})
    assert content_hash(base) == content_hash(same_text)


def test_posting_with_missing_location_gets_empty_string() -> None:
    [posting] = parse_greenhouse(
        {"jobs": [{"id": 2, "absolute_url": "https://x.test/2", "title": "SWE", "content": ""}]}
    )
    assert posting.location_raw == ""


def client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_board_uses_exact_endpoint() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"jobs": []})

    fetch_board(client_returning(handler), "ashby", "acme")
    assert seen == ["https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true"]


def test_fetch_board_404_is_not_found() -> None:
    client = client_returning(lambda request: httpx.Response(404))
    with pytest.raises(BoardFetchError) as error:
        fetch_board(client, "greenhouse", "nope")
    assert error.value.reason == "not_found"


def test_fetch_board_500_is_http_error() -> None:
    client = client_returning(lambda request: httpx.Response(503))
    with pytest.raises(BoardFetchError) as error:
        fetch_board(client, "lever", "flaky")
    assert error.value.reason == "http_error"


def test_fetch_board_timeout_is_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(BoardFetchError) as error:
        fetch_board(client_returning(handler), "greenhouse", "slow")
    assert error.value.reason == "timeout"


def test_fetch_board_bad_json_is_bad_payload() -> None:
    client = client_returning(lambda request: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(BoardFetchError) as error:
        fetch_board(client, "greenhouse", "html")
    assert error.value.reason == "bad_payload"


def test_fetch_board_wrong_shape_is_bad_payload() -> None:
    client = client_returning(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(BoardFetchError) as error:
        fetch_board(client, "lever", "shape")
    assert error.value.reason == "bad_payload"
