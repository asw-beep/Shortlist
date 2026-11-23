"""The LLM layer: one OpenAI-compatible provider, a fallback chain, and a span per attempt."""

import json

import httpx
import pytest
from pydantic import BaseModel

from app.llm.base import LLMError, LLMQuotaExhausted, strict_schema
from app.llm.chain import FallbackChain
from app.llm.openai_compat import OpenAICompatProvider
from app.tracing.spans import MemorySpanSink
from tests.fakes import FakeLLM


class Answer(BaseModel):
    text: str
    score: float | None


def provider(handler, model: str = "m") -> OpenAICompatProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatProvider("groq", "https://api.test/v1", "key", model, client)


def ok_body(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }


def test_strict_schema_requires_every_field_and_forbids_extras() -> None:
    schema = strict_schema(Answer)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"text", "score"}
    assert "title" not in schema and "title" not in schema["properties"]["text"]


def test_openai_compat_sends_strict_schema_and_parses() -> None:
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        sent["auth"] = request.headers["authorization"]
        sent["url"] = str(request.url)
        return httpx.Response(200, json=ok_body('```json\n{"text": "hi", "score": null}\n```'))

    answer, usage = provider(handler).complete_json([{"role": "user", "content": "x"}], Answer, "a")
    assert answer == Answer(text="hi", score=None)
    assert (usage.model, usage.input_tokens, usage.output_tokens) == ("groq:m", 12, 3)
    assert sent["url"] == "https://api.test/v1/chat/completions"
    assert sent["auth"] == "Bearer key"
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["temperature"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"message": "Rate limit reached on tokens per day (TPD): Limit 200000"}},
        [{"error": {"code": 429, "message": "Quota exceeded: GenerateRequestsPerDayPerProject"}}],
    ],
)
def test_openai_compat_daily_429_is_quota_exhausted(body) -> None:
    p = provider(lambda r: httpx.Response(429, json=body))
    with pytest.raises(LLMQuotaExhausted):
        p.complete_json([], Answer, "a")


def test_openai_compat_per_minute_429_is_plain_error() -> None:
    body = {"error": {"message": "Rate limit reached on requests per minute (RPM)"}}
    p = provider(lambda r: httpx.Response(429, json=body))
    with pytest.raises(LLMError) as error:
        p.complete_json([], Answer, "a")
    assert not isinstance(error.value, LLMQuotaExhausted)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={}),
        httpx.Response(200, json=ok_body("not json")),
        httpx.Response(200, json=ok_body('{"text": 1}')),
        httpx.Response(200, json={"unexpected": True}),
    ],
)
def test_openai_compat_bad_responses_are_llm_errors(response) -> None:
    with pytest.raises(LLMError):
        provider(lambda r: response).complete_json([], Answer, "a")


def test_openai_compat_transport_failure_is_llm_error() -> None:
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(LLMError):
        provider(handler).complete_json([], Answer, "a")


def test_chain_falls_back_on_llm_error() -> None:
    first = FakeLLM([LLMError("boom")])
    second = FakeLLM([{"text": "ok", "score": 1}])
    answer, _ = FallbackChain([first, second], MemorySpanSink()).complete_json([], Answer, "a")
    assert answer.text == "ok"


def test_chain_skips_quota_exhausted_provider_for_rest_of_run() -> None:
    first = FakeLLM([LLMQuotaExhausted("daily")])
    second = FakeLLM([{"text": "a", "score": None}, {"text": "b", "score": None}])
    chain = FallbackChain([first, second], MemorySpanSink())
    chain.complete_json([], Answer, "a")
    chain.complete_json([], Answer, "a")
    assert len(first.calls) == 1 and len(second.calls) == 2


def test_chain_raises_quota_when_all_exhausted() -> None:
    chain = FallbackChain(
        [FakeLLM([LLMQuotaExhausted("x")]), FakeLLM([LLMQuotaExhausted("y")])], MemorySpanSink()
    )
    with pytest.raises(LLMQuotaExhausted):
        chain.complete_json([], Answer, "a")
    with pytest.raises(LLMQuotaExhausted):  # and stays exhausted without calling anyone
        chain.complete_json([], Answer, "a")


def test_chain_raises_llm_error_when_all_fail() -> None:
    chain = FallbackChain([FakeLLM([LLMError("x")])], MemorySpanSink())
    with pytest.raises(LLMError):
        chain.complete_json([], Answer, "a")


def test_chain_records_a_span_per_attempt() -> None:
    sink = MemorySpanSink()
    chain = FallbackChain([FakeLLM([LLMError("x")]), FakeLLM([{"text": "ok", "score": 1}])], sink)
    chain.complete_json([], Answer, "extract")
    assert [(s.kind, s.name, s.status) for s in sink.records] == [
        ("llm", "extract", "error"),
        ("llm", "extract", "ok"),
    ]
    assert sink.records[1].tokens_in == 10
