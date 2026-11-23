"""Ranking weights and constants, read from config/ranking.yaml."""

import math
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Weights:
    skill: float
    rrf: float
    experience: float
    location: float
    recency: float
    personal: float

    def as_dict(self) -> dict[str, float]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True)
class RankingConfig:
    weights: Weights
    rrf_k: int
    candidates: int
    recency_days: float
    personal_ramp: int


def load_ranking_config(path: Path) -> RankingConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    weights = Weights(**{name: float(value) for name, value in data["weights"].items()})
    total = sum(weights.as_dict().values())
    if not math.isclose(total, 1.0, abs_tol=1e-6):
        raise ValueError(f"ranking weights must sum to 1.0, got {total:.6f}")
    return RankingConfig(
        weights=weights,
        rrf_k=int(data["rrf_k"]),
        candidates=int(data["candidates"]),
        recency_days=float(data["recency_days"]),
        personal_ramp=int(data["personal_ramp"]),
    )
