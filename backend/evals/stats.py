"""Statistics for the evaluation reports: bootstrap CIs, skill P/R/F1, agreement, ranx metrics."""

import random
from collections import Counter
from collections.abc import Callable, Hashable, Sequence

from ranx import Qrels, Run, evaluate


def bootstrap_metric[T](
    items: Sequence[T],
    metric: Callable[[Sequence[T]], float],
    *,
    n: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI of `metric` over items resampled with replacement."""
    if not items:
        raise ValueError("bootstrap needs at least one item")
    rng = random.Random(seed)
    stats = sorted(metric(rng.choices(items, k=len(items))) for _ in range(n))
    low = stats[int(alpha / 2 * n)]
    high = stats[max(int((1 - alpha / 2) * n) - 1, 0)]
    return low, high


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def bootstrap_ci(
    values: list[float], *, n: int = 2000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float]:
    """95% (by default) percentile bootstrap CI of the mean."""
    return bootstrap_metric(values, mean, n=n, seed=seed, alpha=alpha)


def skill_counts(gold: set[str], pred: set[str]) -> tuple[int, int, int]:
    return len(gold & pred), len(pred - gold), len(gold - pred)


def prf_from_counts(counts: Sequence[tuple[int, int, int]]) -> tuple[float, float, float]:
    tp = sum(c[0] for c in counts)
    fp = sum(c[1] for c in counts)
    fn = sum(c[2] for c in counts)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def skill_prf(gold: list[set[str]], pred: list[set[str]]) -> tuple[float, float, float]:
    """Micro-averaged precision, recall and F1 over all postings' skill sets."""
    return prf_from_counts([skill_counts(g, p) for g, p in zip(gold, pred, strict=True)])


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equally long, non-empty label lists")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[k] * count_b[k] for k in count_a.keys() | count_b.keys()) / n**2
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def evaluate_run(
    qrels: dict[str, dict[str, int]], run: dict[str, dict[str, float]], metrics: list[str]
) -> dict[str, float]:
    """ranx metrics averaged over queries. nDCG uses linear gains (Järvelin & Kekäläinen)."""
    scores = evaluate(Qrels(qrels), Run(run), metrics)
    if isinstance(scores, dict):
        return {name: float(value) for name, value in scores.items()}
    return {metrics[0]: float(scores)}


def per_query(
    qrels: dict[str, dict[str, int]], run: dict[str, dict[str, float]], metric: str
) -> dict[str, float]:
    """One metric for each query, for bootstrap CIs over queries."""
    ranx_run = Run(run)
    evaluate(Qrels(qrels), ranx_run, [metric], return_mean=False, save_results_in_run=True)
    return {query: float(score) for query, score in ranx_run.scores[metric].items()}
