"""Phase 0: save small real payloads from each ATS as test fixtures.

    uv run python -m scripts.checks.fetch_samples --greenhouse a,b --lever c --ashby d

Each board's response is trimmed to its first 5 postings and written as UTF-8 JSON under
tests/fixtures/ats/<ats>/<slug>.json. Boards that fail are reported and skipped.
"""

import argparse
import json
from pathlib import Path

import httpx

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
}
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ats"
KEEP = 5


def trim(ats: str, payload: object) -> tuple[object, int]:
    if ats == "lever":
        assert isinstance(payload, list)
        return payload[:KEEP], len(payload[:KEEP])
    assert isinstance(payload, dict)
    jobs = payload.get("jobs", [])
    return {**payload, "jobs": jobs[:KEEP]}, len(jobs[:KEEP])


def main() -> None:
    parser = argparse.ArgumentParser()
    for ats in ENDPOINTS:
        parser.add_argument(f"--{ats}", default="")
    args = parser.parse_args()
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for ats, url in ENDPOINTS.items():
            for slug in filter(None, getattr(args, ats).split(",")):
                try:
                    response = client.get(url.format(slug=slug))
                    response.raise_for_status()
                    trimmed, count = trim(ats, response.json())
                except (httpx.HTTPError, ValueError, AssertionError) as error:
                    print(f"SKIP {ats} {slug}: {type(error).__name__}")
                    continue
                if count == 0:
                    print(f"SKIP {ats} {slug}: no postings")
                    continue
                out = FIXTURES / ats / f"{slug}.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(trimmed, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"OK   {ats} {slug}: {count} postings")


if __name__ == "__main__":
    main()
