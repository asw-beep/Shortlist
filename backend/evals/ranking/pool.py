"""Pool the top 20 of each ranking variant per query, for relevance labelling.

    uv run python -m evals.ranking.pool --snapshot evals/data/corpus-<date>.jsonl.gz

Writes evals/ranking/pool.jsonl: one line per (query, posting) to judge, already-judged pairs
in qrels.json left out.
"""

import argparse
import json

from evals.ranking.common import HERE, VARIANTS, EvalContext


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--qrels", default=str(HERE / "qrels.json"))
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--out", default=str(HERE / "pool.jsonl"))
    args = parser.parse_args(argv)

    pairs: dict[tuple[str, str], list[str]] = {}
    with EvalContext.open(args.snapshot, args.qrels) as ctx:
        for query in ctx.queries:
            for variant in VARIANTS:
                for job in ctx.search(query, variant, limit=args.depth):
                    key = (query["id"], str(job.posting_id))
                    if key[1] not in ctx.qrels.get(query["id"], {}):
                        pairs.setdefault(key, []).append(variant)
    with open(args.out, "w", encoding="utf-8") as handle:
        for (query_id, posting_id), variants in sorted(pairs.items()):
            line = {"query": query_id, "posting": posting_id, "variants": variants}
            handle.write(json.dumps(line) + "\n")
    print(f"{len(pairs)} pairs to judge across {len(ctx.queries)} queries → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
