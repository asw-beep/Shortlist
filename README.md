# Shortlist

A live, personalised feed of internships and entry-level software, ML and data roles for the
IIIT Kottayam 2027 batch. Shortlist reads public company job boards every six hours, keeps the
postings a student in India can actually take, ranks them for each student with an explained
score, learns from saves and dismissals, and emails a weekly digest with one-click links.
Everything runs on free tiers.

Phase 1 (this repository today) is the feed. Phase 2 adds a tool-calling agent to refine a
search by chat.

## Screens

Every posting gets a match readout, and **Why** opens the six ranking factors as meters. Light
and dark follow the system setting. Captured from a local run with a demo account and real
postings from the public boards.

<p align="center">
  <img src="docs/media/feed.gif" width="880" alt="Searching the feed for python backend intern, opening Why on the top posting and saving it">
</p>

| Sign up with an invite | Set up a profile, then see the feed |
|---|---|
| <img src="docs/media/register.gif" alt="Creating an account with an invite code"> | <img src="docs/media/profile.gif" alt="Choosing roles, levels, skills and cities, saving the profile and opening the feed"> |
| **Saved postings** | **Forgot password, then log in (dark)** |
| <img src="docs/media/saved.gif" alt="Opening the saved list and removing a posting"> | <img src="docs/media/login.gif" alt="Requesting a reset link, logging in and opening Why on the first posting"> |

| Page | Light | Dark |
|---|---|---|
| Feed, with Why open | <img src="docs/media/feed-light.png" width="420" alt="Feed in light mode"> | <img src="docs/media/feed-dark.png" width="420" alt="Feed in dark mode"> |
| Saved | <img src="docs/media/saved-light.png" width="420" alt="Saved postings in light mode"> | <img src="docs/media/saved-dark.png" width="420" alt="Saved postings in dark mode"> |
| Profile | <img src="docs/media/profile-light.png" width="420" alt="Profile form in light mode"> | <img src="docs/media/profile-dark.png" width="420" alt="Profile form in dark mode"> |
| Log in | <img src="docs/media/login-light.png" width="420" alt="Log in in light mode"> | <img src="docs/media/login-dark.png" width="420" alt="Log in in dark mode"> |

<details>
<summary>The other pages</summary>

| Page | Light | Dark |
|---|---|---|
| Create account | <img src="docs/media/register-light.png" width="420" alt="Create account in light mode"> | <img src="docs/media/register-dark.png" width="420" alt="Create account in dark mode"> |
| Forgot password | <img src="docs/media/forgot-password-light.png" width="420" alt="Forgot password in light mode"> | <img src="docs/media/forgot-password-dark.png" width="420" alt="Forgot password in dark mode"> |
| New password (from the emailed link) | <img src="docs/media/reset-password-light.png" width="420" alt="New password in light mode"> | <img src="docs/media/reset-password-dark.png" width="420" alt="New password in dark mode"> |
| Thanks (digest one-click links) | <img src="docs/media/thanks-light.png" width="420" alt="Thanks page in light mode"> | <img src="docs/media/thanks-dark.png" width="420" alt="Thanks page in dark mode"> |
| Waking the server | <img src="docs/media/waking-light.png" width="420" alt="Waking the server in light mode"> | <img src="docs/media/waking-dark.png" width="420" alt="Waking the server in dark mode"> |
| Can't reach Shortlist | <img src="docs/media/unavailable-light.png" width="420" alt="Can't reach Shortlist in light mode"> | <img src="docs/media/unavailable-dark.png" width="420" alt="Can't reach Shortlist in dark mode"> |
| Not found | <img src="docs/media/not-found-light.png" width="420" alt="Not found in light mode"> | <img src="docs/media/not-found-dark.png" width="420" alt="Not found in dark mode"> |

</details>

## How it works

```
        every 6 h (GitHub Actions)                      Mondays (GitHub Actions)
 ┌──────────────────────────────────────────┐     ┌──────────────────────────────┐
 │ ingest → filter → extract → embed        │     │ digest: top 5 new per student │
 │ Greenhouse / Lever / Ashby public APIs   │     │ Brevo HTTP API, signed links  │
 └──────────────────┬───────────────────────┘     └───────────────┬──────────────┘
                    │ writes                                       │ reads
                    ▼                                              ▼
      ┌──────────────────────────────────────────────────────────────────────┐
      │ Neon Postgres + pgvector: postings · features · skills · vectors ·   │
      │ full-text · users · profiles · interactions · digest runs · spans    │
      └──────────────────────────────▲───────────────────────────────────────┘
                                     │ one SQL round trip per search
                       ┌─────────────┴────────────┐
                       │ FastAPI on Render         │──── Groq: résumé → profile draft
                       │ feed · feedback · profile │
                       │ auth · status             │
                       └─────────────▲────────────┘
                                     │ /api/* proxied, same origin (no CORS)
                       ┌─────────────┴────────────┐
                       │ React (Vite) on Cloudflare│  Feed · Saved · Profile
                       │ Worker + static assets    │  (waits while Render wakes)
                       └──────────────────────────┘
```

- **Ingest:** 127 curated boards (`sources/boards.yaml`); a posting missing from two runs in a
  row closes; boards that fail 5 runs in a row are disabled.
- **Filter, then extract:** fast rules decide relevance (India or India-open remote; software,
  ML or data; at most 3 years asked) and only relevant postings go to an LLM (Gemini
  Flash-Lite, then Groq, then rules alone) for strict-JSON requirements. Skills map to a
  156-entry taxonomy built from O*NET.
- **Embed:** `BAAI/bge-small-en-v1.5` (384-d) via fastembed, locally, at write time.
- **Search:** one SQL statement: hard filters, dense and keyword retrieval fused with
  reciprocal-rank fusion, then six explained factors (skills, relevance, experience, location,
  recency, personal taste) weighted from `config/ranking.yaml`. No LLM on the request path.
- **Personalisation:** each save or dismissal updates a Rocchio taste vector
  (mean(saved) − 0.5·mean(dismissed)), ramped in over the first 10 signals.

## Numbers so far

Measured on the first real ingest (local, rules-only extraction, 24 Nov 2026):

| | |
|---|---|
| Boards / postings ingested | 127 / 13,804 |
| Relevant to this batch after filtering | 171 (1.2%) |
| Feed search, warm (embed the query + one SQL statement) | 32–90 ms |
| API container at Render Free limits (512 MB, 0.1 CPU) | 334 MB peak at boot, 278 MiB after a feed |

**Offline evaluation** — extraction accuracy and skill P/R/F1 on 40 hand-labelled postings, and
nDCG@10 / Recall@20 / MRR for five ranking variants on 45 judged queries — runs on a frozen
snapshot with bootstrap CIs and paired t-tests (`backend/evals/README.md`). The labelling has not
been done yet; results will appear in `docs/evaluation/` with n, intervals and the exact command.

## The $0 stack

| Piece | Where | Free-tier limit that matters |
|---|---|---|
| Postgres + pgvector | Neon, region `aws-ap-southeast-1` | 0.5 GB storage; compute sleeps when idle |
| API (FastAPI) | Render web service from `render.yaml` (Docker, Singapore) | 512 MB, 0.1 CPU, sleeps after 15 idle minutes |
| Web app | Cloudflare Worker with static assets (`frontend/wrangler.json`), root `frontend`, build `npm run build` | none that bite |
| `/api/*` proxy | `frontend/worker/index.ts` → `frontend/functions/api/[[path]].ts` (also works as a Pages Function) | retries GETs for ~63 s while Render wakes |
| Pipeline, every 6 h | GitHub Actions `pipeline.yml` | free on public repos |
| Weekly digest, Mon 09:00 IST | GitHub Actions `digest.yml` | |
| Email | Brevo HTTP API (Render blocks SMTP) | 300 emails a day |
| LLMs | Gemini Flash-Lite and Groq | daily request caps; extraction falls back to rules |

## Run it locally

Needs Docker, [uv](https://docs.astral.sh/uv/) and Node 22+.

```bash
docker compose up -d db                     # Postgres 17 + pgvector on localhost:5432

cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.cli seed-skills
uv run python -m app.cli pipeline           # ingest all boards, extract, embed (a few minutes)
uv run python -m app.cli invite-create      # prints an invite code
uv run uvicorn app.main:app --reload        # API on :8000

cd ../frontend                              # in a second terminal
npm ci
npm run dev                                 # app on :5173, /api proxied to :8000
```

Open `http://localhost:5173/register?invite=<code>`. Without `GEMINI_API_KEY` / `GROQ_API_KEY`
in the environment, extraction uses rules alone and the résumé import is unavailable;
everything else works.

Tests: `cd backend && uv run pytest` (integration tests need the database; set
`REQUIRE_POSTGRES=1` to fail rather than skip without it) and `cd frontend && npm test`.

## Deploy for $0

### One-time setup

1. **Neon.** Create project `shortlist` in `aws-ap-southeast-1`. Copy two connection strings and
   change the scheme to `postgresql+psycopg://`: the **pooled** one (host contains `-pooler`) and
   the **direct** one.
2. **Keys.** Groq, Gemini (AI Studio) and Brevo API keys. In Brevo, verify the sender address.
   Generate two secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`: one
   for `JWT_SECRET_KEY`, one for `FEEDBACK_LINK_SECRET`.
3. **Render.** New → Blueprint → this repo. Fill in the `sync: false` variables:
   `DATABASE_URL` (pooled), `DIRECT_DATABASE_URL` (direct), `JWT_SECRET_KEY`,
   `FEEDBACK_LINK_SECRET`, `GROQ_API_KEY`, `BREVO_API_KEY`, `EMAIL_FROM_ADDRESS`, `FRONTEND_URL`
   (the Cloudflare URL from step 4). The container migrates the database on every start.
4. **Cloudflare.** Workers & Pages → Create → import the repo as a Worker named `shortlist`.
   Root directory `frontend`, build command `npm run build`, deploy command
   `npx wrangler deploy`. `frontend/wrangler.json` serves `dist/` with an index.html fallback,
   runs the Worker for `/api/*`, and sets `API_ORIGIN` (edit it to your Render URL).
5. **GitHub secrets** (Settings → Secrets → Actions): `DATABASE_URL` (the **direct** URL; batch
   jobs run long), `GEMINI_API_KEY`, `GROQ_API_KEY`, `BREVO_API_KEY`, `FEEDBACK_LINK_SECRET` (the
   same value as on Render, or digest links fail), `JWT_SECRET_KEY`, `EMAIL_FROM_ADDRESS`,
   `FRONTEND_URL`.

### First production run

```bash
# Actions → Pipeline → Run workflow. Then:
curl https://<pages-domain>/api/v1/status        # boards_ok >= 100, relevant_postings > 0
cd backend
uv run python -m app.cli invite-create --count 1 # with DATABASE_URL pointing at Neon
uv run python -m scripts.smoke --base-url https://<pages-domain> --invite <code>   # exit 0
```

The smoke script registers a throwaway account, saves a profile, loads the feed and the status
page, then deletes the account. It spends one invite.

## Operations

- **Health:** `GET /api/v1/status` shows the last ingest, failing boards, LLM calls today,
  freshness (first seen → searchable, p50), search latency p50/p95 and weekly digest save and
  dismiss rates. When a scheduled run fails, GitHub emails whoever last edited that workflow's
  schedule.
- **Invite students:** `uv run python -m app.cli invite-create --count 10`, then share
  `https://<pages-domain>/register?invite=<code>`.
- **A board keeps failing:** it is disabled after 5 failed runs in a row. Fix or remove it in
  `sources/boards.yaml`; `uv run python -m app.cli check-boards` probes every board.
- **Scheduled workflows stop after 60 days without commits.** GitHub disables cron workflows
  in inactive public repositories; re-enable Pipeline and Digest under Actions → the workflow
  → "Enable workflow".
- **Rotating keys:**
  - LLM and Brevo keys: replace them on Render and in GitHub secrets; nothing else changes.
  - `JWT_SECRET_KEY` (Render): everyone is logged out once.
  - `FEEDBACK_LINK_SECRET`: change it on Render and in GitHub together; links in digests
    already sent stop working.
  - Neon password: update both connection strings on Render and in GitHub.
- **Image check:** `docker build -f backend/Dockerfile -t shortlist-api .` from the repository
  root. CI builds it and runs it offline under 512 MB and 0.1 CPU.

## Privacy

- **Public posting text** goes to Gemini (and Groq as a fallback) for extraction.
- **A résumé** is sent to Groq once to draft a profile, then discarded: it is never saved, in
  the database or in any file that outlives the request. Only the profile the student saves is
  kept.
- **Email addresses** go to Brevo, only to send the digest a student opted into and password
  emails.
- **Fonts** (Geist, Geist Mono, Doto) load from Google Fonts, so a browser opening the web app
  also requests them from Google's servers. No account data is sent with them.
- **Feed impressions, saves, dismissals and clicks** are stored to rank postings and to measure
  the ranking; they are never shared.
- **Deleting an account** (Profile → Delete account, or `DELETE /api/v1/users/me`) removes the
  profile, interactions, digest history and tokens with it.
- Signup is invite-only, which also protects the free LLM quotas.

## Attribution

The skill taxonomy is derived from the O*NET® 30.2 Database by the U.S. Department of Labor,
Employment and Training Administration (USDOL/ETA), used under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Shortlist has modified the
information; USDOL/ETA has not approved, endorsed or tested these modifications. Details in
`taxonomy/README.md`.

## Inspiration (ideas only, no code copied)

- [Compass](https://github.com/akminx/compass), [JobGraph](https://github.com/luisvid/JobGraph)
  and [observable-job-agent](https://github.com/jamwithai/observable-job-agent): job-search
  agents and their observability
- [JobMatchAI](https://arxiv.org/abs/2603.14558) and
  [AdaptJobRec](https://arxiv.org/abs/2508.13423): explained job matching and recommendation
- [τ-bench](https://github.com/sierra-research/tau2-bench),
  [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) and
  [Letta memory blocks](https://docs.letta.com/guides/agents/memory-blocks): the Phase 2 agent
  and its evaluation
- [Hybrid search with RRF in Postgres](https://supabase.com/docs/guides/ai/hybrid-search),
  [fastembed](https://github.com/qdrant/fastembed) and [ranx](https://github.com/AmenRa/ranx)
- Code and patterns reused from my own Engram, TicketLoop and Delta

Design: `docs/superpowers/specs/2026-11-23-shortlist-design.md`.
