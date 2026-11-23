# Shortlist Phase 0 + Phase 1 (Feed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Feed half of Shortlist. That's a live, $0 job index built from public ATS boards, personalised and explained ranking in one SQL statement, one-click feedback, a weekly email digest, and measured extraction and ranking quality.

**Architecture:**
- A FastAPI app (reusing TicketLoop's core and identity) runs on Render.
- Batch jobs (ingest → extract → embed → digest) are CLI commands run by GitHub Actions.
- Everything lives in one Neon Postgres with pgvector.
- A static React app on Cloudflare Pages talks to the API through a same-origin Pages Function proxy.
- The LLM runs only at write time (extraction). Search makes 0 LLM calls.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy 2, psycopg 3, Alembic, pgvector (+ `pgvector` Python package), fastembed (`BAAI/bge-small-en-v1.5`), httpx, pypdf, PyYAML, ranx, pytest, ruff. Frontend: Vite, React, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-23-shortlist-design.md`

## Global Constraints

- Running cost $0: only Neon Free, Render Free, GitHub Actions (public repo), Cloudflare Pages, Gemini free tier, Groq free tier, Brevo free.
- Python 3.12 + uv; Node 24 LTS; local Postgres image `pgvector/pgvector:pg17`; production Neon in `aws-ap-southeast-1`.
- Embeddings: `BAAI/bge-small-en-v1.5` via fastembed, 384 dimensions, the same model in the Actions worker and the API. Query prefix: `Represent this sentence for searching relevant passages: `.
- Extraction models, in order: Gemini Flash-Lite, then Groq `openai/gpt-oss-20b`, then rules only. Only public posting text goes to Gemini. User text goes only to Groq.
- No raw résumé is ever stored.
- No code copied from third-party repos. Reuse only Aswin's own TicketLoop, Engram and Delta.
- The API uses Neon's pooled URL with psycopg `prepare_threshold=None`. Migrations use the direct URL.
- Email goes through the Brevo HTTP API only (Render Free blocks SMTP ports 25/465/587).
- No cross-encoder and no LLM call in the search request path (Render Free: 512 MB, 0.1 CPU).
- Ranking: RRF k = 60; 100 candidates per retriever; weights skill 0.30, rrf 0.25, experience 0.15, location 0.10, recency 0.10, personal 0.10; recency τ = 14 days; personal ramp = 10 feedback events.
- Lifecycle: close a posting after 2 consecutive misses; purge description 30 days after closing; disable a board after 5 consecutive failures.
- Extraction batch size 8; ingest concurrency 8; ingest every 6 h (`0 */6 * * *`); digest Monday 09:00 IST (`30 3 * * 1` UTC).
- Relevance gate: India-located or remote-eligible for India, AND role family ∈ {software, ml, data}, AND not senior (title rules or `min_years > 3`).
- Signup needs an invite code. JWT access 15 min, refresh 7 days (TicketLoop identity).
- Ruff, line length 100, rules `E W F I B UP SIM`. Integration tests run against real Postgres and fail rather than skip when `REQUIRE_POSTGRES=1`.
- Small commits, one per task step "Commit". Commit messages end with the session's `Co-Authored-By` / `Claude-Session` trailer unless Aswin says otherwise.
- All commands below run from `backend/` unless they say `(repo root)`. Integration tests need `docker compose up -d db` (repo root).

## Review Focus

1. **A board times out mid-run.** Its postings must not count a miss, so they stay open (Task 5: `test_failed_board_does_not_count_misses`).
2. **The extraction LLM's daily quota runs out halfway through a run.** The remaining postings get rules-only features marked `llm_pending` and are retried next run, and no provider is called again that run (Task 8: `test_quota_exhaustion_stops_llm_and_marks_pending`).
3. **A user with an empty profile, or a query of only punctuation, hits the feed.** The first gets a 409 problem telling them to complete their profile. The second gets vector-only results, never a 500 (Task 12: `test_feed_without_profile_is_409`, `test_punctuation_query_falls_back_to_dense`).
4. **The same role is posted twice by one company** (two boards or two locations of one city). The feed shows it once (Task 12: `test_feed_collapses_duplicate_roles`).
5. **A digest link is clicked while Render is asleep, then clicked again.** The Pages proxy waits through the cold start for GET requests, and the second click doesn't create a second save (Task 15: `test_proxy_retries_get_through_cold_start`; Task 13: `test_signed_link_is_idempotent`).

---

## File structure

```
Shortlist/
├─ docker-compose.yml                  # db: pgvector/pgvector:pg17
├─ render.yaml
├─ .github/workflows/{ci,checks,pipeline,digest}.yml
├─ sources/boards.yaml                 # Task 7
├─ taxonomy/{onet_hot_tech.txt,aliases.yaml,skills.yaml}   # Task 6
├─ config/ranking.yaml                 # Task 12
├─ docs/{phase-0-early-checks.md, evaluation/*.md}
├─ evals/{snapshot.py, extraction/*, ranking/*}            # Task 17
├─ frontend/                           # Task 15
│  └─ functions/api/[[path]].ts        # Pages Function proxy
└─ backend/
   ├─ pyproject.toml, uv.lock, alembic.ini, Dockerfile
   ├─ migrations/
   ├─ app/
   │  ├─ main.py, cli.py
   │  ├─ core/       config, logging, exceptions, middleware, dependencies, security (TicketLoop)
   │  ├─ db/         base, engine, session (TicketLoop infrastructure/database)
   │  ├─ api/        router, health, status
   │  ├─ notify/     email.py (EmailSender, InMemoryEmailSender, BrevoEmailSender)
   │  ├─ identity/   models, schemas, service, router, dependencies, errors, invites (TicketLoop + invites)
   │  ├─ catalog/    models.py (Company, Board, Posting, PostingFeatures, Skill, PostingSkill, IngestRun, BoardRun)
   │  ├─ ingest/     ats.py, boards.py, service.py
   │  ├─ extract/    taxonomy.py, rules.py, llm.py, service.py
   │  ├─ llm/        base.py, openai_compat.py, chain.py
   │  ├─ tracing/    models.py, spans.py
   │  ├─ embed/      model.py, service.py
   │  ├─ profiles/   models, schemas, service, router, resume.py
   │  ├─ search/     config.py, sql.py, service.py, router.py
   │  ├─ feedback/   models, links.py, service, router
   │  └─ digest/     models, render.py, service.py
   ├─ scripts/checks/{embed_memory,fetch_samples,extract_check,toolcall_check}.py
   ├─ scripts/{build_taxonomy,discover_boards,smoke}.py
   └─ tests/
      ├─ conftest.py, fakes.py           # FakeEmbedder, FakeLLM
      ├─ fixtures/ats/{greenhouse,lever,ashby}/*.json
      ├─ unit/…  integration/…  (conftest, database, factories from TicketLoop pattern)
```

---

### Task 1: Repository skeleton on TicketLoop's core

**Files:**
- Create: `docker-compose.yml`, `.gitignore`, `.gitattributes` (`* text=auto eol=lf`), `README.md` (stub), `.github/workflows/ci.yml` (repo root)
- Create: `backend/pyproject.toml`, `backend/alembic.ini`, `backend/migrations/{env.py,script.py.mako}`, `backend/migrations/versions/0001_extensions.py`
- Create, copied and adapted from TicketLoop:
  - `backend/app/core/{config,logging,exceptions,middleware,dependencies,security}.py`
  - `backend/app/db/{base,engine,session}.py`
  - `backend/app/api/{router,health}.py`
  - `backend/app/main.py`
- Test: `backend/tests/conftest.py`, `backend/tests/integration/{conftest,database}.py`, `backend/tests/unit/test_health.py`, `backend/tests/integration/test_database.py`

**Interfaces:**
- Produces:
  - `create_app(settings: Settings | None = None) -> FastAPI`
  - `Settings` (pydantic-settings) with the fields below
  - `DbSession` dependency
  - `create_db_engine(settings) -> Engine`, built from `engine_connect_args(settings: Settings) -> dict[str, Any]` (TicketLoop's connect_timeout and UTC options, plus `prepare_threshold=None` when pooled)
  - `create_session_factory(bind) -> sessionmaker[Session]`
  - `Base` with TicketLoop's naming convention and `UUIDPrimaryKey`, `Timestamps`, `CreatedAt` mixins
  - Test fixtures `settings`, `app`, `client`, `test_engine`, `db_connection`, `db` (a Session joined to the rolled-back connection) and `api` (a TestClient on the test DB)
- `Settings` fields:
  - From TicketLoop: `environment`, `api_prefix="/api/v1"`, `database_url`, `log_level`, `log_json`, `jwt_secret_key`, `jwt_issuer="shortlist"`, `access_token_minutes=15`, `refresh_token_days=7`, `password_reset_minutes=30`, `frontend_url="http://localhost:5173"`
  - New:
    - `database_pooled: bool = False` (when True the engine passes `prepare_threshold=None`)
    - `direct_database_url: str | None = None` (Alembic uses it when set)
    - `groq_api_key`, `gemini_api_key`, `brevo_api_key`: `SecretStr | None = None`
    - `email_from_address="shortlist@example.com"`, `email_from_name="Shortlist"`
    - `feedback_link_secret: SecretStr` (local default; staging/production refuse it, as TicketLoop does with `jwt_secret_key`)
    - `embed_model="BAAI/bge-small-en-v1.5"`, `embed_cache_dir: str | None = None`
    - Paths, resolved from the repo root: `ranking_config_path="config/ranking.yaml"`, `taxonomy_path="taxonomy/skills.yaml"`, `boards_path="sources/boards.yaml"`
    - `extract_models: list[str] = ["gemini:gemini-3.5-flash-lite", "groq:openai/gpt-oss-20b"]`
    - `resume_model: str = "groq:openai/gpt-oss-120b"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_health.py
def test_health_ok_without_database(client, app):
    app.dependency_overrides[database_is_reachable] = lambda: True
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "checks": {"database": "ok"}}

# tests/integration/test_database.py
def test_vector_extension_installed(db):
    assert db.execute(text("select extversion from pg_extension where extname='vector'")).scalar()

def test_probe_1_commit_inside_test(db):
    db.execute(text("create table t_probe(x int)")); db.commit()
    assert db.execute(text("select to_regclass('t_probe')")).scalar() is not None

def test_probe_2_previous_commit_was_rolled_back(db):    # pytest runs file order: proves per-test rollback
    assert db.execute(text("select to_regclass('t_probe')")).scalar() is None

def test_pooled_settings_disable_prepared_statements():
    pooled = Settings(_env_file=None, environment="test", database_pooled=True)
    direct = Settings(_env_file=None, environment="test")
    assert engine_connect_args(pooled)["prepare_threshold"] is None
    assert "prepare_threshold" not in engine_connect_args(direct)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -v`. Expected: collection errors (modules missing).

- [ ] **Step 3: Copy and adapt TicketLoop's core, DB, health, test fixtures and CI.**
  - Keep the docstrings' reasoning where it still applies.
  - Drop storage, MinIO, Mailpit and all ticket and listing modules.
  - `0001_extensions` runs `CREATE EXTENSION IF NOT EXISTS vector` (and `pgcrypto` only if `gen_random_uuid` is missing; PG 17 has it built in).
  - `docker-compose.yml`: service `db`, image `pgvector/pgvector:pg17`, user/password/db `shortlist`, port 5432, healthcheck as TicketLoop.
  - CI: one `backend` job with a `pgvector/pgvector:pg17` service, `REQUIRE_POSTGRES=1`, then `uv sync --locked`, `ruff check`, `ruff format --check`, `alembic upgrade head`, `alembic check`, `pytest`. The `frontend` job is added in Task 15.

- [ ] **Step 4: Run to verify they pass**

Run: `docker compose up -d db` (repo root), then `uv run pytest -v`. Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "chore: skeleton on TicketLoop core, pgvector database, CI"
```

---

### Task 2: Phase 0 early checks (blocking decisions)

**Files:**
- Create: `backend/scripts/checks/embed_memory.py`, `fetch_samples.py`, `extract_check.py`, `toolcall_check.py`
- Create: `.github/workflows/checks.yml` (repo root, `workflow_dispatch`), `docs/phase-0-early-checks.md`
- Create: `backend/tests/fixtures/ats/{greenhouse,lever,ashby}/<slug>.json` (output of `fetch_samples.py`)

**Interfaces:**
- Produces:
  - Saved ATS fixtures used by Tasks 4–5
  - Confirmed model IDs written into `Settings.extract_models` / `resume_model` defaults
  - A recorded go/no-go on fastembed in 512 MB

- [ ] **Step 1: Write `embed_memory.py`.** It loads `TextEmbedding(settings.embed_model)`, embeds 1 warm-up then 50 short queries, and prints JSON `{peak_rss_mb, p50_ms, p95_ms}` (RSS from `resource.getrusage`).

- [ ] **Step 2: Run it under Render's limits** in `checks.yml`: `docker build` the backend image, then `docker run --memory=512m --cpus=0.1 <image> python -m scripts.checks.embed_memory`.
  - **Pass:** `peak_rss_mb ≤ 420` and `p50_ms ≤ 500`.
  - **Fail:** change both sides to Gemini embeddings before Task 9 (spec §6.3 fallback) and note it in the doc.

- [ ] **Step 3: Write and run `fetch_samples.py`.**
  - It takes `--greenhouse a,b,… --lever … --ashby …` (10 slugs each, chosen while starting Task 7's candidate list).
  - It saves each board's response trimmed to its first 5 postings, as UTF-8 JSON under `tests/fixtures/ats/<ats>/<slug>.json`.
  - Run: `uv run python -m scripts.checks.fetch_samples --greenhouse … --lever … --ashby …`. Expected: 30 files, each with 1–5 postings.

- [ ] **Step 4: Write and run `extract_check.py`.** It sends one batch of 8 fixture postings to each configured extraction model through the OpenAI-compatible endpoints, with `response_format={"type":"json_schema","json_schema":{..., "strict": true}}`. It prints parse success, latency and token usage per model.
  - Gemini base URL: `https://generativelanguage.googleapis.com/v1beta/openai/`. Groq base URL: `https://api.groq.com/openai/v1`.
  - Expected: valid JSON for 8/8 items on at least one model. Record the exact working model IDs.

- [ ] **Step 5: Write and run `toolcall_check.py`.** One `tools=[search_jobs]` round trip on `openai/gpt-oss-120b`, asserting that a `tool_calls[0].function.name == "search_jobs"` comes back with JSON arguments. Record the result for the Phase 2 plan.

- [ ] **Step 6: Write `docs/phase-0-early-checks.md`.**
  - Contents: numbers, model IDs, the free-tier limits as read in each console today, and the decision for each check.
  - Update the `Settings` defaults to the confirmed model IDs.
  - Run: `uv run pytest -v`. Expected: still green.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore: phase 0 early checks, ATS fixtures, confirmed model IDs"
```

---

### Task 3: Catalog schema

**Files:**
- Create: `backend/app/catalog/models.py`, `backend/migrations/versions/0002_catalog.py`
- Test: `backend/tests/integration/test_catalog_schema.py`, `backend/tests/integration/factories.py`

**Interfaces:**
- Produces these tables and models (all ids uuid, server-generated; all timestamps timestamptz):
  - `Company`: name, unique `slug`.
  - `Board`:
    - Columns: company_id, `ats` CHECK in ('greenhouse','lever','ashby'), `slug`, `enabled` bool default true, `consecutive_failures` int default 0.
    - UNIQUE(ats, slug).
  - `Posting`:
    - Columns:
      - board_id, external_id, url, title, location_raw
      - `description` (nullable: purged), `source_metadata` jsonb
      - `content_hash`, `processed_hash` (nullable), `embedded_hash` (nullable)
      - `status` CHECK in ('open','closed'), `missed_runs` int default 0
      - `first_seen_at`, `last_seen_at`, `closed_at`
      - `embedding vector(384)` (nullable), `embedded_at` (nullable)
      - `search_tsv tsvector` GENERATED ALWAYS AS (`setweight(to_tsvector('english', coalesce(title,'')),'A') || setweight(to_tsvector('english', coalesce(summary_text,'')),'B')`) STORED
      - `summary_text text` (written by extraction: title, company name and summary)
    - Constraints:
      - UNIQUE(board_id, external_id)
      - CHECK `(status='closed') = (closed_at IS NOT NULL)`
    - Indexes: GIN on search_tsv; btree on (status).
  - `PostingFeatures` (PK posting_id):
    - Columns:
      - `extractor_version` int, `stage` CHECK in ('rules','llm'), `llm_pending` bool default false
      - `role_family` CHECK in ('software','ml','data','other')
      - `seniority` CHECK in ('intern','new_grad','entry','mid','senior','unknown')
      - `is_internship`, `is_new_grad` bool; `min_years` numeric(3,1) nullable
      - `country` (ISO-2, nullable), `city` nullable
      - `remote_scope` CHECK in ('onsite','hybrid','remote_country','remote_global','unknown')
      - `relevant` bool; `summary` text nullable; `stipend_or_salary` text nullable; `education` text nullable
    - Index (relevant, role_family, seniority).
  - `Skill`: unique `name`, `aliases text[]`.
  - `PostingSkill`: (posting_id, skill_id, `kind` CHECK in ('required','nice')), PK (posting_id, skill_id).
  - `UnknownSkill`: unique `name`, `seen_count`, `first_seen_at`. This is the review list.
  - `IngestRun`: started_at, finished_at, boards_ok, boards_failed, postings_new, postings_changed, postings_closed.
  - `BoardRun`: ingest_run_id, board_id, status CHECK in ('ok','failed'), `failure_reason` nullable, postings_seen, latency_ms.
- Produces factories: `make_company(db, **kw)`, `make_board(db, company=None, **kw)`, `make_posting(db, board=None, **kw)`, `make_features(db, posting, **kw)` returning ORM objects.

- [ ] **Step 1: Write the failing tests**

```python
def test_duplicate_posting_per_board_rejected(db): ...          # IntegrityError on same (board_id, external_id)
def test_closed_requires_closed_at(db): ...                     # status='closed', closed_at=None -> IntegrityError
def test_search_tsv_generated_from_title_and_summary(db):
    p = make_posting(db, title="Backend Engineer Intern", summary_text="FastAPI PostgreSQL")
    assert db.execute(text("select search_tsv @@ websearch_to_tsquery('english','postgresql') from postings where id=:i"), {"i": p.id}).scalar()
def test_embedding_accepts_384_dims_only(db): ...               # 384 ok, 383 -> DataError
def test_feature_enums_enforced(db): ...                        # role_family='sales' -> IntegrityError
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/integration/test_catalog_schema.py -v`. Expected: FAIL (no tables).

- [ ] **Step 3: Write the models and the `0002_catalog` migration.** Autogenerate, then hand-edit the generated column and the GIN index. Use `pgvector.sqlalchemy.Vector(384)`.

- [ ] **Step 4: Run to verify they pass.** Run: `uv run pytest tests/integration -v && uv run alembic check`. Expected: PASS, "No new upgrade operations detected".

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: catalog schema for companies, boards, postings, features, skills, runs"
```

---

### Task 4: ATS clients and normaliser

**Files:**
- Create: `backend/app/ingest/ats.py`
- Test: `backend/tests/unit/test_ats.py`

**Interfaces:**
- Produces:
  - `Ats = Literal["greenhouse","lever","ashby"]`
  - `RawPosting(frozen dataclass)`: `external_id: str, url: str, title: str, location_raw: str, description_text: str, source_metadata: dict[str, Any]`
  - `parse_greenhouse(payload: dict) -> list[RawPosting]`, `parse_lever(payload: list) -> list[RawPosting]`, `parse_ashby(payload: dict) -> list[RawPosting]`
  - `html_to_text(html: str) -> str`: stdlib `html.parser`; block tags become newlines; entities unescaped; whitespace collapsed; capped at 100,000 chars
  - `content_hash(p: RawPosting) -> str`: sha256 hex over `title\nlocation_raw\ndescription_text`
  - `fetch_board(client: httpx.Client, ats: Ats, slug: str, timeout: float = 20.0) -> list[RawPosting]`
  - `BoardFetchError(Exception)` with `.reason: Literal["timeout","not_found","http_error","bad_payload"]`
- Endpoints, exactly:
  - `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
  - `https://api.lever.co/v0/postings/{slug}?mode=json`
  - `https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true`

- [ ] **Step 1: Write the failing tests** (fixtures from Task 2; HTTP through `httpx.MockTransport`)

```python
@pytest.mark.parametrize("ats", ["greenhouse", "lever", "ashby"])
def test_fixture_boards_parse(ats):                # every fixture → ≥1 RawPosting, non-empty title/url/external_id
def test_greenhouse_html_content_is_unescaped_text():   # '&lt;p&gt;Python&lt;/p&gt;' → 'Python'
def test_html_to_text_keeps_paragraph_breaks_and_drops_scripts():
def test_html_to_text_caps_length():                # 300k chars in → len(out) == 100_000
def test_content_hash_changes_with_description_only():
def test_fetch_board_404_is_not_found():            # MockTransport 404 → BoardFetchError.reason == "not_found"
def test_fetch_board_timeout_is_timeout():          # transport raises httpx.ReadTimeout → reason "timeout"
def test_fetch_board_bad_json_is_bad_payload():
def test_posting_with_missing_location_gets_empty_string():
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/unit/test_ats.py -v`. Expected: FAIL (import error).

- [ ] **Step 3: Implement the parsers using each ATS's own field names.**
  - Greenhouse: `jobs[].id/absolute_url/title/location.name/content` (content is HTML-escaped HTML).
  - Lever: `[].id/hostedUrl/text/categories.location/descriptionPlain + lists`.
  - Ashby: `jobs[].id/jobUrl/title/location/descriptionPlain or descriptionHtml/isRemote`.
  - Keep the rest of each item (minus description fields) in `source_metadata`.

- [ ] **Step 4: Run to verify they pass.** Run: `uv run pytest tests/unit/test_ats.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Greenhouse, Lever and Ashby clients with a shared posting shape"
```

---

### Task 5: Ingest run, lifecycle and board health

**Files:**
- Create: `backend/app/ingest/boards.py`, `backend/app/ingest/service.py`, `backend/app/cli.py`
- Test: `backend/tests/integration/test_ingest.py`, `backend/tests/unit/test_boards_file.py`

**Interfaces:**
- Consumes: `fetch_board`, `RawPosting`, `content_hash`, `BoardFetchError` (Task 4); catalog models (Task 3).
- Produces:
  - `BoardSpec(frozen dataclass)`: `company: str, ats: Ats, slug: str`
  - `load_boards_file(path: Path) -> list[BoardSpec]` (rejects duplicates and unknown ats with `ValueError`)
  - `sync_boards(db: Session, specs: list[BoardSpec]) -> None` (creates companies and boards; never deletes; specs removed from the file become `enabled=false`)
  - `IngestSummary(dataclass)`: `boards_ok, boards_failed, new, changed, closed, reopened: int`
  - `run_ingest(db: Session, fetch: Callable[[Ats, str], list[RawPosting]], *, now: datetime, workers: int = 8) -> IngestSummary`. Fetching runs in a `ThreadPoolExecutor(workers)`; all DB writes stay in the calling thread.
  - `purge_closed(db: Session, *, now: datetime, after_days: int = 30) -> int`
  - CLI: `python -m app.cli ingest` and `python -m app.cli check-boards`. The second prints `ats slug company postings|ERROR reason` per board and exits 1 if any fail.

- [ ] **Step 1: Write the failing tests** (fake `fetch` callable)

```python
def test_new_posting_inserted_open_with_first_seen(db):
def test_unchanged_posting_keeps_hashes_and_last_seen_updates(db):
def test_changed_description_updates_content_hash_only(db):     # processed_hash stays old → needs processing
def test_missing_once_stays_open_missing_twice_closes(db):      # missed_runs 1 → open; 2 → closed, closed_at == now
def test_reappearing_posting_reopens(db):                       # status open, missed_runs 0, closed_at None
def test_failed_board_does_not_count_misses(db):                # Review Focus 1: fetch raises BoardFetchError → postings unchanged, missed_runs 0
def test_five_consecutive_failures_disable_board(db):           # enabled False after 5th; a success resets the counter to 0
def test_board_runs_record_reason_and_latency(db):
def test_purge_clears_description_after_30_days(db):            # closed 31 days ago → description None; 29 days → kept
def test_boards_file_rejects_duplicates(tmp_path):
def test_sync_boards_disables_removed_specs(db):
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/integration/test_ingest.py tests/unit/test_boards_file.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `run_ingest`.**
  - One `IngestRun` row per call and one `BoardRun` per enabled board.
  - Upsert with `INSERT … ON CONFLICT (board_id, external_id) DO UPDATE` setting title, location, description, metadata, `content_hash`, `last_seen_at=now`, `missed_runs=0`. If the row was closed, set `status='open', closed_at=NULL` and count it as reopened.
  - After a board succeeds, run `UPDATE postings SET missed_runs = missed_runs + 1 WHERE board_id = :b AND status='open' AND last_seen_at < :now`, then close rows with `missed_runs >= 2`.

- [ ] **Step 4: Run to verify they pass.** Run: same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: ingest with change detection, two-miss closing, board health, purge"
```

---

### Task 6: Skill taxonomy and rules extraction (Stage A)

**Files:**
- Create: `backend/scripts/build_taxonomy.py`, `taxonomy/aliases.yaml`, `taxonomy/skills.yaml` (generated, committed), `taxonomy/README.md` (O*NET attribution)
- Create: `backend/app/extract/taxonomy.py`, `backend/app/extract/rules.py`
- Test: `backend/tests/unit/test_taxonomy.py`, `backend/tests/unit/test_rules.py`

**Interfaces:**
- Produces:
  - `SkillMatcher.from_yaml(path: Path) -> SkillMatcher`
    - `.match(text: str) -> set[str]`: canonical names. Case-insensitive, longest match first, token boundaries that treat `+ # .` as word characters, so "C++", "C#", ".NET" and "Node.js" match and "Java" doesn't match inside "JavaScript".
    - `.canonical(name: str) -> str | None`
  - `Location(frozen dataclass)`: `country: str | None, city: str | None, remote_scope: Literal["onsite","hybrid","remote_country","remote_global","unknown"]`
  - `parse_location(raw: str, *, is_remote_flag: bool | None = None) -> Location`. Cities are canonical, with the aliases Bangalore→Bengaluru, Gurgaon→Gurugram, Bombay→Mumbai, New Delhi→Delhi.
  - `RuleFeatures(frozen dataclass)`: `role_family, seniority, is_internship, is_new_grad, min_years: float | None, location: Location, skills: set[str], confident: bool`
  - `extract_rules(title: str, location_raw: str, description: str, matcher: SkillMatcher, *, is_remote_flag: bool | None = None) -> RuleFeatures`
  - `is_relevant(*, role_family: str, seniority: str, min_years: float | None, country: str | None, remote_scope: str) -> bool`: exactly the Global Constraints relevance gate (keyword-only, so Task 8's `FinalFeatures` can use it too)
  - `build_taxonomy.py` downloads O*NET "Technology Skills". It keeps `Hot Technology == Y` rows whose commodity title is software or IT, merges `aliases.yaml`, and writes `skills.yaml` as `[{name, aliases}]`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw,expected", [
    ("Bengaluru, Karnataka, India", Location("IN", "Bengaluru", "onsite")),
    ("Bangalore", Location("IN", "Bengaluru", "onsite")),
    ("Gurgaon, Haryana", Location("IN", "Gurugram", "onsite")),
    ("Remote - India", Location("IN", None, "remote_country")),
    ("Remote (India)", Location("IN", None, "remote_country")),
    ("Remote", Location(None, None, "remote_global")),
    ("Hyderabad, Telangana (Hybrid)", Location("IN", "Hyderabad", "hybrid")),
    ("San Francisco, CA", Location("US", None, "onsite")),
    ("", Location(None, None, "unknown")),
])
def test_parse_location(raw, expected): assert parse_location(raw) == expected

@pytest.mark.parametrize("title,family,seniority,intern,newgrad", [
    ("Software Engineer Intern", "software", "intern", True, False),
    ("Machine Learning Engineer, New Grad", "ml", "new_grad", False, True),
    ("Senior Data Engineer", "data", "senior", False, False),
    ("SDE I - Backend", "software", "entry", False, False),
    ("Account Executive", "other", "unknown", False, False),
])
def test_title_rules(title, family, seniority, intern, newgrad): ...

def test_min_years(): assert extract_rules("SWE", "", "3+ years of experience", M).min_years == 3; "2-4 years" → 2
def test_skills_aliases(): M.match("Python, k8s and postgres") == {"Python", "Kubernetes", "PostgreSQL"}
def test_skills_symbols(): M.match("C++/C# and .NET") == {"C++", "C#", ".NET"}
def test_java_not_in_javascript(): "Java" not in M.match("JavaScript developer")
def test_relevance_gate(): intern in Bengaluru → True; Senior in Bengaluru → False; intern in SF onsite → False; remote_global intern → True; min_years 4 → False
def test_confident_false_when_title_family_other_but_description_mentions_engineering(): ...
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/unit/test_taxonomy.py tests/unit/test_rules.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Title rules are ordered regex lists in `rules.py`: senior/staff/principal/lead/manager means `senior`; intern means `intern`; new grad/graduate/campus/fresher means `new_grad`; SDE I / Engineer I / Associate / Junior means `entry`.
  - `confident=False` when family is `other` but the description matches a software, ML or data skill, or when years are missing for a non-intern title.
  - Run `build_taxonomy.py` once and commit `skills.yaml`.

- [ ] **Step 4: Run to verify they pass.** Run: same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: O*NET-based skill taxonomy and rules extraction with relevance gate"
```

---

### Task 7: Discover and curate the board list

**Files:**
- Create: `backend/scripts/discover_boards.py`, `sources/candidates.txt`, `sources/boards.yaml`
- Test: `backend/tests/unit/test_discover_boards.py`

**Interfaces:**
- Consumes: `fetch_board` (Task 4), `parse_location` (Task 6).
- Produces:
  - `slug_candidates(company: str) -> list[str]`: lowercase, `-` and no-space variants, deduped in order
  - `sources/boards.yaml`: entries `{company, ats, slug}`, sorted by company
  - At least 100 boards that each had ≥ 1 India-located or remote posting on the day of discovery

- [ ] **Step 1: Write the failing test**

```python
def test_slug_candidates():
    assert slug_candidates("Razor Pay Labs") == ["razorpaylabs", "razor-pay-labs"]
    assert slug_candidates("CRED") == ["cred"]
    assert slug_candidates("Swiggy (Bundl)") == ["swiggybundl", "swiggy-bundl"]   # punctuation dropped
```

- [ ] **Step 2: Write `sources/candidates.txt`:** about 300 company names. Include Indian product startups, YC companies hiring in India, and global tech companies with India engineering offices. One per line, `# category` comments allowed.

- [ ] **Step 3: Run discovery:** `uv run python -m scripts.discover_boards ../sources/candidates.txt > ../sources/boards.yaml`. It probes each slug candidate on all three ATSs at concurrency 8, and keeps a board only if ≥ 1 posting parses to `country == "IN"` or a remote scope. Expected: ≥ 100 boards.

- [ ] **Step 4: Validate.** Run: `uv run python -m app.cli check-boards`. Expected: exit 0. Remove any failing entries by hand.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: discover and curate India-relevant ATS boards"
```

---

### Task 8: LLM client, tracing spans and batched extraction (Stage B)

**Files:**
- Create: `backend/app/llm/{base,openai_compat,chain}.py`, `backend/app/tracing/{models,spans}.py`, `backend/migrations/versions/0003_spans.py`
- Create: `backend/app/extract/llm.py`, `backend/app/extract/service.py`
- Modify: `backend/app/cli.py` (add `extract`, `seed-skills`)
- Test: `backend/tests/fakes.py`, `backend/tests/unit/{test_llm_chain,test_extract_llm,test_merge}.py`, `backend/tests/integration/test_extract_service.py`

**Interfaces:**
- Consumes: `SkillMatcher`, `extract_rules`, `is_relevant`, `RuleFeatures` (Task 6); catalog models.
- Produces:
  - `Usage(frozen dataclass)`: `model: str, input_tokens: int | None, output_tokens: int | None, latency_ms: int`
  - `LLMError(Exception)`, `LLMQuotaExhausted(LLMError)`
  - `JsonLLM(Protocol)`: `complete_json(self, messages: list[dict[str, str]], schema: type[T], schema_name: str) -> tuple[T, Usage]`
  - `OpenAICompatProvider(name: str, base_url: str, api_key: str, model: str, client: httpx.Client, timeout: float = 60)`
    - Sends `response_format` as strict `json_schema` built from `schema.model_json_schema()`.
    - A 429 whose body or headers indicate a daily (RPD/TPD) limit raises `LLMQuotaExhausted`. Other 429s, 5xx, transport failures and invalid JSON raise `LLMError`.
  - `FallbackChain(providers: list[JsonLLM], spans: SpanSink)`
    - Tries the providers in order. A provider that raised `LLMQuotaExhausted` is skipped for the rest of the chain's life.
    - Raises `LLMQuotaExhausted` when every provider is exhausted, `LLMError` otherwise.
    - Records one span per attempt (kind `llm`).
  - `build_chain(specs: list[str], settings: Settings, client: httpx.Client, spans: SpanSink) -> FallbackChain | None`
    - Spec format `"gemini:<model>"` / `"groq:<model>"`.
    - Providers without a key are skipped. `None` if none are left.
  - `Span` model (table `spans`): trace_id, parent_id, kind CHECK in ('llm','tool','sql','http','job'), name, model, tokens_in, tokens_out, latency_ms, status CHECK in ('ok','error'), error, created_at.
  - `SpanSink(Protocol)`: `add(record: SpanRecord) -> None`; `DbSpanSink(db)`; `NullSpanSink()`; `span(sink, kind, name, **attrs)` context manager that measures latency and marks errors.
  - `JobRequirements(BaseModel)`: `required_skills: list[str], nice_to_have_skills: list[str], min_years: float | None, seniority: Literal["intern","new_grad","entry","mid","senior","unknown"], is_internship: bool, is_new_grad: bool, remote_policy: Literal["onsite","hybrid","remote_country","remote_global","unknown"], stipend_or_salary: str | None, education: str | None, one_line_summary: str`
  - `extract_batch(llm: JsonLLM, items: list[ExtractionItem]) -> dict[str, JobRequirements]`
    - `ExtractionItem(id: str, title: str, company: str, location_raw: str, description: str)`.
    - Descriptions are truncated to 6,000 chars. Response schema: `{"items": [{"id": str, **JobRequirements}]}`.
    - Items with unknown or missing ids are dropped.
  - `FinalFeatures(frozen dataclass)`: same fields as the `posting_features` row, plus `required: set[str]`, `nice: set[str]`, `unknown: set[str]`
  - `merge_features(rules: RuleFeatures, llm: JobRequirements | None, matcher: SkillMatcher) -> FinalFeatures`
    - LLM values override rules where not null or "unknown".
    - Location country and city always come from rules; remote_scope uses the LLM when rules said `unknown`.
    - Skills are canonicalised. Rule skills not in the LLM lists become `required`. Unmatched LLM skill names go to `unknown`.
  - `EXTRACTOR_VERSION: int = 1`
  - `run_extraction(db: Session, llm: JsonLLM | None, matcher: SkillMatcher, *, batch_size: int = 8, limit: int | None = None) -> ExtractionSummary(rules_only: int, llm: int, pending: int, irrelevant: int)`
    - Picks postings with `status='open' AND (processed_hash IS DISTINCT FROM content_hash OR features.extractor_version < EXTRACTOR_VERSION OR features.llm_pending)`.
    - Writes features, `posting_skills`, `unknown_skills`, `summary_text`, and `processed_hash = content_hash`.
  - CLI: `python -m app.cli extract`; `python -m app.cli seed-skills` (loads `skills.yaml` into `skills`).
- Test fakes (`tests/fakes.py`): `FakeLLM(handler: Callable[[list[dict]], dict] | list[dict | Exception])` implementing `JsonLLM` (pops responses; raises queued exceptions).

- [ ] **Step 1: Write the failing tests**

```python
# unit
def test_chain_falls_back_on_llm_error():
def test_chain_skips_quota_exhausted_provider_for_rest_of_run():   # 2nd call never touches provider 1
def test_chain_raises_quota_when_all_exhausted():
def test_openai_compat_sends_strict_schema_and_parses(respx or MockTransport):
def test_openai_compat_daily_429_is_quota_exhausted():
def test_extract_batch_truncates_descriptions_and_drops_unknown_ids():
def test_merge_llm_overrides_rules_but_location_from_rules():
def test_merge_unknown_skills_collected():
# integration
def test_run_extraction_writes_features_and_skills(db):           # stage 'llm', processed_hash == content_hash, posting_skills rows
def test_irrelevant_postings_skip_llm(db):                        # FakeLLM never called; stage 'rules', relevant False
def test_second_run_is_noop(db):
def test_version_bump_reprocesses(db, monkeypatch):
def test_llm_error_keeps_rules_only(db):                          # stage 'rules', llm_pending True, processed_hash set
def test_quota_exhaustion_stops_llm_and_marks_pending(db):        # Review Focus 2: batch 1 ok, batch 2 raises LLMQuotaExhausted → no further calls; rest llm_pending True
def test_llm_calls_recorded_as_spans(db):
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/unit/test_llm_chain.py tests/unit/test_extract_llm.py tests/unit/test_merge.py tests/integration/test_extract_service.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Port Engram's `OpenRouterProvider` error handling and `ResilientLLM` into the generic provider and N-way chain.
  - Add migration `0003_spans`.
  - The system prompt in `extract/llm.py` says: extract only what the posting states, use `null` or `"unknown"` otherwise, and return skills as written.

- [ ] **Step 4: Run to verify they pass.** Run: same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: LLM fallback chain, spans, batched extraction merged with rules"
```

---

### Task 9: Embeddings

**Files:**
- Create: `backend/app/embed/model.py`, `backend/app/embed/service.py`
- Modify: `backend/app/cli.py` (add `embed`, and `pipeline` = ingest → extract → embed → purge)
- Test: `backend/tests/unit/test_embed_text.py`, `backend/tests/integration/test_embed_service.py`, `backend/tests/model/test_fastembed.py` (marker `model`, run only when `RUN_MODEL_TESTS=1`)

**Interfaces:**
- Produces:
  - `Embedder(Protocol)`: `dim: int`; `embed_documents(texts: list[str]) -> list[list[float]]`; `embed_query(text: str) -> list[float]`
  - `FastEmbedder(model_name: str, cache_dir: str | None = None)`: loads lazily on first use; normalised vectors; prepends the query prefix in `embed_query`
  - `document_text(*, title: str, company: str, city: str | None, remote_scope: str, summary: str | None, skills: list[str]) -> str`. Format: `"{title} | {company} | {city or remote_scope} | {summary} | {', '.join(skills[:12])}"`, skipping empty parts.
  - `run_embedding(db: Session, embedder: Embedder, *, batch_size: int = 64) -> int` for postings that are `relevant`, open, and have `embedded_hash IS DISTINCT FROM content_hash`. Sets `embedding`, `embedded_hash` and `embedded_at = now()`.
- Test fake: `FakeEmbedder` in `tests/fakes.py`. Deterministic 384-d vectors from hashed lowercase tokens, L2-normalised, so shared words mean higher cosine.

- [ ] **Step 1: Write the failing tests**

```python
def test_document_text_format_and_skill_cap():
def test_run_embedding_only_relevant_open_and_changed(db):     # irrelevant → embedding None; second run returns 0
def test_reembed_after_content_change(db):
@pytest.mark.model
def test_fastembed_similarity_order():                        # "python backend internship" closer to backend doc than to sales doc; dim == 384
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/unit/test_embed_text.py tests/integration/test_embed_service.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement**, reusing Engram's `embed_in_batches` halving-on-OOM idea for `run_embedding`.

- [ ] **Step 4: Run to verify they pass.** Run: same command, plus `RUN_MODEL_TESTS=1 uv run pytest tests/model -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: fastembed embeddings for relevant postings and the pipeline command"
```

---

### Task 10: Identity with invites, and Brevo email

**Files:**
- Create, copied and adapted from TicketLoop: `backend/app/identity/{models,schemas,service,router,dependencies,errors}.py`, `backend/app/notify/email.py`, `backend/migrations/versions/0004_identity.py`
- Create: `backend/app/identity/invites.py`
- Modify: `backend/app/cli.py` (add `invite-create --count N`), `backend/app/main.py`, `backend/app/api/router.py`
- Test: TicketLoop's identity tests copied into `backend/tests/integration/test_auth_*.py`; new `backend/tests/integration/test_invites.py`, `backend/tests/unit/test_brevo.py`

**Interfaces:**
- Produces:
  - TicketLoop's `/auth/register|login|refresh|logout|password/*` and `/users/me` (GET, PATCH, plus DELETE)
  - `CurrentUser` dependency
  - `Invite` model: unique `code`, `used_by` FK users nullable, `used_at`
  - `create_invites(db, count: int) -> list[str]`: codes from `secrets.token_urlsafe(9)`
  - `RegisterIn` gains `invite_code: str`
  - `EmailSender(Protocol)`, `InMemoryEmailSender`, `BrevoEmailSender(api_key: str, sender_email: str, sender_name: str, client: httpx.Client)`. It POSTs `https://api.brevo.com/v3/smtp/email` with header `api-key`, JSON `{"sender":{"name","email"},"to":[{"email"}],"subject","textContent","htmlContent"?}`, and raises `EmailError` on a non-2xx response.
  - `EmailMessage` gains an optional `html: str | None`.
  - `DELETE /api/v1/users/me` deletes the user. Later tables use `ON DELETE CASCADE`.

- [ ] **Step 1: Write the failing tests**

```python
def test_register_requires_valid_invite(api):            # missing/unknown code → 400 problem "invalid_invite"
def test_invite_single_use(api):                          # second register with same code → 400
def test_register_marks_invite_used(api, db):
def test_brevo_payload_and_headers():                     # MockTransport captures; asserts URL, api-key header, JSON shape
def test_brevo_non_2xx_raises():
def test_delete_me_removes_user(api):
# plus TicketLoop's auth tests, adapted to pass invite_code
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/integration/test_invites.py tests/unit/test_brevo.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.** `create_email_sender(settings)`: `BrevoEmailSender` when `brevo_api_key` is set, otherwise `InMemoryEmailSender` (tests and local).

- [ ] **Step 4: Run to verify they pass.** Run: `uv run pytest -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: TicketLoop identity with invite-only signup and Brevo email"
```

---

### Task 11: Profiles and résumé intake

**Files:**
- Create: `backend/app/profiles/{models,schemas,service,router,resume}.py`, `backend/migrations/versions/0005_profiles.py`
- Test: `backend/tests/integration/test_profiles.py`, `backend/tests/unit/test_resume.py`

**Interfaces:**
- Consumes: `SkillMatcher`, `parse_location` (Task 6); `JsonLLM`, `build_chain` (Task 8); `CurrentUser` (Task 10).
- Produces:
  - `Profile` model (PK user_id → users ON DELETE CASCADE):
    - Columns:
      - `target_roles text[]` (each in software/ml/data, non-empty)
      - `seniority_ok text[]` default `{intern,new_grad,entry}`
      - `years_experience numeric(3,1)` 0–10
      - `locations text[]` (canonical cities), `open_to_relocate bool`, `remote_ok bool`
      - `avoid_companies text[]`, `notes text` ≤ 200, `digest_opt_in bool` default true
      - `taste_vector vector(384)` nullable, `feedback_count int` default 0
      - created_at, updated_at
  - `ProfileSkill` (user_id, skill_id, `level` 1–3), PK (user_id, skill_id).
  - `ProfileIn` / `ProfileOut` (pydantic). `ProfileOut` adds `unrecognized_skills: list[str]`.
  - `upsert_profile(db, matcher, user_id: UUID, data: ProfileIn) -> ProfileOut`, `get_profile(db, user_id) -> ProfileOut | None`
  - Routes: `GET /api/v1/profile` (404 problem `profile_missing` when none), `PUT /api/v1/profile`
  - `ProfileDraft(BaseModel)`: the `ProfileIn` fields, all optional
  - `draft_from_resume(llm: JsonLLM, matcher: SkillMatcher, text: str) -> ProfileDraft` (text truncated to 12,000 chars)
  - `POST /api/v1/profile/resume`: multipart `file` (PDF ≤ 2 MB via pypdf) or JSON `{text}`. Returns a draft and stores nothing. Uses `build_chain([settings.resume_model], …)`; 503 problem `llm_unavailable` when the chain is None or fails.

- [ ] **Step 1: Write the failing tests**

```python
def test_put_then_get_profile_roundtrip(api):
def test_skill_aliases_canonicalised_and_unknown_reported(api):   # ["k8s","Fortran77x"] → Kubernetes saved; "Fortran77x" in unrecognized
def test_unknown_target_role_is_422(api):
def test_city_alias_canonicalised(api):                            # "Bangalore" → "Bengaluru"
def test_resume_returns_draft_and_stores_nothing(api, db, fake_llm): # profiles/profile_skills counts unchanged; no table has a column holding the text (assert via information_schema scan for the uploaded sentinel string)
def test_resume_pdf_over_2mb_is_413(api):
def test_resume_without_llm_is_503(api):
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/integration/test_profiles.py tests/unit/test_resume.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.** The `fake_llm` fixture overrides an app-state factory `app.state.resume_llm_factory`, so tests never call Groq.

- [ ] **Step 4: Run to verify they pass.** Run: same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: profiles with canonical skills and résumé drafts that store nothing"
```

---

### Task 12: Search and ranking in one SQL statement

**Files:**
- Create: `config/ranking.yaml` (repo root), `backend/app/search/{config,sql,service,router}.py`
- Test: `backend/tests/unit/test_ranking_config.py`, `backend/tests/integration/test_search.py`

**Interfaces:**
- Consumes: `Embedder` (Task 9); `Profile`, `ProfileSkill` (Task 11); catalog models; `span` (Task 8).
- Produces:
  - `Weights(skill, rrf, experience, location, recency, personal: float)`
  - `RankingConfig(weights: Weights, rrf_k: int, candidates: int, recency_days: float, personal_ramp: int)`
  - `load_ranking_config(path: Path) -> RankingConfig`: `ValueError` unless the weights sum to 1.0 ± 1e-6
  - `ranking.yaml` holds exactly the Global Constraints values.
  - `Variant = Literal["fts","dense","hybrid","utility","full"]`
  - `RankedJob(frozen dataclass)`: `posting_id: UUID, title: str, company: str, url: str, city: str | None, remote_scope: str, first_seen_at: datetime, score: float, factors: dict[str, float], matched_skills: list[str], missing_skills: list[str]`
  - `search(db: Session, embedder: Embedder, config: RankingConfig, *, user_id: UUID, query: str | None, limit: int = 20, variant: Variant = "full", since: datetime | None = None, now: datetime | None = None, exclude_ids: Sequence[UUID] = ()) -> list[RankedJob]`
  - `ProfileIncompleteError(AppError)` → 409 `profile_incomplete`
  - `feed_query_text(profile: ProfileOut) -> str`: target role words plus the top 8 skills by level
  - `GET /api/v1/feed?q=&limit=` → `{"items": [RankedJob…], "query_used": str}`
- SQL shape (`sql.py` builds one `text()` statement with bound parameters; CTE names fixed):
  1. `eligible`. Joins `postings`, `posting_features` and `companies`. Conditions:
     - status open, relevant, `embedding IS NOT NULL`
     - `role_family = ANY(:roles)`, `seniority = ANY(:seniority_ok)`
     - Location: (`remote_scope IN ('remote_country','remote_global') AND :remote_ok AND coalesce(country,'IN')='IN'`) OR (`country='IN' AND (:open_to_relocate OR city = ANY(:locations))`)
     - company not in `:avoid`
     - no `interactions` row for the user with kind `dismissed`/`applied`
     - `first_seen_at > :since` when given
     - id not in `:exclude`
  2. `dense`: `ORDER BY embedding <=> :qvec LIMIT :candidates`, with `row_number()`.
  3. `kw`: `ts_rank_cd(search_tsv, websearch_to_tsquery('english', :q))` where it matches, `LIMIT :candidates`, with `row_number()`. Omitted (empty) when `:q` has no lexemes.
  4. `fused`: full outer join of `dense` and `kw` on id; `rrf = Σ 1/(:k + rank)`.
  5. `scored`. Factors:
     - `skill_overlap = (matched_required + 0.5·matched_nice) / greatest(required_count, 1)`
     - `experience_fit = CASE WHEN min_years IS NULL THEN 1 ELSE greatest(0, 1 − 0.5·greatest(0, min_years − :years)) END`
     - `location_fit`: 1 when remote-eligible or `city = ANY(:locations)`, else 0.5
     - `recency = exp(−age_days / :recency_days)`
     - `rrf_norm = rrf / (2.0/(:k+1))`
     - `personal`: `(1 − (embedding <=> :taste)/2) · least(1, :feedback_count / :ramp)` when taste is not null, else 0
  6. `deduped`: `DISTINCT ON (company_id, lower(title), coalesce(city, remote_scope))`, keeping the highest score.
  7. Final: `ORDER BY score DESC LIMIT :limit`, plus the matched/missing skill arrays.
- Variant scoring:
  - `fts`: kw rank only
  - `dense`: cosine only
  - `hybrid`: rrf only
  - `utility`: full formula with personal weight 0
  - `full`: everything

- [ ] **Step 1: Write the failing tests** (integration with `FakeEmbedder`; each test builds its own small corpus with factories)

```python
def test_weights_must_sum_to_one(tmp_path):
def test_hard_filters_exclude_closed_irrelevant_wrong_role_senior_dismissed_avoided_and_foreign_onsite(db):
def test_remote_postings_need_remote_ok(db):
def test_factors_sum_to_score(db):                         # abs(sum(w_i * f_i) - score) < 1e-6 for every item
def test_more_matched_required_skills_ranks_higher(db):
def test_keyword_only_match_is_retrieved(db):              # vector dissimilar, exact rare term in title → present
def test_recency_decays_with_tau_14(db):                   # same posting 14 days older → recency factor ≈ e^-1
def test_personal_zero_without_feedback(db):
def test_since_filters_by_first_seen(db):
def test_feed_without_profile_is_409(api):                 # Review Focus 3
def test_punctuation_query_falls_back_to_dense(api):       # q="!!! ??" → 200 with items, no SQL error
def test_feed_collapses_duplicate_roles(db):               # Review Focus 4: same company+title+city on two boards → one item
def test_variants_differ_only_in_scoring(db):              # same eligible set for all five variants
def test_search_records_sql_span(db):
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/unit/test_ranking_config.py tests/integration/test_search.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `sql.py`, `service.py` and `router.py`.**
  - Detect "no lexemes" with `SELECT numnode(websearch_to_tsquery('english', :q)) = 0` folded into the statement, or with a pre-check query.
  - Vectors are passed as pgvector parameters, never string-built.

- [ ] **Step 4: Run to verify they pass.** Run: same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: one-statement hybrid search with explained utility ranking"
```

---

### Task 13: Feedback, taste vector and signed links

**Files:**
- Create: `backend/app/feedback/{models,links,service,router}.py`, `backend/migrations/versions/0006_interactions.py`
- Modify: `backend/app/search/router.py` (log impressions after the feed is built)
- Test: `backend/tests/unit/test_links.py`, `backend/tests/integration/test_feedback.py`

**Interfaces:**
- Consumes: `RankedJob`, `search` (Task 12); `Profile` (Task 11); `CurrentUser`.
- Produces:
  - `Interaction` model:
    - Columns: user_id → users ON DELETE CASCADE, posting_id, `kind` CHECK in ('shown','clicked','saved','dismissed','applied'), `surface` CHECK in ('feed','digest','chat'), `rank` int nullable, created_at.
    - Partial UNIQUE (user_id, posting_id, kind) WHERE kind IN ('saved','dismissed','applied').
  - `record(db, *, user_id, posting_id, kind, surface, rank: int | None = None) -> bool`: True if a new row was inserted. `ON CONFLICT DO NOTHING` for unique kinds.
  - `undo(db, *, user_id, posting_id, kind: Literal["saved","dismissed"]) -> bool`
  - `record_impressions(db, *, user_id, items: list[RankedJob], surface) -> None`: one multi-row insert
  - `recompute_taste(db, user_id) -> None`
    - `taste = normalize(mean(saved) − 0.5·mean(dismissed))`. A missing side counts as zero. A zero vector stores NULL.
    - `feedback_count` = saved + dismissed count.
  - `sign_link(secret: str, *, user_id: UUID, posting_id: UUID, action: Literal["open","save","dismiss"], expires_at: datetime) -> str`: base64url(JSON payload) + "." + base64url(HMAC-SHA256)
  - `verify_link(secret: str, token: str, *, now: datetime) -> LinkClaims`: raises `InvalidLinkError` or `ExpiredLinkError`
  - Routes:
    - `POST /api/v1/postings/{id}/feedback {kind: saved|dismissed|applied|clicked}` → 204
    - `DELETE /api/v1/postings/{id}/feedback/{kind}` → 204
    - `GET /api/v1/saved` → `{"items": [...]}` (saved, newest first)
    - `GET /api/v1/l/{token}` (no auth):
      - `open`: record `clicked`, then 303 to the posting URL.
      - `save` / `dismiss`: record the kind and recompute taste, then 303 to `{frontend_url}/thanks?action=…`.
      - Invalid token: 400 problem. Expired token: 410 problem.

- [ ] **Step 1: Write the failing tests**

```python
def test_sign_verify_roundtrip(): ...
def test_tampered_payload_rejected(): ...                  # flip one char → InvalidLinkError
def test_expired_link_rejected(): ...
def test_save_is_idempotent(api, db):                      # two POSTs → one row
def test_signed_link_is_idempotent(api, db):               # Review Focus 5: same save link twice → one row, both 303
def test_dismissed_posting_leaves_feed(api):
def test_taste_vector_moves_toward_saved(db):              # cosine(taste, saved_vec) > cosine(taste, dismissed_vec)
def test_feedback_count_counts_saves_and_dismisses_only(db):
def test_feed_logs_impressions_with_rank(api, db):
def test_undo_save(api, db):
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/unit/test_links.py tests/integration/test_feedback.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.** Mean vectors are computed in SQL with pgvector's `avg(embedding)` over joined postings. Normalisation happens in Python.

- [ ] **Step 4: Run to verify they pass.** Run: same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: feedback events, Rocchio taste vector, signed one-click links"
```

---

### Task 14: Weekly digest and status endpoint

**Files:**
- Create: `backend/app/digest/{models,render,service}.py`, `backend/migrations/versions/0007_digest.py`, `backend/app/api/status.py`
- Modify: `backend/app/cli.py` (add `digest`)
- Test: `backend/tests/integration/test_digest.py`, `backend/tests/integration/test_status.py`

**Interfaces:**
- Consumes: `search` (Task 12) with `since` and `exclude_ids`; `sign_link`, `record_impressions` (Task 13); `EmailSender` (Task 10).
- Produces:
  - `DigestRun` model: user_id → users ON DELETE CASCADE, `sent_at`, `posting_ids uuid[]`, `status` CHECK in ('sent','skipped_empty','failed').
  - `render_digest(user_name: str, items: list[RankedJob], links: Callable[[RankedJob, str], str]) -> tuple[str, str]`: text and HTML. Each item shows title, company, place, the top 2 factors as words, and the Open / Save / Not for me links.
  - `run_digest(db, sender: EmailSender, embedder: Embedder, config: RankingConfig, settings: Settings, *, now: datetime) -> DigestSummary(sent: int, skipped_recent: int, skipped_empty: int, failed: int)`
    - Covers users with `digest_opt_in` and a complete profile.
    - Skips users with a `sent` run in the last 24 h.
    - `since` = last sent run, or `now − 7 days`.
    - Top 5, excluding postings already sent in earlier digests.
    - Links expire after 14 days. Impressions are recorded with surface `digest`.
  - `GET /api/v1/status` (no auth) returns:
    - `last_ingest`: `{started_at, finished_at, boards_ok, boards_failed}` or null
    - `open_postings`, `relevant_postings`: int
    - `failing_boards`: `[{company, ats, slug, consecutive_failures}]`
    - `llm_calls_today`: `{model: count}`
    - `freshness_hours_p50`: median of `embedded_at − first_seen_at` over postings first seen in the last 7 days (spec §6.1)
    - `search_latency_ms`: `{p50, p95}` from `sql` spans in the last 24 h (spec §6.5)
    - `digests`: last 4 weeks, `[{week, sent, save_rate_at5, dismiss_rate}]` (spec §7.4). `save_rate_at5` = share of digest impressions with rank ≤ 5 that got a `saved` row within 7 days.

- [ ] **Step 1: Write the failing tests**

```python
def test_digest_sends_top5_new_since_last(db, fake_email):
def test_digest_not_sent_twice_within_24h(db, fake_email):
def test_user_with_no_matches_gets_no_email(db, fake_email):     # run row status 'skipped_empty', sender.sent == []
def test_digest_links_verify_and_point_to_l_route(db, fake_email):
def test_digest_excludes_previously_sent_postings(db, fake_email):
def test_status_reports_failing_boards_and_llm_calls(api, db):
def test_status_freshness_latency_and_digest_save_rate(api, db):   # fixed timestamps → exact p50 hours; 2 of 5 digest items saved → 0.4
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/integration/test_digest.py tests/integration/test_status.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run to verify they pass.** Run: same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: weekly digest with one-click links and a status endpoint"
```

---

### Task 15: Web app and same-origin proxy

**Files:**
- Create: `frontend/` (Vite React TS)
  - `src/api/{client,problem}.ts`, `src/auth/{session.ts,AuthProvider.tsx}`: adapted from TicketLoop
  - `src/components/{WakeGate,JobCard,WhyPanel,Layout}.tsx`
  - `src/pages/{Login,Register,Feed,Saved,Profile,Thanks}.tsx`, `src/App.tsx`
  - `functions/api/[[path]].ts`, `vite.config.ts` (dev proxy `/api` → `http://localhost:8000`)
- Modify: `.github/workflows/ci.yml` (add the `frontend` job: format, lint, typecheck, test, API types in sync, build)
- Test: `frontend/src/api/client.test.ts` (from TicketLoop), `frontend/src/components/WakeGate.test.tsx`, `frontend/functions/api/proxy.test.ts`

**Interfaces:**
- Consumes: the REST routes from Tasks 10–14, with types from `npm run api:types` (OpenAPI to `src/api/schema.d.ts`, as in TicketLoop).
- Produces:
  - `onRequest(context: { request: Request; env: { API_ORIGIN: string } }): Promise<Response>`
    - Forwards method, path, query, headers (minus `host`, `cf-connecting-ip`, `x-forwarded-*`) and body to `${API_ORIGIN}${pathname}${search}`.
    - Passes `Set-Cookie` through unchanged.
    - GET/HEAD only: on network errors, 502 or 503, retry with backoff 1, 2, 4, 8, 16, 32 s (about 63 s total).
    - After that, return 503 problem JSON `{"type":"about:blank","title":"Server is waking up","status":503}`.
  - `WakeGate`: polls `/api/v1/health` every 3 s and shows "Waking the server, this takes about a minute" until it gets a 200, then renders its children.
  - Feed page: an item list. Each `JobCard` has Save / Not for me / Open, and a "Why" toggle that shows the factor bars, matched skills and missing skills.

- [ ] **Step 1: Write the failing tests**

```ts
test("proxy forwards method, path, query, body and set-cookie", ...)
test("proxy strips host and cf headers", ...)
test("proxy retries GET through cold start", ...)   // Review Focus 5: fetch fails twice then 200 → returns 200, 3 calls
test("proxy does not retry POST", ...)              // POST 503 → returned as-is, 1 call
test("WakeGate shows waking message until health is 200", ...)
// plus TicketLoop's client refresh-on-401 test
```

- [ ] **Step 2: Run to verify they fail.** Run: `npm test` (in `frontend/`). Expected: FAIL.

- [ ] **Step 3: Implement the pages and the proxy.** Use the TicketLoop styling approach (plain CSS) and keep it minimal.

- [ ] **Step 4: Run to verify they pass.** Run: `npm run lint && npm run typecheck && npm test && npm run build`. Expected: all succeed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: web app with wake gate and same-origin Pages proxy"
```

---

### Task 16: Deploy for $0

**Files:**
- Create: `backend/Dockerfile`, `render.yaml`, `.github/workflows/pipeline.yml`, `.github/workflows/digest.yml`, `backend/scripts/smoke.py`
- Modify: `README.md` (deploy and operations section)
- Test: `backend/tests/unit/test_smoke_script.py`, plus a `docker build` job in `ci.yml`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - **Image.** Based on TicketLoop's Dockerfile.
    - At build time: `ENV FASTEMBED_CACHE_PATH=/app/models` and `RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"`, so the model is baked in.
    - `CMD`: `alembic upgrade head` (using `DIRECT_DATABASE_URL`), then `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
  - **`render.yaml`:** one web service, `runtime: docker`, `plan: free`, `region: singapore`, `healthCheckPath: /api/v1/health`. Env vars `DATABASE_URL` (pooled), `DATABASE_POOLED=true`, `DIRECT_DATABASE_URL`, `ENVIRONMENT=production`, `JWT_SECRET_KEY`, `FEEDBACK_LINK_SECRET`, `GROQ_API_KEY`, `BREVO_API_KEY`, `EMAIL_FROM_ADDRESS`, `FRONTEND_URL` (all `sync: false`).
  - **`pipeline.yml`:**
    - Triggers: `schedule: "0 */6 * * *"` + `workflow_dispatch`; `concurrency: pipeline`.
    - Steps: uv sync, cache `~/.cache/fastembed`, `uv run python -m app.cli pipeline`.
    - Secrets: `DATABASE_URL` (direct), `GEMINI_API_KEY`, `GROQ_API_KEY`.
  - **`digest.yml`:** `schedule: "30 3 * * 1"` + `workflow_dispatch`, runs `uv run python -m app.cli digest`.
  - **`smoke.py`:** `main(argv: list[str], client: httpx.Client | None = None) -> int`, run as `--base-url URL --invite CODE`. It checks health, registers, puts a profile, requests the feed and the status page, and returns non-zero on any failure.

- [ ] **Step 1: Write the failing test.** `test_smoke_script.py` calls `smoke.main(["--base-url", "http://testserver", "--invite", code], client=api)` with the integration TestClient and asserts it returns 0.

- [ ] **Step 2: Run to verify it fails.** Run: `uv run pytest tests/unit/test_smoke_script.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement the files above.**

- [ ] **Step 4: Aswin sets up the free accounts.** Exact names:
  - **Neon:** project `shortlist` in `aws-ap-southeast-1`. Copy the pooled and direct URLs.
  - **Render:** a Blueprint from `render.yaml`.
  - **Cloudflare Pages:** connected to the repo, root `frontend`, build `npm run build`, output `dist`, env `API_ORIGIN=https://<render-service>.onrender.com`.
  - **API keys:** Groq, Gemini (AI Studio), Brevo. Verify the sender email in Brevo.
  - **GitHub secrets:** `DATABASE_URL`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `BREVO_API_KEY`, `FEEDBACK_LINK_SECRET`, `JWT_SECRET_KEY`, `EMAIL_FROM_ADDRESS`, `FRONTEND_URL`.

- [ ] **Step 5: First production run.**
  - Run `pipeline` by hand (`workflow_dispatch`). Expected: `/api/v1/status` shows ≥ 100 boards OK and relevant_postings > 0.
  - Run `uv run python -m scripts.smoke --base-url https://<pages-domain> --invite <code>`. Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: Render, Neon, Pages and Actions deployment on free tiers"
```

---

### Task 17: Extraction and ranking evaluation

**Files:**
- Create: `evals/snapshot.py`, `evals/stats.py`
- Create: `evals/extraction/{label.py,run.py,labels.jsonl}`
- Create: `evals/ranking/{profiles.yaml,queries.yaml,pool.py,label.py,qrels.json,run.py,tune.py}`
- Create: `docs/evaluation/extraction-<date>.md`, `docs/evaluation/ranking-<date>.md`, `evals/data/corpus-<date>.jsonl.gz`
- Test: `backend/tests/unit/test_eval_stats.py`, `backend/tests/integration/test_snapshot.py`

**Interfaces:**
- Consumes: `extract_rules`, `merge_features`, `extract_batch` (Tasks 6 and 8); `search(..., variant=…)` (Task 12); `FastEmbedder` (Task 9).
- Produces:
  - `export_snapshot(db, path: Path) -> int` and `load_snapshot(db, path: Path) -> int`. Covers postings, features, skills, posting_skills and embeddings for relevant open postings.
  - `bootstrap_ci(values: list[float], *, n: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float]`
  - `skill_prf(gold: list[set[str]], pred: list[set[str]]) -> tuple[float, float, float]` (micro-averaged)
  - Each runner writes one markdown report with tables, CIs and the exact command, and is reproducible with:
    - `uv run python -m evals.extraction.run --snapshot … --labels …`
    - `uv run python -m evals.ranking.run --snapshot … --qrels …`
  - Ranking variants compared with `ranx.compare` (paired t-test): `fts`, `dense`, `hybrid`, `utility`, `full`. Metrics nDCG@10, Recall@20, MRR.
  - Personal term: per profile, 3 relevant + 3 non-relevant judged items become seed feedback (training). Score on the rest.
  - `tune.py`: grid over weights in steps of 0.05 (summing to 1) on a 70% query split. Reports tuned vs initial on the 30% held-out split. Writes `config/ranking.tuned.yaml`, which is not applied automatically.

- [ ] **Step 1: Write the failing tests**

```python
def test_bootstrap_ci_deterministic_and_contains_mean():
def test_skill_prf_known_values():          # gold [{a,b}], pred [{a,c}] → (0.5, 0.5, 0.5)
def test_ranx_ndcg_on_toy_qrels():          # known value from ranx docs example
def test_snapshot_roundtrip(db, tmp_path):  # export then load into a clean schema → same ids, features, vector equality
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/unit/test_eval_stats.py tests/integration/test_snapshot.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement the snapshot, stats, runners and labelling CLIs.** The CLIs show one item at a time; keys `0/1/2` label, `s` skips, `q` quits; progress is saved after every key.

- [ ] **Step 4: Run to verify they pass.** Run: same command. Expected: PASS.

- [ ] **Step 5: Aswin labels.**
  - Extraction: 40 postings stratified across the 3 ATSs (about 45 min).
  - Ranking:
    - 15 profiles in `profiles.yaml`, ≥ 5 from consenting classmates.
    - `queries.yaml` holds feed mode + 2 free-text queries per profile (45 queries).
    - `pool.py` pools the top 20 from each of the 5 variants.
    - Label 0/1/2 (expect roughly 1,500–2,000 judgments; spread over evenings).
    - A classmate double-labels 10%. `run.py` reports Cohen's κ.

- [ ] **Step 6: Run the evals and write the reports.**
  - Run: `uv run python -m evals.extraction.run …` and `uv run python -m evals.ranking.run …`.
  - Expected: both reports written, each with n, CIs and the command line.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "eval: extraction and ranking reports on a frozen snapshot"
```

---

### Task 18: README with numbers

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the README.**
  - What Shortlist is and who it is for.
  - The architecture diagram from spec §5.
  - The $0 stack table.
  - Eval headline numbers with n and CIs, linking `docs/evaluation/*`.
  - How to run locally: `docker compose up -d db`, `uv sync`, `alembic upgrade head`, `uv run python -m app.cli seed-skills`, `pipeline`, `uvicorn`, `npm run dev`.
  - Operations: `/status`, re-enabling scheduled workflows after 60 days without commits, rotating keys.
  - Privacy: what is sent where, and no résumé storage.
  - O*NET attribution.
  - Inspiration (ideas only) with links.

- [ ] **Step 2: Verify.** Every command in the README runs on a fresh clone. Run: `uv run pytest && (cd ../frontend && npm test)`. Expected: green.

- [ ] **Step 3: Commit**

```bash
git add README.md && git commit -m "docs: README with architecture, free stack, eval results, operations"
```

---

## After this plan

Phase 2 (Agent) gets its own plan once Task 18 is done. It builds on these interfaces:
- `search()`, `RankedJob` (Task 12)
- `record()`, `recompute_taste()` (Task 13)
- `upsert_profile()`, `get_profile()`, `ProfileIn` (Task 11)
- `JsonLLM`, `FallbackChain`, `span()` (Task 8)
- The tool-calling result recorded in `docs/phase-0-early-checks.md` (Task 2)

The Phase 2 plan adds tools, the loop, memory through `update_profile`, routing, budgets, chat UI and the τ-bench-style eval harness.

The cross-encoder and asymmetric-encoder ablations (spec §7.2) belong to Phase 3, as spec §10 sets out. They plug into `evals/ranking/run.py` as extra variants.
