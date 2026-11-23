# Shortlist

A live, personalised feed of internships and entry-level roles for the IIIT Kottayam 2027 batch,
built from public company job boards and run entirely on free tiers.

Work in progress. See `docs/superpowers/specs/2026-11-23-shortlist-design.md` for the design.

## Deploy for $0

Everything runs on free tiers. Nothing here needs a card.

| Piece | Where | Free-tier limit that matters |
|---|---|---|
| Postgres + pgvector | Neon, project `shortlist`, region `aws-ap-southeast-1` | 0.5 GB storage; compute sleeps when idle |
| API (FastAPI) | Render web service from `render.yaml` (Docker, Singapore) | 512 MB, 0.1 CPU, sleeps after 15 idle minutes |
| Web app | Cloudflare Pages, root `frontend`, build `npm run build`, output `dist` | none that bite |
| `/api/*` proxy | Pages Function `frontend/functions/api/[[path]].ts` | retries GETs for ~63 s while Render wakes |
| Pipeline, every 6 h | GitHub Actions `pipeline.yml` | free on public repos |
| Weekly digest, Mon 09:00 IST | GitHub Actions `digest.yml` | |
| Email | Brevo HTTP API (Render blocks SMTP) | 300 emails a day |
| LLMs | Gemini Flash-Lite and Groq | daily request caps; extraction falls back to rules |

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
   (the Pages URL from step 4). The container migrates the database on every start.
4. **Cloudflare Pages.** Connect the repo. Root directory `frontend`, build command
   `npm run build`, output `dist`, environment variable `API_ORIGIN=https://<service>.onrender.com`.
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

### Operations

- **Invite students:** `uv run python -m app.cli invite-create --count 10`, then share
  `https://<pages-domain>/register?invite=<code>`.
- **Health:** `GET /api/v1/status` shows the last ingest, failing boards, LLM calls today,
  freshness, search latency and digest save rates.
- **A board keeps failing:** it is disabled after 5 failed runs in a row. Fix or remove it in
  `sources/boards.yaml`; `uv run python -m app.cli check-boards` probes every board.
- **Image check:** `docker build -f backend/Dockerfile -t shortlist-api .` from the repository
  root. CI builds it and runs it offline under 512 MB and 0.1 CPU.
