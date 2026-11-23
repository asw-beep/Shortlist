"""Search and ranking: one SQL statement, hard filters first, explained scores."""

import math
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Board, Company
from app.core.config import REPO_ROOT
from app.search.config import load_ranking_config
from app.search.service import search
from app.tracing.models import Span
from tests.fakes import FakeEmbedder
from tests.integration.api import bearer, problem_code, registered_and_logged_in
from tests.integration.factories import make_board
from tests.integration.search_helpers import NOW, interact, job, profile

pytestmark = pytest.mark.integration

CONFIG = load_ranking_config(REPO_ROOT / "config" / "ranking.yaml")
E = FakeEmbedder()


def ids(results) -> list:
    return [r.posting_id for r in results]


def run(db: Session, uid, query: str | None = "python backend", **kw):
    return search(db, E, kw.pop("config", CONFIG), user_id=uid, query=query, now=NOW, **kw)


def test_hard_filters_exclude_closed_irrelevant_wrong_role_senior_dismissed_avoided_and_foreign_onsite(  # noqa: E501
    db: Session,
) -> None:
    keep = job(db, "Python Backend Intern", required=("Python",))
    excluded = [
        job(db, "Python Backend Intern closed", status="closed", closed_at=NOW),
        job(db, "Python Backend Intern irrelevant", relevant=False),
        job(db, "Python Data Intern", role_family="data"),
        job(db, "Senior Python Backend Engineer", seniority="senior"),
        job(db, "Python Backend Intern at Avoided", company="AvoidCo"),
        job(db, "Python Backend Intern SF", country="US", city=None),
        job(db, "Python Backend Intern Pune", city="Pune"),
        job(db, "Python Mid Backend", seniority="mid"),
    ]
    dismissed = job(db, "Python Backend Intern dismissed")
    applied = job(db, "Python Backend Intern applied")
    saved = job(db, "Python Backend Intern saved")
    uid = profile(db, avoid=("avoidco",))
    interact(db, uid, dismissed, "dismissed")
    interact(db, uid, applied, "applied")
    interact(db, uid, saved, "saved")
    excluded += [dismissed, applied]
    results = ids(run(db, uid))
    assert saved.id in results
    assert keep.id in results
    assert not set(results) & {p.id for p in excluded}


def test_unknown_seniority_passes_the_filter(db: Session) -> None:
    posting = job(db, "Python Backend Engineer", seniority="unknown")
    assert posting.id in ids(run(db, profile(db)))


def test_india_without_a_city_passes_with_half_location_fit(db: Session) -> None:
    posting = job(db, "Python Backend Intern", city=None)
    [result] = run(db, profile(db, open_to_relocate=False))
    assert result.posting_id == posting.id and result.factors["location"] == 0.5


def test_relocation_opens_other_indian_cities(db: Session) -> None:
    pune = job(db, "Python Backend Intern", city="Pune")
    assert pune.id in ids(run(db, profile(db, open_to_relocate=True)))


def test_empty_locations_mean_anywhere_in_india(db: Session) -> None:
    pune = job(db, "Python Backend Intern", city="Pune")
    assert pune.id in ids(run(db, profile(db, locations=())))


def test_remote_postings_need_remote_ok(db: Session) -> None:
    remote = job(db, "Python Backend Intern", city=None, country=None, remote_scope="remote_global")
    assert remote.id in ids(run(db, profile(db, remote_ok=True)))
    assert remote.id not in ids(run(db, profile(db, remote_ok=False)))


def test_foreign_remote_is_excluded(db: Session) -> None:
    us_remote = job(
        db, "Python Backend Intern", city=None, country="US", remote_scope="remote_country"
    )
    assert us_remote.id not in ids(run(db, profile(db)))


def test_factors_sum_to_score(db: Session) -> None:
    job(db, "Python Backend Intern", required=("Python", "Go"), nice=("Docker",), min_years=1)
    job(db, "Backend Intern", required=("Java",), first_seen_at=NOW - timedelta(days=3))
    w = CONFIG.weights
    for r in run(db, profile(db)):
        expected = sum(getattr(w, name) * value for name, value in r.factors.items())
        assert abs(expected - r.score) < 1e-6
        assert set(r.factors) == {"skill", "rrf", "experience", "location", "recency", "personal"}


def test_more_matched_required_skills_ranks_higher(db: Session) -> None:
    both = job(db, "Backend Intern A", required=("Python", "PostgreSQL"))
    one = job(db, "Backend Intern B", required=("Python", "Rust"))
    results = run(db, profile(db, skills={"Python": 3, "PostgreSQL": 2}), query=None)
    by_id = {r.posting_id: r for r in results}
    assert by_id[both.id].factors["skill"] == 1.0 and by_id[one.id].factors["skill"] == 0.5
    assert by_id[both.id].matched_skills == ["PostgreSQL", "Python"]
    assert by_id[one.id].missing_skills == ["Rust"]


def test_experience_fit_penalises_years_short(db: Session) -> None:
    posting = job(db, "Python Backend Engineer", seniority="entry", min_years=2)
    [result] = [r for r in run(db, profile(db, years=0.5)) if r.posting_id == posting.id]
    assert result.factors["experience"] == pytest.approx(0.25)


def test_keyword_only_match_is_retrieved(db: Session) -> None:
    far = [0.0] * 383 + [1.0]  # nowhere near any text vector
    rare = job(db, "Zigbee Firmware Intern", embedding=far)
    for i in range(3):
        job(db, f"Python Backend Intern {i}")
    tight = replace(CONFIG, candidates=2)
    query = "zigbee firmware intern"  # the "intern" postings beat the far vector on cosine
    assert FakeEmbedder.vector(query)[383] == 0
    by_id = {r.posting_id: r for r in run(db, profile(db), query=query, config=tight)}
    # rrf 0.5 = rank 1 in the keyword list and absent from the dense top 2
    assert by_id[rare.id].factors["rrf"] == pytest.approx(0.5)


def test_recency_decays_with_tau_14(db: Session) -> None:
    new = job(db, "Python Backend Intern", company="New")
    old = job(db, "Python Backend Intern", company="Old", first_seen_at=NOW - timedelta(days=14))
    by_id = {r.posting_id: r for r in run(db, profile(db))}
    assert by_id[new.id].factors["recency"] == pytest.approx(1.0)
    assert by_id[old.id].factors["recency"] == pytest.approx(math.exp(-1), rel=1e-6)


def test_skill_factor_is_capped_at_one(db: Session) -> None:
    job(db, "Python Backend Intern", required=("Python",), nice=("Docker",))
    [result] = run(db, profile(db, skills={"Python": 3, "Docker": 2}))
    assert result.factors["skill"] == 1.0


def test_personal_zero_without_feedback(db: Session) -> None:
    job(db, "Python Backend Intern")
    assert all(r.factors["personal"] == 0 for r in run(db, profile(db)))


def test_personal_ramps_with_feedback(db: Session) -> None:
    posting = job(db, "Python Backend Intern")
    uid = profile(db, taste_vector=posting.embedding, feedback_count=5)
    [result] = run(db, uid)
    assert result.factors["personal"] == pytest.approx(0.5)  # cosine 1, ramp 5/10


def test_since_filters_by_first_seen(db: Session) -> None:
    old = job(db, "Python Backend Intern", company="Old", first_seen_at=NOW - timedelta(days=10))
    new = job(db, "Python Backend Intern", company="New")
    results = ids(run(db, profile(db), since=NOW - timedelta(days=1)))
    assert new.id in results and old.id not in results


def test_exclude_ids(db: Session) -> None:
    posting = job(db, "Python Backend Intern")
    assert posting.id not in ids(run(db, profile(db), exclude_ids=[posting.id]))


def test_feed_collapses_duplicate_roles(db: Session) -> None:
    first = job(db, "Python Backend Intern", company="Same")
    other_board = make_board(db, db.get(Company, db.get(Board, first.board_id).company_id))
    job(db, "python backend intern", board=other_board)
    job(db, "Python Backend Intern", city="Hyderabad", board=other_board)
    uid = profile(db, locations=("Bengaluru", "Hyderabad"))
    titles = sorted((r.title.lower(), r.city) for r in run(db, uid))
    assert titles == [
        ("python backend intern", "Bengaluru"),
        ("python backend intern", "Hyderabad"),
    ]


def test_variants_differ_only_in_scoring(db: Session) -> None:
    for i in range(4):
        job(db, f"Python Backend Intern {i}", required=("Python",))
    uid = profile(db)
    sets = {
        v: set(ids(run(db, uid, query="python", variant=v)))
        for v in ("fts", "dense", "hybrid", "utility", "full")
    }
    assert len({frozenset(s) for s in sets.values()}) == 1


def test_search_records_sql_span(db: Session) -> None:
    job(db, "Python Backend Intern")
    run(db, profile(db))
    db.flush()
    assert db.scalar(select(Span).where(Span.kind == "sql", Span.name == "search")) is not None


@pytest.fixture
def feed_app(db_app: FastAPI) -> FastAPI:
    db_app.state.embedder = FakeEmbedder()
    return db_app


def test_feed_without_profile_is_409(api: TestClient, feed_app: FastAPI) -> None:
    _, tokens = registered_and_logged_in(api)
    response = api.get("/api/v1/feed", headers=bearer(tokens["access_token"]))
    assert response.status_code == 409 and problem_code(response) == "profile-incomplete"


def put_profile(api: TestClient, headers: dict) -> None:
    body = {"target_roles": ["software"], "locations": ["Bengaluru"], "skills": []}
    assert api.put("/api/v1/profile", json=body, headers=headers).status_code == 200


def test_punctuation_query_falls_back_to_dense(
    api: TestClient, feed_app: FastAPI, db: Session
) -> None:
    job(db, "Python Backend Intern")
    _, tokens = registered_and_logged_in(api)
    headers = bearer(tokens["access_token"])
    put_profile(api, headers)
    response = api.get("/api/v1/feed", params={"q": "!!! ??"}, headers=headers)
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1


def test_feed_endpoint_returns_items_and_query_used(
    api: TestClient, feed_app: FastAPI, db: Session
) -> None:
    job(db, "Python Backend Intern", required=("Python",))
    _, tokens = registered_and_logged_in(api)
    headers = bearer(tokens["access_token"])
    put_profile(api, headers)
    body = api.get("/api/v1/feed", headers=headers).json()
    assert body["query_used"].startswith("software engineer")
    [item] = body["items"]
    assert set(item) >= {
        "posting_id",
        "title",
        "company",
        "url",
        "score",
        "factors",
        "matched_skills",
        "missing_skills",
    }


def test_stopword_query_has_no_keyword_leg(db: Session) -> None:
    posting = job(db, "Python Backend Intern")
    [result] = run(db, profile(db), query="the of and")
    assert result.posting_id == posting.id  # dense alone still retrieves
    assert result.factors["rrf"] == pytest.approx(0.5)  # rank 1 in one list of two
