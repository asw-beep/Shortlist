"""run_extraction: turn new or changed postings into stored features, cheaply.

Every posting gets Stage A (rules). Only relevant ones go to Stage B (the LLM), 8 per call.
If the LLM is unavailable, out of quota, or answers badly, the posting keeps its rules-only
features with llm_pending set, and the next run tries again. Results are stored per batch,
so a crash keeps the work already done.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.models import (
    Board,
    Company,
    Posting,
    PostingFeatures,
    PostingSkill,
    Skill,
    UnknownSkill,
)
from app.extract.llm import ExtractionItem, extract_batch
from app.extract.merge import FinalFeatures, merge_features
from app.extract.rules import RuleFeatures, extract_rules
from app.extract.taxonomy import SkillMatcher
from app.llm.base import JsonLLM, LLMError, LLMQuotaExhausted

# Bump when extraction logic changes enough that stored features should be redone.
EXTRACTOR_VERSION = 1


@dataclass
class ExtractionSummary:
    rules_only: int = 0
    llm: int = 0
    pending: int = 0
    irrelevant: int = 0


def seed_skills(db: Session, path: Path) -> int:
    """Load taxonomy/skills.yaml into the skills table (insert new, refresh aliases)."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    for entry in entries:
        stmt = insert(Skill).values(name=entry["name"], aliases=entry.get("aliases", []))
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[Skill.name], set_={"aliases": stmt.excluded.aliases}
            )
        )
    db.commit()
    return len(entries)


def _due(db: Session, limit: int | None) -> list[tuple[Posting, str]]:
    query = (
        select(Posting, Company.name)
        .join(Board, Board.id == Posting.board_id)
        .join(Company, Company.id == Board.company_id)
        .outerjoin(PostingFeatures, PostingFeatures.posting_id == Posting.id)
        .where(
            Posting.status == "open",
            or_(
                Posting.processed_hash.is_distinct_from(Posting.content_hash),
                PostingFeatures.posting_id.is_(None),
                PostingFeatures.extractor_version < EXTRACTOR_VERSION,
                PostingFeatures.llm_pending,
            ),
        )
        .order_by(Posting.first_seen_at.desc())
        .limit(limit)
    )
    return [(p, name) for p, name in db.execute(query).all()]


def run_extraction(
    db: Session,
    llm: JsonLLM | None,
    matcher: SkillMatcher,
    *,
    batch_size: int = 8,
    limit: int | None = None,
) -> ExtractionSummary:
    summary = ExtractionSummary()
    skill_ids = dict(db.execute(select(Skill.name, Skill.id)).all())
    queue: list[tuple[Posting, str, RuleFeatures]] = []
    for posting, company in _due(db, limit):
        rules = extract_rules(
            posting.title,
            posting.location_raw,
            posting.description or "",
            matcher,
            is_remote_flag=(posting.source_metadata or {}).get("isRemote"),
        )
        final = merge_features(rules, None, matcher)
        if final.relevant:
            queue.append((posting, company, rules))
        else:
            _store(db, posting, company, final, skill_ids, pending=False)
            summary.irrelevant += 1
    db.commit()

    exhausted = llm is None
    for start in range(0, len(queue), batch_size):
        batch = queue[start : start + batch_size]
        answers = {}
        if not exhausted:
            items = [
                ExtractionItem(str(p.id), p.title, company, p.location_raw, p.description or "")
                for p, company, _ in batch
            ]
            try:
                answers = extract_batch(llm, items)  # type: ignore[arg-type]
            except LLMQuotaExhausted:
                exhausted = True
            except LLMError:
                pass  # this batch waits for the next run; later batches still try
        for posting, company, rules in batch:
            answer = answers.get(str(posting.id))
            final = merge_features(rules, answer, matcher)
            _store(db, posting, company, final, skill_ids, pending=answer is None)
            if answer is None:
                summary.pending += 1
            else:
                summary.llm += 1
        db.commit()
    return summary


def _store(
    db: Session,
    posting: Posting,
    company: str,
    final: FinalFeatures,
    skill_ids: dict,
    *,
    pending: bool,
) -> None:
    values = {
        "extractor_version": EXTRACTOR_VERSION,
        "stage": final.stage,
        "llm_pending": pending and final.relevant,
        "role_family": final.role_family,
        "seniority": final.seniority,
        "is_internship": final.is_internship,
        "is_new_grad": final.is_new_grad,
        "min_years": final.min_years,
        "country": final.country,
        "city": final.city,
        "remote_scope": final.remote_scope,
        "relevant": final.relevant,
        "summary": final.summary,
        "stipend_or_salary": final.stipend_or_salary,
        "education": final.education,
    }
    stmt = insert(PostingFeatures).values(posting_id=posting.id, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=[PostingFeatures.posting_id], set_=values))

    db.execute(delete(PostingSkill).where(PostingSkill.posting_id == posting.id))
    rows = [
        {"posting_id": posting.id, "skill_id": skill_ids[name], "kind": kind}
        for kind, names in (("required", final.required), ("nice", final.nice))
        for name in sorted(names)
        if name in skill_ids
    ]
    if rows:
        db.execute(insert(PostingSkill).values(rows).on_conflict_do_nothing())
    for name in sorted(final.unknown):
        stmt = insert(UnknownSkill).values(name=name[:120])
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[UnknownSkill.name], set_={"seen_count": UnknownSkill.seen_count + 1}
            )
        )

    posting.summary_text = " ".join(filter(None, [posting.title, company, final.summary]))
    posting.processed_hash = posting.content_hash
