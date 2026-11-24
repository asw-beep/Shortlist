# Evaluation

Offline evaluation on a frozen snapshot (spec §7). Run everything from `backend/`.

Snapshots hold companies' job-description text, so they stay out of git. Each report records its
snapshot's SHA-256; keep the file to reproduce a report.

## 1. Freeze a snapshot

```bash
uv run python -c "from pathlib import Path; from app.core.config import get_settings; \
from app.db.engine import create_db_engine; from app.db.session import create_session_factory; \
from evals.snapshot import export_snapshot; \
db = create_session_factory(create_db_engine(get_settings()))(); \
print(export_snapshot(db, Path('evals/data/corpus-$(date +%F).jsonl.gz')))"
```

Point `DATABASE_URL` at the database you want to freeze (production, after the pipeline ran with
LLM keys, gives the most useful extraction numbers).

## 2. Extraction

```bash
uv run python -m evals.extraction.label --snapshot evals/data/corpus-<date>.jsonl.gz --n 40
uv run python -m evals.extraction.run --snapshot evals/data/corpus-<date>.jsonl.gz \
    --labels evals/extraction/labels.jsonl
```

## 3. Ranking

The ranking tools use a separate database whose name must end in `_eval`
(`EVAL_DATABASE_URL`, default `…/shortlist_eval`); they migrate it, load the snapshot and create
one user per profile in `ranking/profiles.yaml`.

```bash
createdb shortlist_eval    # once; then: psql shortlist_eval -c "CREATE EXTENSION vector"
uv run python -m evals.ranking.pool  --snapshot evals/data/corpus-<date>.jsonl.gz
uv run python -m evals.ranking.label --snapshot evals/data/corpus-<date>.jsonl.gz
uv run python -m evals.ranking.label --snapshot … --labeler <classmate-id>   # 10% overlap
uv run python -m evals.ranking.run   --snapshot … --qrels evals/ranking/qrels.json \
    --second-qrels evals/ranking/qrels.<classmate-id>.json
uv run python -m evals.ranking.tune  --snapshot … --qrels evals/ranking/qrels.json
```

Labelling keys: `0` not for this student, `1` maybe, `2` would apply, `s` skip, `q` quit.
Progress is saved after every key.
