"""Judge pooled (query, posting) pairs: 2 = would apply, 1 = maybe, 0 = not for this student.

    uv run python -m evals.ranking.label --snapshot evals/data/corpus-<date>.jsonl.gz
    uv run python -m evals.ranking.label --snapshot … --labeler priya   # second labeller

Keys: 0 / 1 / 2 label, s skips, q quits. Every key is saved at once (qrels.json, or
qrels.<labeler>.json), so you can stop and resume any time. A second labeller sees a fixed
10% sample of the pool, for Cohen's κ in the report.
"""

import argparse
import json
import random
import textwrap
from pathlib import Path

from evals.keys import read_key
from evals.ranking.common import HERE, load_profiles, load_queries, read_qrels
from evals.snapshot import read_snapshot

SECOND_LABELLER_SHARE = 0.10


def show(profile: dict, query: dict, posting: dict) -> None:
    features = posting["features"]
    skills = ", ".join(s["name"] for s in posting["skills"]) or "none extracted"
    place = features.get("city") or features.get("remote_scope")
    print("\n" + "=" * 78)
    print(
        f"STUDENT {profile['id']}: {', '.join(profile['target_roles'])}; "
        f"skills {', '.join(profile.get('skills', {}))}; "
        f"places {', '.join(profile.get('locations', [])) or 'anywhere in India'}"
    )
    print(f"QUERY   {query['q'] or '(feed: no query)'}")
    print("-" * 78)
    print(f"{posting['title']} — {posting['company']['name']} · {place}")
    print(f"level {features.get('seniority')}, min years {features.get('min_years')}")
    print(f"skills: {skills}")
    print(textwrap.fill((features.get("summary") or posting["description"])[:700], width=78))
    print(posting["url"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--pool", default=str(HERE / "pool.jsonl"))
    parser.add_argument("--labeler", default=None)
    args = parser.parse_args(argv)

    out = Path(HERE / (f"qrels.{args.labeler}.json" if args.labeler else "qrels.json"))
    qrels = read_qrels(out)
    _, items = read_snapshot(Path(args.snapshot))
    postings = {item["id"]: item for item in items}
    profiles = load_profiles()
    queries = {q["id"]: q for q in load_queries()}
    pool = [json.loads(line) for line in Path(args.pool).read_text(encoding="utf-8").splitlines()]
    if args.labeler:
        pool = random.Random(0).sample(pool, max(1, round(len(pool) * SECOND_LABELLER_SHARE)))
    todo = [p for p in pool if p["posting"] not in qrels.get(p["query"], {})]
    print(f"{len(todo)} to judge ({len(pool) - len(todo)} done). 0/1/2 label, s skip, q quit.")

    for done, pair in enumerate(todo, start=1):
        query = queries[pair["query"]]
        show(profiles[query["profile"]], query, postings[pair["posting"]])
        key = read_key(f"[{done}/{len(todo)}] 0/1/2/s/q:")
        while key not in "012sq":
            key = read_key("0, 1, 2, s or q:")
        if key == "q":
            break
        if key == "s":
            continue
        qrels.setdefault(pair["query"], {})[pair["posting"]] = int(key)
        out.write_text(json.dumps(qrels, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"saved {sum(len(v) for v in qrels.values())} judgments to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
