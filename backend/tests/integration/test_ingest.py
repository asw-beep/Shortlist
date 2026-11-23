"""Ingest: change detection, two-miss closing, reopening, board health, purge."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Board, BoardRun, Posting
from app.ingest.ats import BoardFetchError, RawPosting, content_hash
from app.ingest.boards import BoardSpec, sync_boards
from app.ingest.service import purge_closed, run_ingest
from tests.integration.factories import make_board, make_posting

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


def raw(
    external_id: str = "1", description: str = "Python", title: str = "SWE Intern"
) -> RawPosting:
    return RawPosting(external_id, f"https://x.test/{external_id}", title, "Pune", description, {})


def fetch_from(boards: dict[str, list[RawPosting] | Exception]) -> Callable:
    def fetch(ats: str, slug: str) -> list[RawPosting]:
        result = boards[slug]
        if isinstance(result, Exception):
            raise result
        return result

    return fetch


def postings_of(db: Session, board: Board) -> list[Posting]:
    db.expire_all()
    return list(db.scalars(select(Posting).where(Posting.board_id == board.id)))


def test_new_posting_inserted_open_with_first_seen(db: Session) -> None:
    board = make_board(db, slug="acme")
    summary = run_ingest(db, fetch_from({"acme": [raw("1")]}), now=T0)
    [posting] = postings_of(db, board)
    assert (summary.new, summary.boards_ok) == (1, 1)
    assert posting.status == "open"
    assert posting.first_seen_at == T0 and posting.last_seen_at == T0
    assert posting.content_hash == content_hash(raw("1"))
    assert posting.processed_hash is None


def test_unchanged_posting_keeps_hashes_and_last_seen_updates(db: Session) -> None:
    board = make_board(db, slug="acme")
    run_ingest(db, fetch_from({"acme": [raw("1")]}), now=T0)
    [posting] = postings_of(db, board)
    posting.processed_hash = posting.content_hash
    db.commit()
    later = T0 + timedelta(hours=6)
    summary = run_ingest(db, fetch_from({"acme": [raw("1")]}), now=later)
    [posting] = postings_of(db, board)
    assert summary.changed == 0 and summary.new == 0
    assert posting.processed_hash == posting.content_hash
    assert posting.last_seen_at == later and posting.first_seen_at == T0


def test_changed_description_updates_content_hash_only(db: Session) -> None:
    board = make_board(db, slug="acme")
    run_ingest(db, fetch_from({"acme": [raw("1", "Python")]}), now=T0)
    [posting] = postings_of(db, board)
    posting.processed_hash = posting.content_hash
    db.commit()
    summary = run_ingest(
        db, fetch_from({"acme": [raw("1", "Python and Go")]}), now=T0 + timedelta(hours=6)
    )
    [posting] = postings_of(db, board)
    assert summary.changed == 1
    assert posting.content_hash == content_hash(raw("1", "Python and Go"))
    assert posting.processed_hash != posting.content_hash  # needs processing again


def test_missing_once_stays_open_missing_twice_closes(db: Session) -> None:
    board = make_board(db, slug="acme")
    run_ingest(db, fetch_from({"acme": [raw("1"), raw("2")]}), now=T0)
    t1, t2 = T0 + timedelta(hours=6), T0 + timedelta(hours=12)
    run_ingest(db, fetch_from({"acme": [raw("1")]}), now=t1)
    gone = {p.external_id: p for p in postings_of(db, board)}["2"]
    assert (gone.status, gone.missed_runs) == ("open", 1)
    summary = run_ingest(db, fetch_from({"acme": [raw("1")]}), now=t2)
    gone = {p.external_id: p for p in postings_of(db, board)}["2"]
    assert summary.closed == 1
    assert (gone.status, gone.closed_at) == ("closed", t2)


def test_reappearing_posting_reopens(db: Session) -> None:
    board = make_board(db, slug="acme")
    run_ingest(db, fetch_from({"acme": [raw("1"), raw("2")]}), now=T0)
    for hours in (6, 12):
        run_ingest(db, fetch_from({"acme": [raw("1")]}), now=T0 + timedelta(hours=hours))
    summary = run_ingest(
        db, fetch_from({"acme": [raw("1"), raw("2")]}), now=T0 + timedelta(hours=18)
    )
    back = {p.external_id: p for p in postings_of(db, board)}["2"]
    assert summary.reopened == 1
    assert (back.status, back.missed_runs, back.closed_at) == ("open", 0, None)


def test_failed_board_does_not_count_misses(db: Session) -> None:
    board = make_board(db, slug="acme")
    run_ingest(db, fetch_from({"acme": [raw("1")]}), now=T0)
    for hours in (6, 12, 18):
        summary = run_ingest(
            db, fetch_from({"acme": BoardFetchError("timeout")}), now=T0 + timedelta(hours=hours)
        )
    [posting] = postings_of(db, board)
    assert summary.boards_failed == 1
    assert (posting.status, posting.missed_runs) == ("open", 0)


def test_five_consecutive_failures_disable_board(db: Session) -> None:
    board = make_board(db, slug="acme")
    for i in range(4):
        run_ingest(
            db, fetch_from({"acme": BoardFetchError("http_error")}), now=T0 + timedelta(hours=i)
        )
    db.refresh(board)
    assert (board.enabled, board.consecutive_failures) == (True, 4)
    run_ingest(db, fetch_from({"acme": BoardFetchError("http_error")}), now=T0 + timedelta(hours=5))
    db.refresh(board)
    assert (board.enabled, board.consecutive_failures) == (False, 5)


def test_success_resets_failure_count(db: Session) -> None:
    board = make_board(db, slug="acme")
    run_ingest(db, fetch_from({"acme": BoardFetchError("timeout")}), now=T0)
    run_ingest(db, fetch_from({"acme": [raw("1")]}), now=T0 + timedelta(hours=6))
    db.refresh(board)
    assert board.consecutive_failures == 0


def test_disabled_boards_are_not_fetched(db: Session) -> None:
    make_board(db, slug="off", enabled=False)
    summary = run_ingest(db, fetch_from({}), now=T0)  # a fetch of "off" would KeyError
    assert summary.boards_ok == summary.boards_failed == 0


def test_board_runs_record_reason_and_latency(db: Session) -> None:
    ok, bad = make_board(db, slug="ok"), make_board(db, slug="bad")
    run_ingest(db, fetch_from({"ok": [raw("1")], "bad": BoardFetchError("not_found")}), now=T0)
    runs = {r.board_id: r for r in db.scalars(select(BoardRun))}
    assert (runs[ok.id].status, runs[ok.id].postings_seen) == ("ok", 1)
    assert (runs[bad.id].status, runs[bad.id].failure_reason) == ("failed", "not_found")
    assert runs[ok.id].latency_ms >= 0


def test_duplicate_external_ids_in_one_payload_are_stored_once(db: Session) -> None:
    board = make_board(db, slug="acme")
    run_ingest(db, fetch_from({"acme": [raw("1"), raw("1", "other text")]}), now=T0)
    assert len(postings_of(db, board)) == 1


def test_purge_clears_description_after_30_days(db: Session) -> None:
    now = T0 + timedelta(days=60)
    old = make_posting(db, status="closed", closed_at=now - timedelta(days=31))
    recent = make_posting(db, status="closed", closed_at=now - timedelta(days=29))
    assert purge_closed(db, now=now) == 1
    db.refresh(old), db.refresh(recent)
    assert old.description is None and recent.description is not None


def test_sync_boards_creates_and_disables_removed_specs(db: Session) -> None:
    sync_boards(db, [BoardSpec("Acme", "lever", "acme"), BoardSpec("Beta", "ashby", "beta")])
    sync_boards(db, [BoardSpec("Acme", "lever", "acme")])
    boards = {b.slug: b for b in db.scalars(select(Board))}
    assert boards["acme"].enabled and not boards["beta"].enabled


def test_sync_boards_reenables_readded_but_not_failing_boards(db: Session) -> None:
    sync_boards(db, [BoardSpec("Acme", "lever", "acme")])
    sync_boards(db, [])
    sync_boards(db, [BoardSpec("Acme", "lever", "acme")])
    [board] = db.scalars(select(Board)).all()
    assert board.enabled
    board.consecutive_failures, board.enabled = 5, False
    db.commit()
    sync_boards(db, [BoardSpec("Acme", "lever", "acme")])
    db.refresh(board)
    assert not board.enabled  # disabled for failing stays disabled until fixed by hand
