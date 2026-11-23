"""The contract every LLM provider meets: messages in, a validated Pydantic object out."""

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Usage:
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


class LLMError(Exception):
    """The call failed, but another provider (or a later retry) may succeed."""


class LLMQuotaExhausted(LLMError):
    """This provider's daily allowance is used up: don't call it again this run."""


class JsonLLM(Protocol):
    label: str

    def complete_json(
        self, messages: list[dict[str, str]], schema: type[T], schema_name: str
    ) -> tuple[T, Usage]: ...


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema in the shape strict structured output wants: $defs inlined,
    every property required (optional ones are nullable), no extra properties, no titles."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def clean(node: Any) -> Any:
        if isinstance(node, list):
            return [clean(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return clean(defs[node["$ref"].split("/")[-1]])
        out = {k: clean(v) for k, v in node.items() if k not in ("title", "default")}
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out

    return clean(raw)
