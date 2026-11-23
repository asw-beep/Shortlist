"""Stage B: one LLM call per batch of postings, answers matched back by id."""

from app.extract.llm import ExtractionItem, extract_batch
from tests.fakes import FakeLLM, echo_requirements, posting_ids


def item(pid: str, description: str = "Python") -> ExtractionItem:
    return ExtractionItem(pid, "SWE Intern", "Acme", "Pune", description)


def test_extract_batch_returns_requirements_by_id() -> None:
    llm = FakeLLM(echo_requirements(min_years=1))
    result = extract_batch(llm, [item("a"), item("b")])
    assert set(result) == {"a", "b"}
    assert result["a"].min_years == 1 and result["a"].required_skills == ["Python", "PostgreSQL"]


def test_extract_batch_truncates_descriptions() -> None:
    llm = FakeLLM(echo_requirements())
    extract_batch(llm, [item("a", "x" * 10_000)])
    prompt = llm.calls[0][-1]["content"]
    assert "x" * 6_000 in prompt and "x" * 6_001 not in prompt


def test_extract_batch_drops_unknown_and_missing_ids() -> None:
    def handler(messages):
        ids = posting_ids(messages)
        answer = echo_requirements()(messages)
        answer["items"] = [answer["items"][0], {**answer["items"][0], "id": "stranger"}]
        assert ids == ["a", "b"]
        return answer

    result = extract_batch(FakeLLM(handler), [item("a"), item("b")])
    assert set(result) == {"a"}


def test_extract_batch_empty_is_no_call() -> None:
    llm = FakeLLM([])
    assert extract_batch(llm, []) == {}
    assert llm.calls == []
