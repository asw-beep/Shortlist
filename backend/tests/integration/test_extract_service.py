"""run_extraction against Postgres: what gets written, what is retried, what is skipped."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog.models import Posting, PostingFeatures, PostingSkill, Skill, UnknownSkill
from app.core.config import REPO_ROOT
from app.extract import service
from app.extract.service import run_extraction, seed_skills
from app.extract.taxonomy import SkillMatcher
from app.llm.base import LLMError, LLMQuotaExhausted
from app.tracing.models import Span
from tests.fakes import FakeLLM, echo_requirements
from tests.integration.factories import make_posting

pytestmark = pytest.mark.integration

TAXONOMY = REPO_ROOT / "taxonomy" / "skills.yaml"
M = SkillMatcher.from_yaml(TAXONOMY)


@pytest.fixture(autouse=True)
def skills(db: Session) -> None:
    seed_skills(db, TAXONOMY)


def relevant_posting(db: Session, **kw) -> Posting:
    return make_posting(
        db,
        title=kw.pop("title", "Backend Engineer Intern"),
        location_raw=kw.pop("location_raw", "Bengaluru, India"),
        description=kw.pop("description", "Python and PostgreSQL."),
        **kw,
    )


def features(db: Session, posting: Posting) -> PostingFeatures:
    db.expire_all()
    return db.get(PostingFeatures, posting.id)


def test_seed_skills_is_idempotent(db: Session) -> None:
    before = db.scalar(select(func.count()).select_from(Skill))
    seed_skills(db, TAXONOMY)
    assert db.scalar(select(func.count()).select_from(Skill)) == before == len(M.names)


def test_run_extraction_writes_features_and_skills(db: Session) -> None:
    posting = relevant_posting(db)
    summary = run_extraction(db, FakeLLM(echo_requirements()), M)
    f = features(db, posting)
    assert summary.llm == 1
    assert (f.stage, f.relevant, f.llm_pending, f.seniority) == ("llm", True, False, "intern")
    assert f.summary == "Backend internship building APIs."
    skills = dict(
        db.execute(
            select(Skill.name, PostingSkill.kind)
            .join(PostingSkill, PostingSkill.skill_id == Skill.id)
            .where(PostingSkill.posting_id == posting.id)
        ).all()
    )
    assert skills == {"Python": "required", "PostgreSQL": "required", "Docker": "nice"}
    db.refresh(posting)
    assert posting.processed_hash == posting.content_hash
    assert "Backend internship building APIs." in posting.summary_text


def test_irrelevant_postings_skip_llm(db: Session) -> None:
    posting = make_posting(db, title="Account Executive", location_raw="London")
    llm = FakeLLM([])
    summary = run_extraction(db, llm, M)
    f = features(db, posting)
    assert llm.calls == [] and summary.irrelevant == 1
    assert (f.stage, f.relevant, f.llm_pending) == ("rules", False, False)


def test_second_run_is_noop(db: Session) -> None:
    relevant_posting(db)
    run_extraction(db, FakeLLM(echo_requirements()), M)
    llm = FakeLLM([])
    summary = run_extraction(db, llm, M)
    assert llm.calls == [] and (summary.llm, summary.rules_only, summary.irrelevant) == (0, 0, 0)


def test_changed_content_is_reprocessed(db: Session) -> None:
    posting = relevant_posting(db)
    run_extraction(db, FakeLLM(echo_requirements()), M)
    posting.content_hash = "changed"
    db.commit()
    assert run_extraction(db, FakeLLM(echo_requirements()), M).llm == 1


def test_version_bump_reprocesses(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    relevant_posting(db)
    run_extraction(db, FakeLLM(echo_requirements()), M)
    monkeypatch.setattr(service, "EXTRACTOR_VERSION", service.EXTRACTOR_VERSION + 1)
    assert run_extraction(db, FakeLLM(echo_requirements()), M).llm == 1


def test_llm_error_keeps_rules_only_and_marks_pending(db: Session) -> None:
    posting = relevant_posting(db)
    summary = run_extraction(db, FakeLLM([LLMError("down")]), M)
    f = features(db, posting)
    assert summary.pending == 1
    assert (f.stage, f.llm_pending, f.relevant) == ("rules", True, True)
    db.refresh(posting)
    assert posting.processed_hash == posting.content_hash


def test_pending_postings_are_retried_next_run(db: Session) -> None:
    posting = relevant_posting(db)
    run_extraction(db, FakeLLM([LLMError("down")]), M)
    run_extraction(db, FakeLLM(echo_requirements()), M)
    f = features(db, posting)
    assert (f.stage, f.llm_pending) == ("llm", False)


def test_no_llm_configured_marks_pending(db: Session) -> None:
    posting = relevant_posting(db)
    summary = run_extraction(db, None, M)
    assert summary.pending == 1 and features(db, posting).llm_pending is True


def test_quota_exhaustion_stops_llm_and_marks_pending(db: Session) -> None:
    postings = [relevant_posting(db, external_id=f"p{i}") for i in range(10)]
    script = [echo_requirements(), LLMQuotaExhausted("daily")]
    calls = []

    def handler(messages):
        calls.append(1)
        step = script[min(len(calls), len(script)) - 1]
        if isinstance(step, Exception):
            raise step
        return step(messages)

    summary = run_extraction(db, FakeLLM(handler), M, batch_size=4)
    assert len(calls) == 2  # batch 1 answered, batch 2 hit the quota, batch 3 never sent
    assert (summary.llm, summary.pending) == (4, 6)
    pending = [features(db, p).llm_pending for p in postings]
    assert pending.count(True) == 6


def test_unknown_skills_recorded(db: Session) -> None:
    relevant_posting(db, external_id="a")
    relevant_posting(db, external_id="b")
    run_extraction(db, FakeLLM(echo_requirements(required_skills=["Zorblang"])), M)
    row = db.scalar(select(UnknownSkill).where(UnknownSkill.name == "Zorblang"))
    assert row is not None and row.seen_count == 2


def test_llm_upgrade_can_make_posting_irrelevant(db: Session) -> None:
    posting = relevant_posting(db, title="Backend Engineer")
    run_extraction(
        db, FakeLLM(echo_requirements(min_years=5, seniority="mid", is_internship=False)), M
    )
    assert features(db, posting).relevant is False


def test_closed_postings_are_not_extracted(db: Session) -> None:
    from datetime import UTC, datetime

    relevant_posting(db, status="closed", closed_at=datetime.now(UTC))
    llm = FakeLLM([])
    run_extraction(db, llm, M)
    assert llm.calls == []


def test_llm_calls_recorded_as_spans(db: Session) -> None:
    from app.llm.chain import FallbackChain
    from app.tracing.spans import DbSpanSink

    relevant_posting(db)
    chain = FallbackChain([FakeLLM(echo_requirements())], DbSpanSink(db))
    run_extraction(db, chain, M)
    db.commit()
    [row] = db.scalars(select(Span).where(Span.kind == "llm")).all()
    assert (row.name, row.model, row.status) == ("job_requirements_batch", "fake:model", "ok")


def test_new_features_are_embedded_again(db: Session) -> None:
    """A posting embedded from rules-only features gets a new vector once the LLM fills them in
    (the document text is built from the features, not only from the posting's content)."""
    from app.embed.service import run_embedding
    from tests.fakes import FakeEmbedder

    posting = relevant_posting(db)
    run_extraction(db, FakeLLM([LLMError("down")]), M)
    assert run_embedding(db, FakeEmbedder()) == 1
    assert run_embedding(db, FakeEmbedder()) == 0
    run_extraction(db, FakeLLM(echo_requirements(summary="Build payment APIs in Go.")), M)
    assert run_embedding(db, FakeEmbedder()) == 1
    db.refresh(posting)
    assert posting.embedded_hash == posting.content_hash


def test_impossible_years_from_the_llm_do_not_stop_the_run(db: Session) -> None:
    posting = relevant_posting(db)
    summary = run_extraction(db, FakeLLM(echo_requirements(min_years=150)), M)
    assert summary.llm == 1 and features(db, posting).min_years is None
