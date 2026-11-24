"""Score feature extraction against gold labels; write docs/evaluation/extraction-<date>.md.

    uv run python -m evals.extraction.run --snapshot evals/data/corpus-<date>.jsonl.gz \
        --labels evals/extraction/labels.jsonl

Two systems are scored on the same postings: "pipeline" (what the snapshot holds: rules plus
the LLM where it ran) and "rules" (Stage A alone, recomputed now). Field accuracy and skill
micro P/R/F1 come with 95% bootstrap intervals over postings.
"""

import argparse
import json
import shlex
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.core.config import REPO_ROOT, get_settings
from app.extract.merge import merge_features
from app.extract.rules import extract_rules
from app.extract.taxonomy import SkillMatcher
from evals.extraction.label import FIELDS
from evals.snapshot import read_snapshot, sha256
from evals.stats import bootstrap_ci, bootstrap_metric, prf_from_counts, skill_counts


def same(field: str, gold, pred) -> bool:
    if field == "min_years":
        if gold is None or pred is None:
            return gold is None and pred is None
        return abs(float(gold) - float(pred)) < 0.01
    return gold == pred


def rules_prediction(item: dict, matcher: SkillMatcher) -> tuple[dict, set[str]]:
    rules = extract_rules(
        item["title"],
        item["location_raw"],
        item["description"],
        matcher,
        is_remote_flag=(item.get("source_metadata") or {}).get("isRemote"),
    )
    final = merge_features(rules, None, matcher)
    values = {field: getattr(final, field) for field in FIELDS}
    if isinstance(values["min_years"], Decimal):
        values["min_years"] = float(values["min_years"])
    return values, final.required | final.nice


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    matcher = SkillMatcher.from_yaml(settings.repo_path(settings.taxonomy_path))
    _, items = read_snapshot(Path(args.snapshot))
    postings = {item["id"]: item for item in items}
    labels = [json.loads(line) for line in Path(args.labels).read_text().splitlines() if line]
    labels = [label for label in labels if label["posting_id"] in postings]
    if not labels:
        raise SystemExit("no labels for postings in this snapshot: run evals.extraction.label")

    systems: dict[str, list[tuple[dict, set[str]]]] = {"pipeline": [], "rules": []}
    for label in labels:
        item = postings[label["posting_id"]]
        stored = {field: item["features"].get(field) for field in FIELDS}
        systems["pipeline"].append((stored, {s["name"] for s in item["skills"]}))
        systems["rules"].append(rules_prediction(item, matcher))

    header = "| Field | " + " | ".join(systems) + " |"
    rows = [header, "|---|" + "---|" * len(systems)]
    for field in FIELDS:
        cells = []
        for predictions in systems.values():
            hits = [
                float(same(field, label[field], pred[field]))
                for label, (pred, _) in zip(labels, predictions, strict=True)
            ]
            low, high = bootstrap_ci(hits)
            cells.append(f"{sum(hits) / len(hits):.2f} [{low:.2f}, {high:.2f}]")
        rows.append(f"| {field} | " + " | ".join(cells) + " |")
    for index, name in enumerate(("precision", "recall", "F1")):
        cells = []
        for predictions in systems.values():
            counts = [
                skill_counts(set(label["skills"]), skills)
                for label, (_, skills) in zip(labels, predictions, strict=True)
            ]
            value = prf_from_counts(counts)[index]
            low, high = bootstrap_metric(counts, lambda c, i=index: prf_from_counts(c)[i])
            cells.append(f"{value:.2f} [{low:.2f}, {high:.2f}]")
        rows.append(f"| skills {name} (micro) | " + " | ".join(cells) + " |")

    stages = Counter(postings[label["posting_id"]]["features"]["stage"] for label in labels)
    ats = Counter(postings[label["posting_id"]]["board"]["ats"] for label in labels)
    command = "uv run python -m evals.extraction.run " + shlex.join(
        sys.argv[1:] if argv is None else argv
    )
    lines = [
        f"# Extraction evaluation, {date.today().isoformat()}",
        "",
        f"- Snapshot: `{Path(args.snapshot).name}` (sha256 `{sha256(Path(args.snapshot))[:16]}…`)",
        f"- {len(labels)} labelled postings; by ATS: "
        + ", ".join(f"{k} {v}" for k, v in sorted(ats.items())),
        "- Pipeline stage of those postings: "
        + ", ".join(f"{k} {v}" for k, v in sorted(stages.items())),
        "- Intervals: 95% percentile bootstrap over postings (2,000 resamples, seed 0).",
        "",
        *rows,
        "",
        "Reproduce:",
        "",
        "```bash",
        command,
        "```",
        "",
    ]
    out = Path(args.out or REPO_ROOT / "docs" / "evaluation" / f"extraction-{date.today()}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
