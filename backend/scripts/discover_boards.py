"""Find which candidate companies have a public Greenhouse, Lever or Ashby board with at
least one posting this batch could take (India-located, or remote not tied to another
country), and print them as sources/boards.yaml.

    uv run python -m scripts.discover_boards ../sources/candidates.txt > ../sources/boards.yaml

candidates.txt: one company per line; "# comments" allowed. A line may list exact slugs to
try after a pipe ("Physics Wallah | pw, physicswallah"); otherwise slugs are guessed.
"""

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx
import yaml

from app.extract.rules import parse_location
from app.ingest.ats import ATS_ORDER, BoardFetchError, RawPosting, fetch_board


def slug_candidates(company: str) -> list[str]:
    words = re.sub(r"[^a-z0-9 ]+", " ", company.lower()).split()
    variants = ["".join(words), "-".join(words)]
    return list(dict.fromkeys(v for v in variants if v))


def parse_candidate_line(line: str) -> tuple[str, list[str]] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if "|" in text:
        name, slugs = text.split("|", 1)
        return name.strip(), [s.strip() for s in slugs.split(",") if s.strip()]
    return text, slug_candidates(text)


def keeps_board(postings: list[RawPosting]) -> bool:
    for p in postings:
        place = parse_location(p.location_raw, is_remote_flag=p.source_metadata.get("isRemote"))
        if place.country == "IN" or (
            place.country is None and place.remote_scope == "remote_global"
        ):
            return True
    return False


def dedupe_boards(boards: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique = []
    for board in boards:
        key = (board["ats"], board["slug"])
        if key not in seen:
            seen.add(key)
            unique.append(board)
    return unique


def probe(client: httpx.Client, company: str, slugs: list[str]) -> list[dict[str, str]]:
    found = []
    for ats in ATS_ORDER:
        for slug in slugs:
            try:
                postings = fetch_board(client, ats, slug, timeout=15)
            except BoardFetchError:
                continue
            if keeps_board(postings):
                found.append({"company": company, "ats": ats, "slug": slug})
            break  # the first slug a given ATS answers for is this company's board there
    return found


def main(path: str) -> None:
    candidates = [c for c in map(parse_candidate_line, Path(path).read_text().splitlines()) if c]
    with httpx.Client(follow_redirects=True) as client, ThreadPoolExecutor(8) as pool:
        results = pool.map(lambda c: probe(client, *c), candidates)
        boards = dedupe_boards([b for found in results for b in found])
    boards.sort(key=lambda b: (b["company"].lower(), b["ats"]))
    print(f"# Discovered {date.today().isoformat()} by backend/scripts/discover_boards.py;")
    print("# validate with `uv run python -m app.cli check-boards`. Edit by hand freely.")
    print(yaml.safe_dump(boards, sort_keys=False, default_flow_style=None, width=100), end="")
    print(f"discovered {len(boards)} boards from {len(candidates)} candidates", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
