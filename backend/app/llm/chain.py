"""Try providers in order. A provider out of daily quota is skipped for the rest of the run."""

from typing import TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.llm.base import JsonLLM, LLMError, LLMQuotaExhausted, Usage
from app.llm.openai_compat import BASE_URLS, OpenAICompatProvider, parse_spec
from app.tracing.spans import SpanSink, span

T = TypeVar("T", bound=BaseModel)


class FallbackChain:
    def __init__(self, providers: list[JsonLLM], spans: SpanSink) -> None:
        self._providers = providers
        self._spans = spans
        self._exhausted: set[int] = set()
        self.label = " > ".join(p.label for p in providers)

    def complete_json(
        self, messages: list[dict[str, str]], schema: type[T], schema_name: str
    ) -> tuple[T, Usage]:
        last_error: LLMError | None = None
        for index, provider in enumerate(self._providers):
            if index in self._exhausted:
                continue
            try:
                with span(self._spans, "llm", schema_name, model=provider.label) as attrs:
                    result, usage = provider.complete_json(messages, schema, schema_name)
                    attrs["tokens_in"], attrs["tokens_out"] = (
                        usage.input_tokens,
                        usage.output_tokens,
                    )
                return result, usage
            except LLMQuotaExhausted as error:
                self._exhausted.add(index)
                last_error = error
            except LLMError as error:
                last_error = error
        if len(self._exhausted) == len(self._providers):
            raise LLMQuotaExhausted("every provider is out of daily quota")
        raise LLMError(f"every provider failed; last: {last_error}")


def build_chain(
    specs: list[str], settings: Settings, client: httpx.Client, spans: SpanSink
) -> FallbackChain | None:
    """Providers for the specs whose API key is set, in order; None when none are left."""
    keys = {"gemini": settings.gemini_api_key, "groq": settings.groq_api_key}
    providers: list[JsonLLM] = []
    for spec in specs:
        name, model = parse_spec(spec)
        key = keys[name]
        if key is not None:
            providers.append(
                OpenAICompatProvider(name, BASE_URLS[name], key.get_secret_value(), model, client)
            )
    return FallbackChain(providers, spans) if providers else None
