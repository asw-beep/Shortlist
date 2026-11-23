# Shortlist — Design

**Status:** Draft for review, 2026-11-23
**Owner:** Aswin
**Folder:** `E:\Projects\Shortlist` (new repo; will be public on GitHub as `asw-beep/Shortlist`)

---

## 1. What this is, and why

Shortlist finds internships and entry-level roles for Aswin's 2027 batch at IIIT Kottayam. It reads live postings from company career boards, ranks them for each student, sends a weekly digest, and lets students refine their search by chatting with an agent that can call tools.

It exists for two reasons:

1. **To be a portfolio project that maps one-to-one onto the Elip SDE Intern role** (YC W25, AI career agent). Elip screens for LLM tool use, structured outputs, and table/query design. They want retrieval, ranking and personalisation over a large, constantly changing jobs index; LLM output evaluation; and shipped, reliable backend features. Good-to-haves are a recommender or search system, RAG or LLM evals, a live project with real users, and Docker or cloud deploys. Aswin's current repos (Engram, TicketLoop) cover structured outputs, semantic search and database design. They don't cover tool use, recommendation and personalisation, agent evals with numbers, or real users. Shortlist covers exactly those.
2. **To be genuinely useful to his batch during placement season**, which is also what produces real users and real feedback data.

It sits on the resume next to Engram and TicketLoop, so it must not duplicate them. Engram is document RAG with dedicated stores (Qdrant, plus OpenSearch planned). Shortlist is a recommender and agent on Postgres alone.

## 2. Goals, non-goals, anti-goals

**Goals**
- A live index of postings from public ATS boards that refreshes every 6 hours, re-processing only postings that changed.
- Personalised ranking where each result carries its own explanation, plus one-click feedback that changes later rankings.
- A chat agent that uses real tool calling, keeps durable memory of the user's preferences, and stays within free-tier limits.
- Measured quality at three levels: extraction, ranking and agent conversations. Each number can be reproduced with one documented command.
- **$0 running cost** on free tiers, deployed and used by real classmates.
- Code Aswin can defend line by line, built in small commits.

**Non-goals**
- Auto-apply, résumé tailoring and cover letters. Other repos do these, and they aren't the gap.
- Scraping LinkedIn, Naukri, Internshala or any site without a public API.
- Multi-agent frameworks such as LangGraph, Kubernetes, or any paid service.
- A polished consumer UI. Four plain screens are enough.

**Anti-goals** (failures even if the code works)
- An "LLM wrapper" that calls the model per job per search.
- Quality claims without measured numbers behind them.
- Storing raw résumés, or sending users' personal data to a free tier that trains on it.
- A git history of giant AI-generated commits.

## 3. Constraints

- **Money:** $0, which means free tiers only. Their limits shape the design:

| Service | Free allowance that matters | Consequence for the design |
|---|---|---|
| Neon Postgres | 1 GB storage per project, 100 CU-hours/month, scales to zero after 5 min idle, pgvector included | One database for everything. Fine at about 10k postings. |
| Render web service | 512 MB RAM, 0.1 CPU, spins down after 15 min idle, about 1 min to wake | API must be lean. No cross-encoder in the request path. Frontend must handle the cold start. |
| GitHub Actions (public repo) | Standard runners free. Scheduled workflows auto-disable after 60 days without repo activity. | All batch work (ingest, embed, digest, evals) runs here. |
| Cloudflare Pages | Static asset requests free and unlimited | Frontend is a static build. |
| Gemini API free tier | Flash-Lite models about 500 requests/day; free-tier data may be used to improve Google's products | Extraction only, on **public posting text only**, batched. |
| Groq free tier | gpt-oss-120b and gpt-oss-20b: 30 RPM, 1K req/day, 8K tokens/min, 200K tokens/day, per model | Agent chat with strict token budgets. Two-model routing doubles capacity. |
| Brevo email API (HTTP) | 300 emails/day, sender email verified, no domain needed | Digest and password-reset email. Must be HTTP: Render Free blocks outbound SMTP ports 25/465/587, so Gmail SMTP fails from the API. Resend needs a verified domain and allows 100/day. |

- **People and time:** one developer, about 10 working days, done one phase at a time.
- **Machine:** Windows laptop with Docker Desktop. Python 3.12 + uv, Node 24 LTS, matching TicketLoop.
- **Reuse:** Aswin's own code from TicketLoop (app factory, settings, RFC 9457 errors, JSON logs with request IDs, Alembic, test database rolled back after every test, identity module, CI) and Engram (LLM client with model fallback and strict JSON schema, retry helpers, embedding batching). **No code is copied from other people's repos.** Only ideas are borrowed (§6). Compass, JobGraph and Hiring-Agent-Platform have no license, so their code can't be reused anyway.

## 4. Approaches considered

**4.1 Fork a similar repo vs build from scratch: decided, scratch.** The only forkable candidate, observable-job-agent (MIT), is built the opposite way: no database, jobs fetched from third-party APIs on every run, the LLM ranks at most 10 jobs, and it's a fixed LangGraph pipeline. Forking would mean deleting most of it, keeping their copyright notice, and having the repo recognised as a public tutorial series. Building from scratch while reusing Aswin's own code gives an architecture that matches the design and a clean history.

**4.2 When the LLM runs: chosen, when a posting arrives (write time).** The alternative is scoring each job with the LLM at search time, which is what observable-job-agent and Compass do. That costs LLM calls per search, caps how many jobs can be considered, and doesn't fit free-tier limits. Here the LLM extracts structured fields once per posting version. Search is SQL plus arithmetic over the whole index. LLM cost scales with how many postings change, not with traffic.

**4.3 Storage: chosen, Postgres for everything.** The alternative is a vector DB plus a search engine plus Postgres (Engram's route). At about 10k postings, pgvector (HNSW) and built-in full-text search in one database are enough. A single SQL statement can then filter, retrieve, fuse and score in one round trip. It also contrasts usefully with Engram in interviews.

**4.4 Agent: chosen, hand-written loop on native tool calling.** The alternative is LangGraph or a similar framework (Compass, JobGraph, observable-job-agent). A ~150-line loop is easier to defend, debug and budget for tokens.

## 5. System overview

```
           every 6h (GitHub Actions)                         weekly (GitHub Actions)
  ┌──────────────────────────────────────────┐          ┌──────────────────────────┐
  │ ingest → filter → extract → embed        │          │ digest: top-5 per user    │
  │ Greenhouse / Lever / Ashby public APIs   │          │ Gmail SMTP, signed links  │
  └───────────────┬──────────────────────────┘          └────────────┬─────────────┘
                  │ writes                                            │ reads
                  ▼                                                   ▼
        ┌────────────────────────────────────────────────────────────────────┐
        │ Neon Postgres (Singapore): postings · features · skills · vectors   │
        │ full-text · users · profiles · interactions · chats · spans · runs  │
        └───────────────▲───────────────────────────────▲────────────────────┘
                        │ one SQL round trip per search  │
              ┌─────────┴──────────────┐                 │
              │ FastAPI on Render       │  tool calls ───┘
              │ search · feedback ·     │◀──── Groq (gpt-oss-120b / 20b)
              │ agent loop · auth       │
              └─────────▲──────────────┘
                        │ HTTPS (CORS)
              ┌─────────┴──────────────┐
              │ React (Vite) static on  │  Feed · Saved · Chat · Profile
              │ Cloudflare Pages        │
              └────────────────────────┘
```

Request-path cost: **search = 1 local query embedding + 1 SQL query + 0 LLM calls**. A **chat turn = 1–3 LLM calls**.

## 6. Components

Each component lists what it does, how, what it borrows from (ideas only), and how it is measured.

### 6.1 Sources and ingestion

- **Sources:** public job-board endpoints, no keys needed:
  - Greenhouse `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`
  - Lever `https://api.lever.co/v0/postings/{company}?mode=json`
  - Ashby `https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true`
- **Board list:** `sources/boards.yaml` lists about 150 companies hiring in India or remote-for-India (Indian startups, YC companies, global tech with India offices). Each entry has `ats`, `slug` and `company`. `cli check-boards` validates every slug and reports dead ones.
- **Run:** `cli ingest` fetches boards concurrently (limit 8, polite timeouts, retries with backoff) and normalises them into one `RawPosting` shape. It keeps raw ATS fields in a `source_metadata` JSONB column. It upserts by `(ats, external_id)` and computes a `content_hash` over the normalised text. Unchanged hash means no further work.
- **Lifecycle:** a posting missing from **two consecutive** runs is marked `closed_at`, which avoids flapping on a transient API miss. Description text of closed postings is purged after 30 days. The row stays so interactions keep their reference.
- **Health:** `ingest_runs` holds one row per run, and `board_runs` holds per-board status, counts, latency and a named failure reason (timeout, 404, schema change). A board failing 5 runs in a row is auto-disabled and listed on `/status`.
- **Borrowed from:** Compass (public Greenhouse/Lever/Ashby APIs on a daily cron, URL-hash dedupe, no LinkedIn); JobGraph (keep the source's structured fields, dedupe on normalised identity); observable-job-agent (a failing source reports a named reason, plus per-source timing).
- **Measured by:** index freshness (median hours from a posting's first appearance on its board to being searchable, from `first_seen_at` vs run time) and the per-board failure rate.

### 6.2 Filter, then extract

Cheap deterministic work happens first. The LLM is used only on what survives and only where rules are unsure.

- **Stage A (rules, every new or changed posting):**
  - Location: parse into `{country, city, remote_scope}` using an India city list and remote phrases.
  - Role family from the title: software, ML/AI, data, or other.
  - Seniority and intern/new-grad flags from title patterns.
  - Required years from regexes like `(\d+)\+?\s*years`.
  - Skills by dictionary matching against a taxonomy (see below).
- **Relevance gate:** keep postings that are India-located or remote-eligible for India, AND in role families software, ML/AI or data, AND not senior (title rules or more than 3 required years). The rest are stored but skip Stage B and embedding, and are filtered out of search.
- **Stage B (LLM, relevant postings only):** batches of 8 postings per call, strict JSON schema output into `JobRequirements`. Fields: `required_skills`, `nice_to_have_skills`, `min_years`, `seniority`, `is_internship`, `is_new_grad`, `remote_policy`, `stipend_or_salary` (if stated), `education`, `one_line_summary`.
  - The skills it returns are mapped to canonical IDs, and unknown skills go to a review list.
  - Results are cached by `(content_hash, extractor_version)`. Re-extraction happens only on change or when the version is bumped.
  - **Models:** Gemini Flash-Lite (free) first, then Groq gpt-oss-20b, then Stage A only. Every call site has a non-LLM path, as in Delta.
- **Skill taxonomy:** O*NET Technology Skills / Hot Technologies (Creative Commons license; attribution in README) plus a hand-kept `taxonomy/aliases.yaml` for Indian and modern-stack spellings (k8s→Kubernetes, postgres→PostgreSQL, gen ai→Generative AI).
- **Budget check:** about 150 boards × about 40 postings ≈ 6k postings. If 10–20% are relevant, that's 600–1,200, so the one-off backfill is about 75–150 batched calls. Daily change is about 5–20 calls. This is well inside about 500 requests/day.
- **Borrowed from:** Compass (typed requirement extraction, taxonomy-canonical skills, keyword pre-filter with a cheap LLM fallback); JobGraph (facts from structured data first, LLM only for fuzzy fields).
- **Measured by:** a 40-posting labelled set. Report per-field accuracy and skill precision/recall/F1 for **rules-only vs rules+LLM**, which shows what the LLM actually adds, plus LLM calls per posting.

### 6.3 Embeddings

- **Model:** `BAAI/bge-small-en-v1.5` (384-d) via **fastembed** (quantized ONNX, no PyTorch), used in both the Actions worker and the API so documents and queries share one space. No embedding API, no rate limit, and no user text leaves the server for embedding.
- **Document text:** `title | company | city/remote | one_line_summary | top required skills`. It's short and focused on matching, not the full description.
- **Query text:** the bge retrieval prefix plus the user query. In feed mode with no query, it's built from the profile as target roles plus top skills.
- **Phase 0 check (blocking):** resident memory and latency inside a `--memory 512m --cpus 0.1` container. If it doesn't fit, switch both sides to the Gemini embedding API and re-embed (about 6k docs, one Actions run).
- **Stretch:** asymmetric encoders, a heavy document encoder offline with a tiny query encoder online (Qdrant's Constella research preview). Evaluated as an ablation only, never in production unless it wins.
- **Borrowed from:** Engram's embedding batching (own code); Qdrant fastembed.

### 6.4 Data model (Postgres)

Main tables (constraints enforce the rules, TicketLoop-style):

- `companies`, `boards` (ats, slug, enabled, consecutive_failures), `ingest_runs`, `board_runs`
- `postings`
  - Columns: id, board_id, external_id, url, title, location_raw, description, source_metadata jsonb, content_hash, status, first_seen_at, last_seen_at, closed_at, embedding vector(384), search_tsv tsvector generated from title, company and summary
  - UNIQUE(board_id, external_id)
- `posting_features`: posting_id PK, extractor_version, stage ('rules'/'llm'), role_family, seniority, is_internship, is_new_grad, min_years, country, city, remote_scope, relevant bool, summary
- `skills` (canonical name, aliases[]), `posting_skills` (posting_id, skill_id, kind required/nice)
- `users`, `refresh_tokens` (reused from TicketLoop), `invites`
- `profiles`
  - Columns: user_id PK, target_roles[], years_experience, locations[], open_to_relocate, remote_ok, avoid_companies[], avoid_industries[], notes, taste_vector vector(384), feedback_count
  - Plus `profile_skills` (user_id, skill_id, level)
- `interactions` (user_id, posting_id, kind shown/clicked/saved/dismissed/applied, rank, surface feed/digest/chat, created_at). UNIQUE(user, posting, kind) for saved/dismissed/applied.
- `digest_runs`, `chat_sessions`, `chat_messages`, `spans` (§6.10)
- Indexes:
  - GIN on `search_tsv`
  - btree on (status, role_family, seniority)
  - **No vector index at first.** The relevant, open set is about 1–2k rows. An exact scan after the hard filters is a few milliseconds and never under-returns. An approximate HNSW index with selective filters can return fewer than k rows unless pgvector's iterative scans are enabled. Add a partial HNSW index (with `hnsw.iterative_scan`) only if the relevant set passes about 20k rows, and measure before and after.

Storage estimate: about 10 KB per posting × 10k is about 100 MB, well under 1 GB.

### 6.5 Search and ranking (one SQL statement)

1. **Hard filters** (a CTE): open, relevant, location eligible for the user, role family in the user's targets, seniority allowed, and not dismissed, applied or from an avoided company. Must-haves are applied before ranking, so ineligible jobs never take ranking slots.
2. **Retrieve:** top 100 by cosine distance within the filtered set, and top 100 by `ts_rank_cd(search_tsv, websearch_to_tsquery(q))`.
3. **Fuse** with Reciprocal Rank Fusion (k = 60).
4. **Score** each fused candidate with a transparent utility, computed in SQL:
   `score = 0.30·skill_overlap + 0.25·rrf_norm + 0.15·experience_fit + 0.10·location_fit + 0.10·recency + 0.10·personal·min(1, feedback_count/10)`
   - `skill_overlap` = matched required skills ÷ required skills, plus half credit for nice-to-have skills
   - `experience_fit` = 1 when within range, minus 0.5 per year short
   - `recency` = exp(−days_since_first_seen / 14)
   - `personal` = cosine(taste_vector, embedding)
5. **Return** the top N with the factor breakdown and matched/missing skills, so the explanation needs no LLM.

- Weights live in `config/ranking.yaml` and are tuned by grid search on the labelled set (§7.2). Initial values are listed above.
- **No cross-encoder in the request path** (0.1 CPU). It is evaluated offline as an ablation and added only if it earns its latency.
- **Borrowed from:** RRF in SQL (Supabase and DigitalOcean hybrid-search guides); JobMatchAI (must-have filters before reranking, a weighted multi-factor utility with per-factor explanations); AdaptJobRec (user-interest adjustment from feedback).
- **Measured by:** nDCG@10, Recall@20 and MRR across variants (§7.2), plus p50/p95 search latency from spans.

### 6.6 Personalisation and feedback

- **Events:** impressions (`shown` with rank and surface) are logged in batches. Clicks, saves, dismisses and applies are logged on action.
- **Taste vector (Rocchio-style):** on every save or dismiss, `taste = normalize(mean(saved) − 0.5·mean(dismissed))`, stored on the profile. Its weight in the score ramps up with `feedback_count` so new users aren't skewed.
- **One-click digest links:** an HMAC-signed token (user, posting, action, expiry) at `/f/{token}`. It writes the interaction idempotently, then redirects to the posting or a thank-you page.
- **Measured by:** offline lift from the personal term using simulated feedback (§7.2), and online save-rate@5 and dismiss-rate for digests.

### 6.7 Agent (Phase 2)

- **Loop (~150 lines, `app/agent/loop.py`):**
  1. Assemble the context: system prompt, the profile block, the last 6 turns, and the tool schemas.
  2. Call the model.
  3. Validate each tool call's arguments with Pydantic. Run it. Return validation or runtime errors to the model as tool results so it can correct itself.
  4. Repeat up to **4 model calls per turn**, then return the final answer.
- **Tools:** thin wrappers over the same service functions the REST API uses.
  - `search_jobs(query?, filters)`, `get_job(id)`, `compare_jobs(ids ≤ 3)`, `explain_match(id)`, `show_saved()`
  - `record_feedback(id, kind)`, `update_profile(ops)`
  - Tool results are compact: ≤ 5 jobs, each about 100 tokens (id, title, company, location, score, 3 factors).
- **Memory, Letta-style core block:**
  - The structured profile is always in context, rendered at ≤ 300 tokens.
  - It changes **only** through `update_profile`, which takes `set/add/remove` ops on a whitelist of fields with size limits. Memory is therefore auditable rows, not a growing transcript.
  - Chat messages persist in Postgres. Only the last 6 turns go into context.
- **Routing:**
  - Rule-matched simple intents ("show my saved jobs", "why job 42?") call the tool directly with no LLM planning.
  - Short single-tool requests go to **gpt-oss-20b**. Everything else goes to **gpt-oss-120b**.
  - The two models have separate Groq quotas, so routing roughly doubles capacity.
- **Token budget (fits 8K TPM):** system ≤ 700 tokens, profile ≤ 300, history ≤ 1,500, tool schemas ≤ 800, tool results ≤ 700. That's about 4K per call.
  - A token bucket per model honours RPM/TPM limits.
  - Per-user cap of 30 turns/day.
  - When a quota is exhausted, the reply says so plainly and offers the search UI. Nothing fails silently.
- **Fallbacks:** Groq 120b, then Groq 20b, then a "search only" degraded mode. Gemini isn't used for chat (free Flash RPD is too low, and it may train on user text).
- **Résumé intake:** the user pastes text or uploads a PDF. Profile fields are extracted via Groq structured output and shown for confirmation. **The raw résumé is not stored.**
- **Borrowed from:** mini-swe-agent (a ~100-line agent class as the whole core), adapted from bash-only to native tool calling; Letta/MemGPT (core memory blocks edited only through memory tools, with size limits); AdaptJobRec (simple requests go straight to a tool, complex ones through the planner); observable-job-agent (you control location and remote, the model picks search arguments, bounded retries).

### 6.8 Delivery

- **Web app (Vite + React + TypeScript, static on Cloudflare Pages):**
  - **Feed:** ranked list, a "why" panel, Save/Not for me.
  - **Saved**
  - **Chat** (Phase 2)
  - **Profile:** edit fields, paste résumé.
  - It shows a "waking the server…" state while the Render instance cold-starts (it polls `/api/v1/health`).
  - **One origin:** a Cloudflare Pages Function at `functions/api/[[path]].ts` proxies `/api/*` to Render. The browser then sees one site, as with TicketLoop's dev proxy. That keeps the httpOnly refresh cookie first-party (cross-site cookies are blocked by Safari and others) and removes CORS. Pages Functions share the Workers free quota of 100k requests/day, which is far above this app's needs.
- **Weekly digest (Mondays 09:00 IST = 03:30 UTC cron, Actions):** for each opted-in user, top 5 **new since last digest** in feed mode, sent via the Brevo HTTP API with signed feedback links. A `digest_runs` row guards against double-sends within 24 hours (from JobGraph).

### 6.9 Identity and privacy

- Reuse TicketLoop's identity module: Argon2id, 15-minute JWT access tokens, rotating 7-day refresh tokens with reuse detection, and password reset by email.
- **Signup needs an invite code** (batch-only at first), created with `cli invite create --count N`. This protects free LLM quotas and can be opened later. Password-reset email goes through the Brevo HTTP API.
- Privacy rules:
  - User text goes only to Groq (listed as not training on API data; confirm in their terms before launch).
  - Only public posting text goes to Gemini's free tier.
  - No raw résumé storage.
  - `DELETE /users/me` cascades everything.

### 6.10 Tracing and operations

- **`spans` table:** trace_id, parent_id, kind (llm/tool/sql/http), name, model, tokens_in, tokens_out, latency_ms, status, error. Written by a context manager around LLM and tool calls. Queryable with SQL. No paid observability service.
- **`/status`:** last ingest run, open/relevant counts, failing boards, today's LLM usage against quotas.
- **Alerts:** GitHub Actions failure emails (built in).

## 7. Evaluation plan

All eval data lives in `evals/`. Every report in `docs/evaluation/` is produced by one documented command from a **frozen corpus snapshot** (`evals/data/corpus-<date>.jsonl.gz`: postings + features + embeddings), loadable into local Docker Postgres. The live index changing can't change the reported numbers. Small-sample results are reported with bootstrap 95% CIs.

### 7.1 Extraction
- 40 postings, stratified across the three ATSs, labelled by hand.
- Metrics: per-field accuracy, and skill P/R/F1 against canonical IDs.
- Variants: rules-only vs rules+LLM, plus calls per posting.

### 7.2 Ranking
- **Profiles:** 15 profiles. At least 5 are real classmates with consent; the rest are synthetic personas typical of the batch (SDE intern, ML intern, data intern, backend new grad…).
- **Queries:** each profile gets feed mode plus 2 free-text queries, about 45 queries in total.
- **Labels:** pool the top 20 from every variant (deduped) and label each 0/1/2. A classmate double-labels 10% so agreement can be reported.
- **Variants:** full-text only, dense only, hybrid RRF, hybrid + utility, + personal.
- **Metrics:** nDCG@10, Recall@20, MRR, computed and compared with **ranx** (paired significance tests built in).
- **Personal term:** per profile, use 3 relevant items as "saved" and 3 non-relevant as "dismissed" for training. Evaluate on the remaining labels.
- **Ablations:** cross-encoder rerank on top 30 (offline only), and the asymmetric encoder (stretch).
- **Tuning:** grid search on the weights in `ranking.yaml`. Report tuned vs initial weights and keep a held-out split.

### 7.3 Agent (τ-bench style)
- **Scenarios:** 30 YAML scenarios, each with a persona, a hidden goal (e.g. "remote backend internship, not Bengaluru, no fintech, wants Python") and success checks.
- **Setup:** a simulated user (gpt-oss-20b) talks to the agent (gpt-oss-120b) against the frozen corpus.
- **Deterministic graders, no LLM judge:**
  - Were the right tools called with the right filters (e.g. `remote=true`, the city excluded)?
  - Does the final profile state match the goal?
  - Does every recommended job satisfy the hard constraints?
  - Did the agent avoid unrequested actions?
- **Metrics:** task success, pass^3 (succeeds in all 3 trials), tool-argument accuracy, turns per task, p50/p95 turn latency, tokens per task.
- **Failure labels:** τ-bench's fault types (partial goal, wrong tool, wrong tool argument, unintended action).
- **Budget and cadence:** about 30 × 3 × ~8 calls fits the per-model daily quotas but runs for hours at 8K TPM. It runs on `workflow_dispatch` (manual or weekly), not per commit.
- **CI gate (every push):** recorded model responses (cassettes) replayed with no network. Checks tool-call parsing, loop termination, budget enforcement and the graders themselves. From observable-job-agent's deterministic gates.

### 7.4 Online (real users)
- Save-rate@5 and dismiss-rate per digest, weekly active users, time to first save.
- Reported in the README once there are at least 3 digest cycles.

## 8. Deployment ($0)

| Piece | Where | Notes |
|---|---|---|
| Postgres + pgvector | Neon Free, `aws-ap-southeast-1` (Singapore) | Pooled connection string for the API, direct for migrations |
| API (FastAPI, Docker) | Render Free web service, Singapore | `render.yaml`. Migrations run as a pre-deploy step or from Actions. |
| Batch jobs | GitHub Actions | `ingest.yml` (every 6h), `digest.yml` (weekly), `eval.yml` (manual), `ci.yml` (push) |
| Frontend | Cloudflare Pages | Builds from `frontend/`. A Pages Function proxies `/api/*` to Render (same origin). |
| LLMs | Groq free (chat), Gemini free (extraction) | Keys in Render env vars and Actions secrets |
| Email | Brevo free, HTTP API | A dedicated sender address, verified in Brevo |

Neon note: the API uses Neon's pooled connection string, which runs PgBouncer in transaction mode. psycopg's automatic prepared statements must therefore be off (`prepare_threshold=None`). Migrations use the direct connection string.
| Local dev | Docker Compose with `pgvector/pgvector` | Same as TicketLoop's workflow |

The 60-day auto-disable of scheduled workflows is avoided by normal development activity. After that, a weekly `index-stats.json` commit from the ingest job keeps the repo active. The builder may choose this or a manual re-enable.

## 9. Repository layout

```
Shortlist/
├─ backend/
│  ├─ app/
│  │  ├─ core/            # settings, logging, errors, db (reused from TicketLoop)
│  │  ├─ identity/        # reused from TicketLoop + invites
│  │  ├─ ingest/          # ats clients, normaliser, lifecycle, runs
│  │  ├─ extract/         # rules, llm batch extractor, taxonomy
│  │  ├─ embed/           # fastembed wrapper
│  │  ├─ search/          # SQL builder, ranking config, explanations
│  │  ├─ feedback/        # interactions, taste vector, signed links
│  │  ├─ agent/           # loop, tools, router, budgets, memory
│  │  ├─ digest/          # selection, render, send
│  │  ├─ llm/             # provider clients + fallback (from Engram)
│  │  ├─ tracing/         # spans
│  │  ├─ api/             # routers
│  │  └─ cli.py           # ingest | extract | embed | digest | check-boards | eval-*
│  ├─ migrations/
│  └─ tests/              # unit + integration (real Postgres) + cassettes
├─ frontend/              # Vite + React + TS
├─ evals/                 # labelled data, scenarios, snapshot loader, runners
├─ sources/boards.yaml
├─ taxonomy/              # O*NET extract + aliases.yaml
├─ config/ranking.yaml
├─ docs/                  # specs, plans, decisions (ADRs), evaluation reports
├─ .github/workflows/
├─ docker-compose.yml
└─ render.yaml
```

## 10. Build order (one phase at a time)

**Phase 0: early checks (½ day, blocking).** Record the results in `docs/phase-0-early-checks.md`.
1. fastembed bge-small memory and latency at 512 MB / 0.1 CPU.
2. Fetch 10 boards per ATS and save sample payloads as test fixtures.
3. Gemini Flash-Lite strict-JSON batch extraction on 10 postings.
4. Groq gpt-oss-120b tool-calling round trip.
5. Confirm current free-tier limits in each console.

**Phase 1: Feed.**
1. Skeleton (reuse TicketLoop core)
2. Schema and migrations
3. Ingest and lifecycle
4. Rules extraction and taxonomy
5. LLM extraction
6. Embeddings
7. Search and ranking API
8. Feedback and taste vector
9. Web app (Feed/Saved/Profile)
10. Identity and invites
11. Deploy (Neon, Render, Pages, Actions)
12. Digest
13. Extraction and ranking evals
14. README with numbers

**Phase 2: Agent.**
1. Tools over services
2. Loop, budgets and fallback
3. Memory and the `update_profile` tool
4. Router
5. Chat UI
6. Spans
7. Agent eval harness and CI cassettes
8. README update

**Phase 3: stretch, only after Phases 1 and 2.**
- Weight tuning from real feedback
- Cross-encoder ablation
- Asymmetric encoder experiment
- Telegram delivery

## 11. Decided vs left to the builder

**Decided:** everything in §4, the free-tier stack in §8, Postgres-only storage, write-time extraction, one-SQL ranking with the explained utility, the hand-written agent loop with memory through tools, the three eval levels with frozen snapshots, and no copied third-party code.

**Calls made while writing this, open to correction:**
1. Users are the 2027 batch, with invite-code signup.
2. Target roles are software, ML/AI and data; intern/new-grad/entry level; India or remote-for-India.
3. The repo is public (needed for free Actions minutes, and Elip will look at it).
4. The digest goes out weekly on Monday 09:00 IST by email through Brevo. Telegram is deferred.
4a. The frontend reaches the API through a Pages Function proxy, so everything is same-origin.
4b. Vector search is exact (no ANN index) until the relevant set passes about 20k rows.
5. bge-small via fastembed in both places, with Gemini embeddings as the documented fallback.
6. Initial ranking weights as in §6.5, tuned later.
7. Postgres built-in full-text search rather than a BM25 extension, so local and cloud behave the same.
8. A closed posting needs 2 consecutive misses; text is purged after 30 days.
9. Agent limits: 4 model calls per turn and 30 turns per user per day.
10. Ranking labels: 15 profiles (≥ 5 real with consent).

**Left to the builder:**
- Exact prompts
- UI styling
- Whether chat streams over SSE
- The exact board list (must be validated by `check-boards`)
- The keep-active mechanism for scheduled workflows
- Retry and backoff constants
- Test layout beyond "integration tests use real Postgres"

## 12. Risks and fallbacks

| Risk | Fallback |
|---|---|
| A free tier changes (Hugging Face restricted free CPU Spaces in mid-2026) | Each provider sits behind an interface. Documented swaps: Render→Koyeb, Neon→Supabase, Gemini→Groq 20b, Groq→OpenRouter. |
| fastembed doesn't fit in 512 MB | Gemini embeddings on both sides, re-embed in one Actions run |
| Render cold start (~1 min) | Frontend waking state; digest links tolerate the delay |
| Quotas exhausted under load | Router to 20b, token buckets, per-user caps, clear "busy" message, search-only mode |
| ATS slugs change or boards vanish | `board_runs` failure counter, auto-disable, `check-boards` |
| Small labelled sets over-claim | Bootstrap CIs, sample sizes stated next to every number |

## Sources and inspiration (ideas only)

- Compass: https://github.com/akminx/compass
- JobGraph: https://github.com/luisvid/JobGraph
- observable-job-agent: https://github.com/jamwithai/observable-job-agent
- JobMatchAI (ACL 2026 demo): https://arxiv.org/abs/2603.14558
- AdaptJobRec (Walmart): https://arxiv.org/abs/2508.13423
- τ-bench / τ³-bench: https://github.com/sierra-research/tau2-bench
- mini-swe-agent: https://github.com/SWE-agent/mini-swe-agent
- Letta memory blocks: https://docs.letta.com/guides/agents/memory-blocks
- Hybrid search with RRF in Postgres: https://supabase.com/docs/guides/ai/hybrid-search
- fastembed: https://github.com/qdrant/fastembed
- ranx: https://github.com/AmenRa/ranx
- O*NET database: https://www.onetcenter.org/database.html
- Free tiers: Neon https://neon.com/docs/introduction/plans · Render https://render.com/docs/free (SMTP block: https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports) · Groq https://console.groq.com/docs/rate-limits · Gemini https://ai.google.dev/gemini-api/docs/rate-limits · Cloudflare Pages https://developers.cloudflare.com/pages/functions/pricing/ · Brevo https://www.brevo.com/features/email-api/
- Aswin's own: Engram, TicketLoop, Delta (reused code and patterns)
