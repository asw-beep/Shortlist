"""Compare the five ranking variants on judged queries; write docs/evaluation/ranking-<date>.md.

    uv run python -m evals.ranking.run --snapshot evals/data/corpus-<date>.jsonl.gz \
        --qrels evals/ranking/qrels.json [--second-qrels evals/ranking/qrels.<name>.json]

Personal term: per profile, 3 relevant and 3 non-relevant judged postings become saves and
dismissals first; they are then left out of every variant's results and of the scoring.
Significance: paired Student's t-test between variants (ranx.compare), p < 0.05.
"""

import argparse
import shlex
import sys
from datetime import date
from pathlib import Path

from ranx import Qrels, Run, compare

from app.core.config import REPO_ROOT
from evals.ranking.common import VARIANTS, EvalContext, read_qrels
from evals.stats import bootstrap_ci, cohen_kappa, per_query

METRICS = ("ndcg@10", "recall@20", "mrr")


def agreement(first: dict, second: dict) -> tuple[int, float, float] | None:
    pairs = [
        (first[q][d], grade)
        for q, docs in second.items()
        for d, grade in docs.items()
        if d in first.get(q, {})
    ]
    if not pairs:
        return None
    a, b = [x for x, _ in pairs], [y for _, y in pairs]
    binary = cohen_kappa([x >= 1 for x in a], [y >= 1 for y in b])
    return len(pairs), cohen_kappa(a, b), binary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--qrels", required=True)
    parser.add_argument("--second-qrels", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    with EvalContext.open(args.snapshot, args.qrels) as ctx:
        if not ctx.qrels:
            raise SystemExit("no judgments yet: run evals.ranking.pool and evals.ranking.label")
        excluded = ctx.seed_personal()
        qrels = ctx.scoring_qrels(excluded)
        runs = {variant: ctx.run(variant, excluded) for variant in VARIANTS}
        sha, now, n_postings, n_profiles = (
            ctx.snapshot_sha256,
            ctx.now,
            len(ctx.postings),
            len(ctx.profiles),
        )
    runs = {v: {q: runs[v].get(q) or {} for q in qrels} for v in VARIANTS}

    rows = []
    for variant in VARIANTS:
        cells = []
        for metric in METRICS:
            values = list(per_query(qrels, runs[variant], metric).values())
            low, high = bootstrap_ci(values)
            cells.append(f"{sum(values) / len(values):.3f} [{low:.3f}, {high:.3f}]")
        rows.append(f"| {variant} | " + " | ".join(cells) + " |")
    report = compare(
        Qrels(qrels),
        [Run(runs[v], name=v) for v in VARIANTS],
        metrics=list(METRICS),
        max_p=0.05,
        stat_test="student",
    )
    judgments = sum(len(docs) for docs in qrels.values())
    command = "uv run python -m evals.ranking.run " + shlex.join(
        sys.argv[1:] if argv is None else argv
    )
    lines = [
        f"# Ranking evaluation, {date.today().isoformat()}",
        "",
        f"- Snapshot: `{Path(args.snapshot).name}` (sha256 `{sha[:16]}…`), {n_postings} postings,"
        f" rankings computed as of {now.isoformat(timespec='minutes')}",
        f"- {n_profiles} profiles, {len(qrels)} judged queries, {judgments} judgments"
        f" (after removing {sum(len(v) for v in excluded.values())} personal-feedback seeds)",
        "- Grades: 2 would apply, 1 maybe, 0 not for this student. nDCG uses linear gains.",
        "- Intervals: 95% percentile bootstrap over queries (2,000 resamples, seed 0).",
        "",
        "| Variant | nDCG@10 | Recall@20 | MRR |",
        "|---|---|---|---|",
        *rows,
        "",
        "Paired t-tests (ranx; superscripts mark variants this one beats at p < 0.05):",
        "",
        "```",
        str(report),
        "```",
    ]
    if args.second_qrels:
        kappa = agreement(read_qrels(args.qrels), read_qrels(args.second_qrels))
        lines += ["", "## Labeller agreement", ""]
        lines += (
            [
                f"{kappa[0]} doubly judged pairs: Cohen's κ {kappa[1]:.2f} on 0/1/2,"
                f" {kappa[2]:.2f} on relevant (≥ 1) vs not."
            ]
            if kappa
            else ["No overlapping judgments yet."]
        )
    lines += ["", "Reproduce:", "", "```bash", command, "```", ""]
    out = Path(args.out or REPO_ROOT / "docs" / "evaluation" / f"ranking-{date.today()}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
