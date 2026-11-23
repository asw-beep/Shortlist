"""One provider for every OpenAI-compatible chat endpoint (Groq, Gemini's /openai/ route).

Error handling follows Engram's OpenRouter client: a 429 that names a daily limit means the
provider is done for the day (LLMQuotaExhausted); any other failure is a plain LLMError, and
the fallback chain moves on to the next provider.
"""

import re
import time
from typing import Any, TypeVar

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from app.llm.base import LLMError, LLMQuotaExhausted, Usage, strict_schema

log = structlog.get_logger(__name__)
T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_DAILY = re.compile(r"per ?day|\(rpd\)|\(tpd\)|daily", re.I)

BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
}


class OpenAICompatProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client,
        timeout: float = 60,
    ) -> None:
        self.label = f"{name}:{model}"
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key, self._model = api_key, model
        self._client, self._timeout = client, timeout

    def complete_json(
        self, messages: list[dict[str, str]], schema: type[T], schema_name: str
    ) -> tuple[T, Usage]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": strict_schema(schema),
                },
            },
        }
        started = time.perf_counter()
        try:
            response = self._client.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as failure:
            raise LLMError(f"{self.label}: request failed ({type(failure).__name__})") from failure
        latency = round((time.perf_counter() - started) * 1000)

        if response.status_code == 429:
            # Bodies hold no secrets; logged so the daily-limit rule can be checked later.
            log.warning("llm.rate_limited", model=self.label, body=response.text[:500])
            if _DAILY.search(response.text):
                raise LLMQuotaExhausted(f"{self.label}: daily limit reached")
            raise LLMError(f"{self.label}: rate limited")
        if response.status_code >= 400:
            raise LLMError(f"{self.label}: HTTP {response.status_code}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            parsed = schema.model_validate_json(_FENCE.sub("", content.strip()))
        except (ValueError, KeyError, IndexError, TypeError, ValidationError) as failure:
            raise LLMError(f"{self.label}: invalid output") from failure
        usage = payload.get("usage") or {}
        return parsed, Usage(
            self.label, usage.get("prompt_tokens"), usage.get("completion_tokens"), latency
        )


def parse_spec(spec: str) -> tuple[str, str]:
    """ "groq:openai/gpt-oss-20b" -> ("groq", "openai/gpt-oss-20b")."""
    provider, _, model = spec.partition(":")
    if provider not in BASE_URLS or not model:
        raise ValueError(f"unknown model spec {spec!r}")
    return provider, model
