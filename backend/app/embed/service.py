"""run_embedding: embed relevant open postings whose content changed since last embedded."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.catalog.models import Board, Company, Posting, PostingFeatures, PostingSkill, Skill
from app.embed.model import Embedder, document_text


def run_embedding(db: Session, embedder: Embedder, *, batch_size: int = 64) -> int:
    skills = (
        select(
            PostingSkill.posting_id,
            func.array_agg(Skill.name).filter(PostingSkill.kind == "required").label("names"),
        )
        .join(Skill, Skill.id == PostingSkill.skill_id)
        .group_by(PostingSkill.posting_id)
        .subquery()
    )
    query = (
        select(
            Posting.id,
            Posting.content_hash,
            Posting.title,
            Company.name,
            PostingFeatures.city,
            PostingFeatures.remote_scope,
            PostingFeatures.summary,
            skills.c.names,
        )
        .join(PostingFeatures, PostingFeatures.posting_id == Posting.id)
        .join(Board, Board.id == Posting.board_id)
        .join(Company, Company.id == Board.company_id)
        .outerjoin(skills, skills.c.posting_id == Posting.id)
        .where(
            Posting.status == "open",
            PostingFeatures.relevant,
            Posting.embedded_hash.is_distinct_from(Posting.content_hash),
        )
        .order_by(Posting.first_seen_at.desc())
    )
    rows = db.execute(query).all()
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [
            document_text(
                title=r.title,
                company=r.name,
                city=r.city,
                remote_scope=r.remote_scope,
                summary=r.summary,
                skills=sorted(r.names or []),
            )
            for r in batch
        ]
        for row, vector in zip(batch, embedder.embed_documents(texts), strict=True):
            db.execute(
                update(Posting)
                .where(Posting.id == row.id)
                .values(embedding=vector, embedded_hash=row.content_hash, embedded_at=func.now())
            )
        db.commit()
    return len(rows)
