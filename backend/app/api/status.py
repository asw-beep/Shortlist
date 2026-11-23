"""GET /status: a public health page for the pipeline, search and digests (spec §6.1, §6.5, §7.4).

Aggregates only: no user data leaves this endpoint.
"""

from datetime import date, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.db.session import DbSession

router = APIRouter(tags=["status"])


class LastIngest(BaseModel):
    started_at: datetime
    finished_at: datetime | None
    boards_ok: int
    boards_failed: int


class FailingBoard(BaseModel):
    company: str
    ats: str
    slug: str
    consecutive_failures: int


class Latency(BaseModel):
    p50: float | None
    p95: float | None


class DigestWeek(BaseModel):
    week: date
    sent: int
    save_rate_at5: float | None
    dismiss_rate: float | None


class StatusOut(BaseModel):
    last_ingest: LastIngest | None
    open_postings: int
    relevant_postings: int
    failing_boards: list[FailingBoard]
    llm_calls_today: dict[str, int]
    freshness_hours_p50: float | None
    search_latency_ms: Latency
    digests: list[DigestWeek]


LAST_INGEST = text(
    "SELECT started_at, finished_at, boards_ok, boards_failed FROM ingest_runs"
    " ORDER BY started_at DESC LIMIT 1"
)
POSTING_COUNTS = text(
    "SELECT count(*) AS open, count(*) FILTER (WHERE f.relevant) AS relevant"
    " FROM postings p LEFT JOIN posting_features f ON f.posting_id = p.id"
    " WHERE p.status = 'open'"
)
FAILING_BOARDS = text(
    "SELECT c.name AS company, b.ats, b.slug, b.consecutive_failures"
    " FROM boards b JOIN companies c ON c.id = b.company_id"
    " WHERE b.consecutive_failures > 0"
    " ORDER BY b.consecutive_failures DESC, c.name"
)
LLM_CALLS_TODAY = text(
    "SELECT coalesce(model, 'unknown') AS model, count(*) AS calls FROM spans"
    " WHERE kind = 'llm' AND created_at >= date_trunc('day', now() AT TIME ZONE 'UTC')"
    " AT TIME ZONE 'UTC' GROUP BY 1 ORDER BY 1"
)
FRESHNESS = text(
    "SELECT percentile_cont(0.5) WITHIN GROUP ("
    "  ORDER BY extract(epoch FROM embedded_at - first_seen_at) / 3600.0)"
    " FROM postings"
    " WHERE first_seen_at >= now() - interval '7 days' AND embedded_at IS NOT NULL"
)
SEARCH_LATENCY = text(
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50,"
    "       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95"
    " FROM spans"
    " WHERE kind = 'sql' AND name = 'search' AND created_at >= now() - interval '24 hours'"
)
# save_rate_at5: digest impressions at rank <= 5 that got a saved row within 7 days.
DIGEST_WEEKS = text(
    """
    WITH weeks AS (
        SELECT date_trunc('week', sent_at AT TIME ZONE 'UTC')::date AS week, count(*) AS sent
        FROM digest_runs
        WHERE status = 'sent'
          AND sent_at >= (date_trunc('week', now() AT TIME ZONE 'UTC') - interval '3 weeks')
                         AT TIME ZONE 'UTC'
        GROUP BY 1
    ),
    shown AS (
        SELECT date_trunc('week', s.created_at AT TIME ZONE 'UTC')::date AS week,
               EXISTS (SELECT 1 FROM interactions x
                       WHERE x.user_id = s.user_id AND x.posting_id = s.posting_id
                         AND x.kind = 'saved'
                         AND x.created_at BETWEEN s.created_at
                                              AND s.created_at + interval '7 days') AS saved,
               EXISTS (SELECT 1 FROM interactions x
                       WHERE x.user_id = s.user_id AND x.posting_id = s.posting_id
                         AND x.kind = 'dismissed'
                         AND x.created_at BETWEEN s.created_at
                                              AND s.created_at + interval '7 days') AS dismissed
        FROM interactions s
        WHERE s.kind = 'shown' AND s.surface = 'digest' AND s.rank <= 5
    )
    SELECT w.week, w.sent,
           avg(sh.saved::int) AS save_rate_at5,
           avg(sh.dismissed::int) AS dismiss_rate
    FROM weeks w LEFT JOIN shown sh ON sh.week = w.week
    GROUP BY w.week, w.sent
    ORDER BY w.week DESC
    """
)


def _float(value: object) -> float | None:
    return None if value is None else float(value)


@router.get("/status", response_model=StatusOut)
def status(db: DbSession) -> StatusOut:
    last = db.execute(LAST_INGEST).mappings().first()
    counts = db.execute(POSTING_COUNTS).mappings().one()
    latency = db.execute(SEARCH_LATENCY).mappings().one()
    return StatusOut(
        last_ingest=LastIngest(**last) if last else None,
        open_postings=counts["open"],
        relevant_postings=counts["relevant"],
        failing_boards=[FailingBoard(**row) for row in db.execute(FAILING_BOARDS).mappings()],
        llm_calls_today={row.model: row.calls for row in db.execute(LLM_CALLS_TODAY)},
        freshness_hours_p50=_float(db.scalar(FRESHNESS)),
        search_latency_ms=Latency(p50=_float(latency["p50"]), p95=_float(latency["p95"])),
        digests=[
            DigestWeek(
                week=row["week"],
                sent=row["sent"],
                save_rate_at5=_float(row["save_rate_at5"]),
                dismiss_rate=_float(row["dismiss_rate"]),
            )
            for row in db.execute(DIGEST_WEEKS).mappings()
        ],
    )
