"""Label gold features for a stratified sample of postings (spec §7.1).

    uv run python -m evals.extraction.label --snapshot evals/data/corpus-<date>.jsonl.gz --n 40

Postings are drawn round-robin across the three ATSs (seeded, so the sample is fixed). For each
posting, every field shows the pipeline's value: press Enter to accept it or type the right one.
At the start of a posting, s skips it and q quits. Each finished posting is saved at once to
evals/extraction/labels.jsonl.
"""

import argparse
import json
import random
import textwrap
from pathlib import Path

from evals.keys import read_key
from evals.snapshot import read_snapshot

HERE = Path(__file__).parent
FIELDS = ("role_family", "seniority", "country", "city", "remote_scope", "min_years", "relevant")
CHOICES = {
    "role_family": "software ml data other",
    "seniority": "intern new_grad entry mid senior unknown",
    "remote_scope": "onsite hybrid remote_country remote_global unknown",
    "relevant": "true false",
}


def stratified(items: list[dict], n: int, seed: int = 0) -> list[dict]:
    by_ats: dict[str, list[dict]] = {}
    for item in sorted(items, key=lambda i: i["id"]):
        by_ats.setdefault(item["board"]["ats"], []).append(item)
    rng = random.Random(seed)
    for group in by_ats.values():
        rng.shuffle(group)
    sample, groups = [], [by_ats[ats] for ats in sorted(by_ats)]
    while len(sample) < n and any(groups):
        for group in groups:
            if group and len(sample) < n:
                sample.append(group.pop())
    return sample


def parse(field: str, text: str):
    if text in ("", "-", "none", "null"):
        return None
    if field == "min_years":
        return float(text)
    if field == "relevant":
        return text.lower() in ("true", "t", "yes", "y", "1")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--labels", default=str(HERE / "labels.jsonl"))
    args = parser.parse_args(argv)

    labels_path = Path(args.labels)
    done = set()
    if labels_path.exists():
        done = {json.loads(line)["posting_id"] for line in labels_path.read_text().splitlines()}
    _, items = read_snapshot(Path(args.snapshot))
    todo = [item for item in stratified(items, args.n) if item["id"] not in done]
    print(f"{len(todo)} postings to label ({len(done)} done).")

    for number, item in enumerate(todo, start=1):
        features = item["features"]
        print("\n" + "=" * 78)
        source = f"{item['company']['name']} ({item['board']['ats']})"
        print(f"[{number}/{len(todo)}] {item['title']} — {source}")
        print(f"location: {item['location_raw']}")
        print(textwrap.fill(item["description"][:2500], width=78))
        key = read_key("Enter to label, s skip, q quit:")
        if key == "q":
            break
        if key == "s":
            continue
        gold = {"posting_id": item["id"]}
        for field in FIELDS:
            hint = f" ({CHOICES[field]})" if field in CHOICES else ""
            typed = input(f"  {field}{hint} [{features.get(field)}]: ").strip()
            gold[field] = parse(field, typed) if typed else features.get(field)
        predicted = ", ".join(s["name"] for s in item["skills"])
        typed = input(f"  skills, comma-separated [{predicted}]: ").strip()
        gold["skills"] = sorted(
            {s.strip() for s in typed.split(",") if s.strip()}
            if typed
            else {s["name"] for s in item["skills"]}
        )
        with labels_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(gold) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
