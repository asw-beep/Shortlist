"""One ingest run: fetch every enabled board, store what changed, close what vanished.

Fetching is network-bound, so boards are fetched in a thread pool. Every database write
stays in the calling thread, on the one session, and is committed board by board: a crash
halfway through keeps the boards already done.

A posting closes only after it is missing from two runs in a row of a board that answered.
One miss is often an ATS hiccup; a board that failed to answer says nothing about its
postings, so it counts no misses at all.
"""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.catalog.models import Board, BoardRun, IngestRun, Posting
from app.ingest.ats import Ats, BoardFetchError, RawPosting, content_hash
from app.ingest.boards import FAILURE_LIMIT

MISSES_TO_CLOSE = 2
Fetch = Callable[[Ats, str], list[RawPosting]]


@dataclass
class IngestSummary:
    boards_ok: int = 0
    boards_failed: int = 0
    new: int = 0
    changed: int = 0
    closed: int = 0
    reopened: int = 0


@dataclass
class _Fetched:
    postings: list[RawPosting] | None
    error: BoardFetchError | None
    latency_ms: int


def _fetch_timed(fetch: Fetch, ats: Ats, slug: str) -> _Fetched:
    started = time.perf_counter()
    try:
        postings, error = fetch(ats, slug), None
    except BoardFetchError as failure:
        postings, error = None, failure
    return _Fetched(postings, error, round((time.perf_counter() - started) * 1000))


def run_ingest(db: Session, fetch: Fetch, *, now: datetime, workers: int = 8) -> IngestSummary:
    summary = IngestSummary()
    run = IngestRun(started_at=now)
    db.add(run)
    boards = list(db.scalars(select(Board).where(Board.enabled).order_by(Board.slug)))
    db.commit()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {b.id: pool.submit(_fetch_timed, fetch, b.ats, b.slug) for b in boards}
        for board in boards:
            result = futures[board.id].result()
            if result.error is not None:
                _record_failure(db, run, board, result)
                summary.boards_failed += 1
            else:
                _store_board(db, run, board, result, now, summary)
                summary.boards_ok += 1
            db.commit()

    run.finished_at = datetime.now(UTC)
    run.boards_ok, run.boards_failed = summary.boards_ok, summary.boards_failed
    run.postings_new, run.postings_changed = summary.new, summary.changed
    run.postings_closed = summary.closed
    db.commit()
    return summary


def _record_failure(db: Session, run: IngestRun, board: Board, result: _Fetched) -> None:
    assert result.error is not None
    board.consecutive_failures += 1
    if board.consecutive_failures >= FAILURE_LIMIT:
        board.enabled = False
    db.add(
        BoardRun(
            ingest_run_id=run.id,
            board_id=board.id,
            status="failed",
            failure_reason=result.error.reason,
            latency_ms=result.latency_ms,
        )
    )


def _store_board(
    db: Session,
    run: IngestRun,
    board: Board,
    result: _Fetched,
    now: datetime,
    summary: IngestSummary,
) -> None:
    assert result.postings is not None
    unique = {p.external_id: p for p in reversed(result.postings)}  # first occurrence wins
    existing = {
        p.external_id: p for p in db.scalars(select(Posting).where(Posting.board_id == board.id))
    }
    for external_id, raw in unique.items():
        digest = content_hash(raw)
        posting = existing.get(external_id)
        if posting is None:
            db.add(
                Posting(
                    board_id=board.id,
                    external_id=external_id,
                    url=raw.url,
                    title=raw.title,
                    location_raw=raw.location_raw,
                    description=raw.description_text,
                    source_metadata=raw.source_metadata,
                    content_hash=digest,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            summary.new += 1
            continue
        if posting.content_hash != digest:
            summary.changed += 1
        if posting.status == "closed":
            posting.status, posting.closed_at = "open", None
            summary.reopened += 1
        posting.url, posting.title = raw.url, raw.title
        posting.location_raw, posting.description = raw.location_raw, raw.description_text
        posting.source_metadata, posting.content_hash = raw.source_metadata, digest
        posting.last_seen_at, posting.missed_runs = now, 0
    db.flush()

    db.execute(
        update(Posting)
        .where(Posting.board_id == board.id, Posting.status == "open", Posting.last_seen_at < now)
        .values(missed_runs=Posting.missed_runs + 1)
    )
    closed = db.execute(
        update(Posting)
        .where(
            Posting.board_id == board.id,
            Posting.status == "open",
            Posting.missed_runs >= MISSES_TO_CLOSE,
        )
        .values(status="closed", closed_at=now)
        .returning(Posting.id)
    ).all()
    summary.closed += len(closed)

    board.consecutive_failures = 0
    db.add(
        BoardRun(
            ingest_run_id=run.id,
            board_id=board.id,
            status="ok",
            postings_seen=len(unique),
            latency_ms=result.latency_ms,
        )
    )


def purge_closed(db: Session, *, now: datetime, after_days: int = 30) -> int:
    """Drop the description of postings closed more than `after_days` ago. The row stays."""
    rows = db.execute(
        update(Posting)
        .where(
            Posting.status == "closed",
            Posting.closed_at < now - timedelta(days=after_days),
            Posting.description.is_not(None),
        )
        .values(description=None)
        .returning(Posting.id)
    ).all()
    db.commit()
    return len(rows)
