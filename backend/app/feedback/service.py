"""Record what students do with postings, and learn a taste vector from it (Rocchio).

taste = normalize(mean(saved) − 0.5 · mean(dismissed)); a missing side counts as zero and a
zero vector is stored as NULL. Saved and dismissed exclude each other: recording one removes
the other, so a posting never pulls the taste both ways.
"""

import uuid
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.models import EMBEDDING_DIM, Posting
from app.feedback.models import UNIQUE_KINDS, Interaction
from app.profiles.models import Profile
from app.search.service import RankedJob

Kind = Literal["shown", "clicked", "saved", "dismissed", "applied"]
Surface = Literal["feed", "digest", "chat"]
OPPOSITE = {"saved": "dismissed", "dismissed": "saved"}
DISMISS_WEIGHT = 0.5


def record(
    db: Session,
    *,
    user_id: uuid.UUID,
    posting_id: uuid.UUID,
    kind: Kind,
    surface: Surface,
    rank: int | None = None,
) -> bool:
    """Store one event. Saved/dismissed/applied happen at most once; True if a row was added."""
    if kind in OPPOSITE:
        undo(db, user_id=user_id, posting_id=posting_id, kind=OPPOSITE[kind])
    statement = insert(Interaction).values(
        user_id=user_id, posting_id=posting_id, kind=kind, surface=surface, rank=rank
    )
    if kind in UNIQUE_KINDS:
        statement = statement.on_conflict_do_nothing(
            index_elements=["user_id", "posting_id", "kind"],
            index_where=Interaction.kind.in_(UNIQUE_KINDS),
        )
    inserted = db.execute(statement.returning(Interaction.id)).first()
    return inserted is not None


def undo(
    db: Session, *, user_id: uuid.UUID, posting_id: uuid.UUID, kind: Literal["saved", "dismissed"]
) -> bool:
    result = db.execute(
        delete(Interaction).where(
            Interaction.user_id == user_id,
            Interaction.posting_id == posting_id,
            Interaction.kind == kind,
        )
    )
    return result.rowcount > 0


def record_impressions(
    db: Session, *, user_id: uuid.UUID, items: Sequence[RankedJob], surface: Surface
) -> None:
    if not items:
        return
    rows = [
        {
            "user_id": user_id,
            "posting_id": item.posting_id,
            "kind": "shown",
            "surface": surface,
            "rank": rank,
        }
        for rank, item in enumerate(items, start=1)
    ]
    db.execute(insert(Interaction), rows)


def _mean_embedding(db: Session, user_id: uuid.UUID, kind: str) -> np.ndarray | None:
    mean = db.scalar(
        select(func.avg(Posting.embedding, type_=Vector(EMBEDDING_DIM)))
        .join(Interaction, Interaction.posting_id == Posting.id)
        .where(
            Interaction.user_id == user_id,
            Interaction.kind == kind,
            Posting.embedding.is_not(None),
        )
    )
    return None if mean is None else np.asarray(mean, dtype=np.float64)


def recompute_taste(db: Session, user_id: uuid.UUID) -> None:
    saved = _mean_embedding(db, user_id, "saved")
    dismissed = _mean_embedding(db, user_id, "dismissed")
    taste = np.zeros(1)
    if saved is not None:
        taste = saved
    if dismissed is not None:
        taste = taste - DISMISS_WEIGHT * dismissed
    norm = float(np.linalg.norm(taste))
    vector = (taste / norm).tolist() if norm > 1e-9 else None
    feedback_count = db.scalar(
        select(func.count()).where(
            Interaction.user_id == user_id, Interaction.kind.in_(("saved", "dismissed"))
        )
    )
    db.execute(
        update(Profile)
        .where(Profile.user_id == user_id)
        .values(taste_vector=vector, feedback_count=feedback_count)
    )
