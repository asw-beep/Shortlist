"""The statistics the evaluation reports rest on."""

import math

import pytest

from evals.ranking.tune import rescore, weight_grid
from evals.stats import bootstrap_ci, cohen_kappa, evaluate_run, skill_prf


def test_bootstrap_ci_deterministic_and_contains_mean() -> None:
    values = [0.2, 0.4, 0.4, 0.6, 0.9, 1.0, 0.0, 0.5]
    first = bootstrap_ci(values, n=500, seed=7)
    assert first == bootstrap_ci(values, n=500, seed=7)
    low, high = first
    assert low <= sum(values) / len(values) <= high
    assert 0.0 <= low < high <= 1.0


def test_bootstrap_ci_of_constant_values_is_a_point() -> None:
    assert bootstrap_ci([0.5] * 10) == (0.5, 0.5)


def test_skill_prf_known_values() -> None:
    assert skill_prf([{"a", "b"}], [{"a", "c"}]) == (0.5, 0.5, 0.5)


def test_skill_prf_is_micro_averaged() -> None:
    precision, recall, f1 = skill_prf([{"a"}, {"b", "c", "d"}], [{"a"}, {"b"}])
    assert (precision, recall) == (1.0, 0.5)
    assert f1 == pytest.approx(2 / 3)


def test_skill_prf_with_nothing_predicted_is_zero_not_an_error() -> None:
    assert skill_prf([{"a"}], [set()]) == (0.0, 0.0, 0.0)


def test_cohen_kappa_known_value() -> None:
    # 8 of 10 agree; each rater says 1 five times, so chance agreement is 0.5: κ = 0.3 / 0.5
    a = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    b = [1, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    assert cohen_kappa(a, b) == pytest.approx(0.6)


def test_ranx_ndcg_on_toy_qrels() -> None:
    """ranx's README example; nDCG with linear gains (Järvelin & Kekäläinen)."""
    qrels = {"q_1": {"d_12": 5, "d_25": 3}, "q_2": {"d_11": 6, "d_22": 1}}
    run = {
        "q_1": {"d_12": 0.9, "d_23": 0.8, "d_25": 0.7, "d_36": 0.6, "d_32": 0.5, "d_35": 0.4},
        "q_2": {"d_12": 0.9, "d_11": 0.8, "d_25": 0.7, "d_36": 0.6, "d_22": 0.5, "d_35": 0.4},
    }
    q1 = (5 + 3 / math.log2(4)) / (5 + 3 / math.log2(3))
    q2 = (6 / math.log2(3) + 1 / math.log2(6)) / (6 + 1 / math.log2(3))
    scores = evaluate_run(qrels, run, ["ndcg@5", "mrr"])
    assert scores["ndcg@5"] == pytest.approx((q1 + q2) / 2, rel=1e-6)
    assert scores["mrr"] == pytest.approx((1 + 1 / 2) / 2)


def test_weight_grid_sums_to_one_in_steps_of_005() -> None:
    grid = weight_grid(3, step=0.05)
    assert len(grid) == math.comb(20 + 2, 2)
    assert all(abs(sum(w) - 1) < 1e-9 for w in grid)
    assert (1.0, 0.0, 0.0) in grid


def test_rescore_orders_by_weighted_factors() -> None:
    factors = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
    assert rescore(factors, (0.7, 0.3)) == {"a": 0.7, "b": 0.3}


def test_per_query_scores_each_query() -> None:
    from evals.stats import per_query

    qrels = {"a": {"d1": 1}, "b": {"d2": 2}}
    run = {"a": {"d1": 1.0}, "b": {"d3": 1.0}}
    assert per_query(qrels, run, "ndcg@10") == {"a": 1.0, "b": 0.0}
