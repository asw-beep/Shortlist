"""Test doubles for the outside world: an LLM that answers from a script."""

import re
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from app.llm.base import Usage

T = TypeVar("T", bound=BaseModel)
Handler = Callable[[list[dict[str, str]]], dict[str, Any]]


class FakeLLM:
    """Answers complete_json from a handler, or from a queue of payloads and exceptions."""

    label = "fake:model"

    def __init__(self, script: Handler | list[dict[str, Any] | Exception]) -> None:
        self._script = script
        self.calls: list[list[dict[str, str]]] = []

    def complete_json(
        self, messages: list[dict[str, str]], schema: type[T], schema_name: str
    ) -> tuple[T, Usage]:
        self.calls.append(messages)
        if callable(self._script):
            payload: dict[str, Any] | Exception = self._script(messages)
        else:
            payload = self._script.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return schema.model_validate(payload), Usage(self.label, 10, 5, 1)


def posting_ids(messages: list[dict[str, str]]) -> list[str]:
    return re.findall(r'<posting id="([^"]+)"', messages[-1]["content"])


def echo_requirements(**overrides: Any) -> Handler:
    """A handler that answers every posting in the prompt with the same requirements."""

    def handler(messages: list[dict[str, str]]) -> dict[str, Any]:
        base = {
            "required_skills": ["Python", "PostgreSQL"],
            "nice_to_have_skills": ["Docker"],
            "min_years": None,
            "seniority": "intern",
            "is_internship": True,
            "is_new_grad": False,
            "remote_policy": "unknown",
            "stipend_or_salary": None,
            "education": None,
            "one_line_summary": "Backend internship building APIs.",
        }
        base.update(overrides)
        return {"items": [{"id": pid, **base} for pid in posting_ids(messages)]}

    return handler
