"""Shared setup for the ranking evaluation: an eval database, the snapshot, the profiles.

Everything runs against a separate database (EVAL_DATABASE_URL, default
postgresql+psycopg://shortlist:shortlist@localhost:5432/shortlist_eval) whose name must end in
"_eval", so an eval run can never write students or interactions into a real database. The
schema is migrated, the snapshot loaded and one user per profile created, idempotently.

Search runs with `now` = the snapshot's export time, so recency, and therefore every ranking,
is the same whenever the eval runs.
"""

import json
import os
import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, make_url, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, get_settings
from app.embed.model import Embedder, FastEmbedder
from app.extract.taxonomy import SkillMatcher
from app.feedback.models import Interaction
from app.feedback.service import recompute_taste, record
from app.identity.models import User
from app.profiles.schemas import ProfileIn, SkillIn
from app.profiles.service import upsert_profile
from app.search.config import RankingConfig, load_ranking_config
from app.search.service import FACTORS, RankedJob, search
from evals.snapshot import load_snapshot, read_snapshot, sha256

HERE = Path(__file__).parent
BACKEND = HERE.parents[1]
DEFAULT_URL = "postgresql+psycopg://shortlist:shortlist@localhost:5432/shortlist_eval"
VARIANTS = ("fts", "dense", "hybrid", "utility", "full")
SEEDS_PER_SIDE = 3


def eval_database_url() -> str:
    url = os.environ.get("EVAL_DATABASE_URL", DEFAULT_URL)
    if not (make_url(url).database or "").endswith("_eval"):
        raise SystemExit(f"refusing to run: the eval database name must end in _eval ({url})")
    return url


def migrate(url: str) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND / "migrations"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def load_profiles(path: Path = HERE / "profiles.yaml") -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in yaml.safe_load(path.read_text(encoding="utf-8")) or []}


def load_queries(path: Path = HERE / "queries.yaml") -> list[dict[str, Any]]:
    """Each profile gets a feed query (no text) plus the free-text queries listed for it."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    queries = []
    for profile_id, texts in data.items():
        queries.append({"id": f"{profile_id}/feed", "profile": profile_id, "q": None})
        for i, text in enumerate(texts or [], start=1):
            queries.append({"id": f"{profile_id}/q{i}", "profile": profile_id, "q": text})
    return queries


def read_qrels(path: str | Path | None) -> dict[str, dict[str, int]]:
    if path is None or not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_user(db: Session, matcher: SkillMatcher, profile: dict[str, Any]) -> uuid.UUID:
    email = f"eval-{profile['id']}@shortlist.invalid"
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, full_name=f"Eval {profile['id']}", password_hash="!")
        db.add(user)
        db.flush()
    body = ProfileIn(
        target_roles=profile["target_roles"],
        seniority_ok=profile.get("seniority_ok", ["intern", "new_grad", "entry"]),
        years_experience=profile.get("years_experience", 0),
        locations=profile.get("locations", []),
        open_to_relocate=profile.get("open_to_relocate", True),
        remote_ok=profile.get("remote_ok", True),
        skills=[SkillIn(name=n, level=lvl) for n, lvl in profile.get("skills", {}).items()],
        avoid_companies=profile.get("avoid_companies", []),
        digest_opt_in=False,
    )
    upsert_profile(db, matcher, user.id, body)
    db.execute(delete(Interaction).where(Interaction.user_id == user.id))  # fresh every run
    recompute_taste(db, user.id)
    return user.id


@dataclass
class EvalContext:
    db: Session
    snapshot: Path
    now: datetime
    config: RankingConfig
    raw_config: dict[str, Any]
    profiles: dict[str, dict[str, Any]]
    queries: list[dict[str, Any]]
    qrels: dict[str, dict[str, int]]
    users: dict[str, uuid.UUID]
    embedder: Embedder
    postings: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    @contextmanager
    def open(
        cls,
        snapshot: str | Path,
        qrels: str | Path | None = None,
        *,
        embedder: Embedder | None = None,
    ) -> Iterator["EvalContext"]:
        url = eval_database_url()
        migrate(url)
        settings = get_settings()
        engine = create_engine(url)
        config_path = REPO_ROOT / "config" / "ranking.yaml"
        header, items = read_snapshot(Path(snapshot))
        matcher = SkillMatcher.from_yaml(settings.repo_path(settings.taxonomy_path))
        try:
            with Session(engine, expire_on_commit=False) as db:
                load_snapshot(db, Path(snapshot))
                profiles = load_profiles()
                users = {pid: ensure_user(db, matcher, p) for pid, p in profiles.items()}
                db.commit()
                yield cls(
                    db=db,
                    snapshot=Path(snapshot),
                    now=datetime.fromisoformat(header["exported_at"]),
                    config=load_ranking_config(config_path),
                    raw_config=yaml.safe_load(config_path.read_text(encoding="utf-8")),
                    profiles=profiles,
                    queries=[q for q in load_queries() if q["profile"] in profiles],
                    qrels=read_qrels(qrels),
                    users=users,
                    embedder=embedder
                    or FastEmbedder(settings.embed_model, settings.embed_cache_dir, threads=None),
                    postings={item["id"]: item for item in items},
                )
        finally:
            engine.dispose()

    @property
    def snapshot_sha256(self) -> str:
        return sha256(self.snapshot)

    def search(
        self,
        query: dict[str, Any],
        variant: str,
        *,
        limit: int = 20,
        exclude: set[str] = frozenset(),
    ) -> list[RankedJob]:
        return search(
            self.db,
            self.embedder,
            self.config,
            user_id=self.users[query["profile"]],
            query=query["q"],
            limit=limit,
            variant=variant,  # type: ignore[arg-type]
            now=self.now,
            exclude_ids=[uuid.UUID(e) for e in exclude],
        )

    def run(self, variant: str, excluded: dict[str, set[str]], limit: int = 20) -> dict:
        """ranx run: query → {posting: score}, scores by rank so ties never reorder."""
        runs = {}
        for query in self.queries:
            results = self.search(
                query, variant, limit=limit, exclude=excluded.get(query["profile"], set())
            )
            runs[query["id"]] = {str(r.posting_id): float(limit - i) for i, r in enumerate(results)}
        return runs

    def candidate_factors(
        self, excluded: dict[str, set[str]] | None = None
    ) -> dict[str, dict[str, list[float]]]:
        out = {}
        for query in self.queries:
            results = self.search(
                query,
                "full",
                limit=self.config.candidates,
                exclude=(excluded or {}).get(query["profile"], set()),
            )
            out[query["id"]] = {
                str(r.posting_id): [r.factors[name] for name in FACTORS] for r in results
            }
        return out

    def seed_personal(self, seed: int = 0) -> dict[str, set[str]]:
        """Per profile: 3 relevant and 3 non-relevant judged postings become saves and
        dismissals (training feedback). Returns them, to exclude from scoring."""
        rng = random.Random(seed)
        excluded: dict[str, set[str]] = {}
        for profile_id, user_id in self.users.items():
            grades: dict[str, int] = {}
            for query in self.queries:
                if query["profile"] == profile_id:
                    for doc, grade in self.qrels.get(query["id"], {}).items():
                        grades[doc] = max(grade, grades.get(doc, 0))
            relevant = sorted(d for d, g in grades.items() if g >= 1)
            irrelevant = sorted(d for d, g in grades.items() if g == 0)
            saved = rng.sample(relevant, min(SEEDS_PER_SIDE, len(relevant)))
            dismissed = rng.sample(irrelevant, min(SEEDS_PER_SIDE, len(irrelevant)))
            for doc, kind in [(d, "saved") for d in saved] + [(d, "dismissed") for d in dismissed]:
                record(
                    self.db,
                    user_id=user_id,
                    posting_id=uuid.UUID(doc),
                    kind=kind,  # type: ignore[arg-type]
                    surface="feed",
                )
            recompute_taste(self.db, user_id)
            excluded[profile_id] = set(saved) | set(dismissed)
        self.db.commit()
        return excluded

    def scoring_qrels(self, excluded: dict[str, set[str]]) -> dict[str, dict[str, int]]:
        """Judgments minus the seed items, for queries that have any judgments left."""
        out = {}
        for query in self.queries:
            judged = self.qrels.get(query["id"], {})
            kept = {d: g for d, g in judged.items() if d not in excluded.get(query["profile"], ())}
            if kept:
                out[query["id"]] = kept
        return out
