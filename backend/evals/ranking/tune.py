"""Grid-search the ranking weights on 70% of the judged queries; report on the other 30%.

    uv run python -m evals.ranking.tune --snapshot evals/data/corpus-<date>.jsonl.gz \
        --qrels evals/ranking/qrels.json

Factors do not depend on the weights, so each query's candidates and their six factors are
fetched once (variant "full", personal weight kept) and every weight vector is scored in
NumPy. Writes config/ranking.tuned.yaml; it is never applied automatically.
"""

import argparse
import random
from datetime import date
from itertools import combinations
from pathlib import Path

import numpy as np
import yaml

from app.core.config import REPO_ROOT
from app.search.service import FACTORS
from evals.stats import evaluate_run


def weight_grid(k: int, *, step: float = 0.05) -> list[tuple[float, ...]]:
    """Every k-tuple of non-negative multiples of `step` that sums to 1."""
    units = round(1 / step)
    grid = []
    for bars in combinations(range(units + k - 1), k - 1):  # stars and bars
        edges = (-1, *bars, units + k - 1)
        parts = [edges[i + 1] - edges[i] - 1 for i in range(k)]
        grid.append(tuple(round(p * step, 10) for p in parts))
    return grid


def rescore(factors: dict[str, list[float]], weights: tuple[float, ...]) -> dict[str, float]:
    w = np.asarray(weights)
    return {doc: float(np.dot(w, values)) for doc, values in factors.items()}


def best_weights(
    candidates: dict[str, dict[str, list[float]]],
    qrels: dict[str, dict[str, int]],
    grid: list[tuple[float, ...]],
    *,
    metric: str = "ndcg@10",
) -> tuple[tuple[float, ...], float]:
    """The grid point with the highest mean metric on these queries (ties: first found)."""
    queries = [q for q in candidates if q in qrels]
    docs = {q: list(candidates[q]) for q in queries}
    matrices = {q: np.asarray([candidates[q][d] for d in docs[q]]) for q in queries}
    best, best_score = grid[0], -1.0
    for weights in grid:
        w = np.asarray(weights)
        run = {q: dict(zip(docs[q], (matrices[q] @ w).tolist(), strict=True)) for q in queries}
        score = evaluate_run({q: qrels[q] for q in queries}, run, [metric])[metric]
        if score > best_score:
            best, best_score = weights, score
    return best, best_score


def split(queries: list[str], *, train: float = 0.7, seed: int = 0) -> tuple[list[str], list[str]]:
    shuffled = sorted(queries)
    random.Random(seed).shuffle(shuffled)
    cut = round(len(shuffled) * train)
    return shuffled[:cut], shuffled[cut:]


def main(argv: list[str] | None = None) -> int:
    from evals.ranking.common import EvalContext

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--qrels", required=True)
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--out", default=str(REPO_ROOT / "config" / "ranking.tuned.yaml"))
    args = parser.parse_args(argv)

    with EvalContext.open(args.snapshot, args.qrels) as ctx:
        excluded = ctx.seed_personal()  # same personal-feedback seeds as evals.ranking.run
        qrels = ctx.scoring_qrels(excluded)
        candidates = ctx.candidate_factors(excluded)
        initial = tuple(getattr(ctx.config.weights, name) for name in FACTORS)
    train, test = split([q for q in candidates if q in qrels])
    grid = weight_grid(len(FACTORS), step=args.step)
    tuned, train_score = best_weights({q: candidates[q] for q in train}, qrels, grid)
    held_out = {q: candidates[q] for q in test}
    scores = {
        name: best_weights(held_out, qrels, [weights])[1]
        for name, weights in (("initial", initial), ("tuned", tuned))
    }
    out = Path(args.out)
    out.write_text(
        f"# Tuned {date.today()} on {len(train)} queries; not applied automatically.\n"
        f"# Held-out nDCG@10 ({len(test)} queries): initial {scores['initial']:.4f},"
        f" tuned {scores['tuned']:.4f}.\n"
        + yaml.safe_dump(
            {"weights": dict(zip(FACTORS, tuned, strict=True))}
            | {k: v for k, v in ctx.raw_config.items() if k != "weights"},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    print(f"train nDCG@10 {train_score:.4f} over {len(train)} queries; grid {len(grid)} points")
    print(f"held-out nDCG@10: initial {scores['initial']:.4f}, tuned {scores['tuned']:.4f}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
