"""Phase 0: can each extraction model return strict JSON for a batch of 8 postings?

    GEMINI_API_KEY=... GROQ_API_KEY=... uv run python -m scripts.checks.extract_check

Sends one batch of 8 fixture postings to every model in Settings.extract_models through the
providers' OpenAI-compatible endpoints, with a strict json_schema response format, and prints
parse success, latency and token usage per model.
"""

import json
import os
import time
from pathlib import Path

import httpx

BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
}
KEYS = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ats" / "greenhouse"
SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "required_skills": {"type": "array", "items": {"type": "string"}},
                    "min_years": {"type": ["number", "null"]},
                    "is_internship": {"type": "boolean"},
                    "one_line_summary": {"type": "string"},
                },
                "required": [
                    "id",
                    "required_skills",
                    "min_years",
                    "is_internship",
                    "one_line_summary",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def postings() -> list[dict[str, str]]:
    out = []
    for path in sorted(FIXTURES.glob("*.json")):
        for job in json.loads(path.read_text(encoding="utf-8"))["jobs"]:
            out.append({"id": str(job["id"]), "title": job["title"], "text": job["content"][:4000]})
    return out[:8]


def main() -> None:
    models = os.environ.get(
        "EXTRACT_MODELS", "gemini:gemini-3.5-flash-lite,groq:openai/gpt-oss-20b"
    ).split(",")
    batch = postings()
    prompt = "Extract fields for each posting. Use null when a posting does not say.\n" + "\n".join(
        f"[{p['id']}] {p['title']}\n{p['text']}" for p in batch
    )
    for spec in models:
        provider, model = spec.split(":", 1)
        key = os.environ.get(KEYS[provider])
        if not key:
            print(f"SKIP {spec}: {KEYS[provider]} not set")
            continue
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "batch", "strict": True, "schema": SCHEMA},
            },
        }
        started = time.perf_counter()
        response = httpx.post(
            f"{BASE_URLS[provider]}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            timeout=120,
        )
        elapsed = round(time.perf_counter() - started, 1)
        if response.status_code != 200:
            print(f"FAIL {spec}: HTTP {response.status_code} {response.text[:300]}")
            continue
        payload = response.json()
        try:
            items = json.loads(payload["choices"][0]["message"]["content"])["items"]
            ids_ok = {i["id"] for i in items} == {p["id"] for p in batch}
            print(
                f"OK   {spec}: {len(items)}/8 items, ids match={ids_ok}, {elapsed}s, "
                f"usage={payload.get('usage')}"
            )
        except (KeyError, ValueError, TypeError) as error:
            print(f"FAIL {spec}: unparseable output ({type(error).__name__})")


if __name__ == "__main__":
    main()
