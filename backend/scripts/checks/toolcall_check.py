"""Phase 0: one tool-calling round trip on the agent model (input for the Phase 2 plan).

GROQ_API_KEY=... uv run python -m scripts.checks.toolcall_check
"""

import json
import os
import sys

import httpx

TOOL = {
    "type": "function",
    "function": {
        "name": "search_jobs",
        "description": "Search open internships and entry-level jobs.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "remote": {"type": "boolean"},
                "exclude_cities": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
    },
}


def main() -> int:
    key = os.environ.get("GROQ_API_KEY")
    model = os.environ.get("AGENT_MODEL", "openai/gpt-oss-120b")
    if not key:
        print("SKIP: GROQ_API_KEY not set")
        return 0
    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "user", "content": "Find me remote backend internships, not in Bengaluru."}
            ],
            "tools": [TOOL],
        },
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
    )
    if response.status_code != 200:
        print(f"FAIL: HTTP {response.status_code} {response.text[:300]}")
        return 1
    message = response.json()["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if not calls or calls[0]["function"]["name"] != "search_jobs":
        print(f"FAIL: no search_jobs call: {json.dumps(message)[:300]}")
        return 1
    print(f"OK {model}: search_jobs({calls[0]['function']['arguments']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
