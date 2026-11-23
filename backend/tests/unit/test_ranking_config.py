"""config/ranking.yaml: the weights and constants the ranking SQL uses."""

from pathlib import Path

import pytest

from app.core.config import REPO_ROOT
from app.search.config import RankingConfig, Weights, load_ranking_config


def test_committed_config_has_the_spec_values() -> None:
    config = load_ranking_config(REPO_ROOT / "config" / "ranking.yaml")
    assert config == RankingConfig(
        weights=Weights(
            skill=0.30, rrf=0.25, experience=0.15, location=0.10, recency=0.10, personal=0.10
        ),
        rrf_k=60,
        candidates=100,
        recency_days=14,
        personal_ramp=10,
    )


def test_weights_must_sum_to_one(tmp_path: Path) -> None:
    path = tmp_path / "ranking.yaml"
    path.write_text(
        "weights: {skill: 0.5, rrf: 0.5, experience: 0.5, location: 0, recency: 0, personal: 0}\n"
        "rrf_k: 60\ncandidates: 100\nrecency_days: 14\npersonal_ramp: 10\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sum to 1"):
        load_ranking_config(path)
