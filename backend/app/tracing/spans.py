"""Record what the system did and how long it took, in Postgres, queryable with SQL.

    with span(sink, "sql", "search") as attrs:
        ...                       # run the thing
        attrs["model"] = "..."    # optional extra fields

On exit the span is written with its latency, and status "error" if the block raised (the
exception still propagates).
"""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.tracing.models import Span


@dataclass
class SpanRecord:
    kind: str
    name: str
    latency_ms: int
    status: str
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    trace_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None


class SpanSink(Protocol):
    def add(self, record: SpanRecord) -> None: ...


class NullSpanSink:
    def add(self, record: SpanRecord) -> None:
        pass


@dataclass
class MemorySpanSink:
    records: list[SpanRecord] = field(default_factory=list)

    def add(self, record: SpanRecord) -> None:
        self.records.append(record)


class DbSpanSink:
    """Adds span rows to the caller's session; they are saved when the caller commits."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def add(self, record: SpanRecord) -> None:
        self._db.add(Span(**vars(record)))


@contextmanager
def span(sink: SpanSink, kind: str, name: str, **attrs: Any) -> Iterator[dict[str, Any]]:
    started = time.perf_counter()
    status, error = "ok", None
    try:
        yield attrs
    except Exception as failure:
        status, error = "error", f"{type(failure).__name__}: {failure}"[:500]
        raise
    finally:
        latency = round((time.perf_counter() - started) * 1000)
        sink.add(
            SpanRecord(
                kind=kind, name=name, latency_ms=latency, status=status, error=error, **attrs
            )
        )
