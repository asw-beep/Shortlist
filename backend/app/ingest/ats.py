"""Read public ATS job boards (Greenhouse, Lever, Ashby) into one RawPosting shape.

All three publish unauthenticated JSON for embedding career pages. Each parser maps that
ATS's own field names; everything else in an item, minus the description fields, is kept in
source_metadata so later stages can read structured facts (Lever's country, Ashby's
isRemote) straight from the source instead of asking an LLM.
"""

import hashlib
import html
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Literal

import httpx

Ats = Literal["greenhouse", "lever", "ashby"]
FailureReason = Literal["timeout", "not_found", "http_error", "bad_payload"]

ENDPOINTS: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
}
MAX_TEXT = 100_000
_BLOCK_TAGS = {"p", "br", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}
_SKIP_TAGS = {"script", "style"}
_DESCRIPTION_FIELDS = {
    "content",
    "description",
    "descriptionPlain",
    "descriptionHtml",
    "descriptionBody",
    "descriptionBodyPlain",
    "lists",
    "additional",
    "additionalPlain",
    "opening",
    "openingPlain",
}


@dataclass(frozen=True)
class RawPosting:
    external_id: str
    url: str
    title: str
    location_raw: str
    description_text: str
    source_metadata: dict[str, Any] = field(default_factory=dict)


class BoardFetchError(Exception):
    def __init__(self, reason: FailureReason, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: FailureReason = reason


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skipping += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Plain text from HTML: block tags become line breaks, scripts and styles are dropped,
    entities are decoded, whitespace is collapsed, and the result is capped at 100,000 chars."""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)[:MAX_TEXT]


def content_hash(posting: RawPosting) -> str:
    """What makes a posting "changed": its title, location and description, nothing else."""
    text = f"{posting.title}\n{posting.location_raw}\n{posting.description_text}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in _DESCRIPTION_FIELDS}


def _join_locations(*names: str | None) -> str:
    seen: list[str] = []
    for name in names:
        if name and name.strip() and name.strip() not in seen:
            seen.append(name.strip())
    return "; ".join(seen)


def parse_greenhouse(payload: dict[str, Any]) -> list[RawPosting]:
    postings = []
    for job in payload["jobs"]:
        # Greenhouse escapes the HTML once more: unescape to HTML, then strip tags.
        description = html_to_text(html.unescape(job.get("content") or ""))
        location = (job.get("location") or {}).get("name") or ""
        postings.append(
            RawPosting(
                external_id=str(job["id"]),
                url=job["absolute_url"],
                title=job["title"].strip(),
                location_raw=location.strip(),
                description_text=description,
                source_metadata=_metadata(job),
            )
        )
    return postings


def parse_lever(payload: list[dict[str, Any]]) -> list[RawPosting]:
    postings = []
    for job in payload:
        categories = job.get("categories") or {}
        all_locations = categories.get("allLocations") or []
        location = _join_locations(*all_locations) or _join_locations(categories.get("location"))
        sections = [job.get("descriptionPlain") or html_to_text(job.get("description") or "")]
        for item in job.get("lists") or []:
            sections.append(item.get("text") or "")
            sections.append(html_to_text(item.get("content") or ""))
        sections.append(job.get("additionalPlain") or html_to_text(job.get("additional") or ""))
        description = "\n".join(s.strip() for s in sections if s and s.strip())[:MAX_TEXT]
        postings.append(
            RawPosting(
                external_id=str(job["id"]),
                url=job["hostedUrl"],
                title=job["text"].strip(),
                location_raw=location,
                description_text=description,
                source_metadata=_metadata(job),
            )
        )
    return postings


def parse_ashby(payload: dict[str, Any]) -> list[RawPosting]:
    postings = []
    for job in payload["jobs"]:
        secondary = [s.get("location") for s in job.get("secondaryLocations") or []]
        description = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml") or "")
        postings.append(
            RawPosting(
                external_id=str(job["id"]),
                url=job["jobUrl"],
                title=job["title"].strip(),
                location_raw=_join_locations(job.get("location"), *secondary),
                description_text=description[:MAX_TEXT],
                source_metadata=_metadata(job),
            )
        )
    return postings


_PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}
ATS_ORDER: tuple[Ats, ...] = ("greenhouse", "lever", "ashby")


def fetch_board(
    client: httpx.Client, ats: Ats, slug: str, timeout: float = 20.0
) -> list[RawPosting]:
    """Fetch and parse one board. Every failure is a BoardFetchError with a named reason."""
    try:
        response = client.get(ENDPOINTS[ats].format(slug=slug), timeout=timeout)
    except httpx.TimeoutException as error:
        raise BoardFetchError("timeout", str(error)) from error
    except httpx.HTTPError as error:
        raise BoardFetchError("http_error", type(error).__name__) from error
    if response.status_code == 404:
        raise BoardFetchError("not_found", f"{ats}/{slug}")
    if response.status_code >= 400:
        raise BoardFetchError("http_error", f"HTTP {response.status_code}")
    try:
        return _PARSERS[ats](response.json())
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise BoardFetchError("bad_payload", type(error).__name__) from error
