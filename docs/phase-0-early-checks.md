# Phase 0: early checks

Run on 2026-11-23. Each check either confirms a design decision or triggers its documented
fallback (spec §6.3, §12).

## 1. Does the query embedder fit Render Free? (provisionally yes)

`backend/scripts/checks/embed_memory.py`, BAAI/bge-small-en-v1.5 via fastembed (quantized ONNX).

| Where | Peak RSS | p50 query | p95 query |
|---|---:|---:|---:|
| Dev container, 2 cores | 357 MB | 13.2 ms | 17.0 ms |
| Dev container, pinned to 1 core | 298 MB | 12.6 ms | 14.8 ms |
| Container limited to 512 MB / 0.1 CPU (`checks.yml`) | pending | pending | pending |

The model and ONNX runtime alone take about 300 MB on one thread; the API process adds roughly
80–100 MB (FastAPI, SQLAlchemy, psycopg). That is about 400 MB, under the 420 MB pass mark but
without much headroom, so the API's embedder runs ONNX on **one thread** (`threads=1`), which
is also what a 0.1 CPU share can use. At 0.1 CPU a 13 ms query should take roughly 130 ms.

Decision: go with fastembed in the API, threads=1. The container-limited run in `checks.yml`
confirms or overturns this once the GitHub repo exists. Fallback if it fails: Gemini
embeddings on both sides (re-embed in one Actions run).

## 2. ATS samples (done)

`backend/scripts/checks/fetch_samples.py` saved 29 boards (first 5 postings each) under
`backend/tests/fixtures/ats/`:

- Greenhouse (10): cloudflare, coinbase, databricks, dropbox, druva, figma, gitlab, groww,
  robinhood, stripe
- Lever (9): brightedge, cred, jumpcloud, leverdemo, meesho, mindtickle, palantir, spotify, zeta
- Ashby (10): ashby, elevenlabs, linear, notion, openai, perplexity, posthog, ramp, replit,
  supabase

Several Indian companies tried under obvious slugs were not on these three ATSs (Razorpay,
PhonePe, Postman on Greenhouse; Swiggy, Upstox, Navi on Lever; Zepto on Ashby). Board
discovery (plan Task 7) probes slug variants for about 300 candidates instead of guessing.

## 3. Extraction models return strict JSON (pending keys)

`backend/scripts/checks/extract_check.py` sends 8 fixture postings to each of
`gemini:gemini-3.5-flash-lite` and `groq:openai/gpt-oss-20b` with a strict `json_schema`.
Runs in `checks.yml` once `GEMINI_API_KEY` and `GROQ_API_KEY` are repository secrets. The
model IDs in `Settings.extract_models` stay provisional until then.

## 4. Agent model calls a tool (pending keys)

`backend/scripts/checks/toolcall_check.py`: one `search_jobs` round trip on
`openai/gpt-oss-120b`. Input for the Phase 2 plan; nothing in Phase 1 depends on it.

## Free-tier limits

To be re-read in each console when the keys are created: Neon (1 GB / 100 CU-hours per
project), Render (512 MB, 0.1 CPU, 15-minute spin-down), Groq (gpt-oss: 30 RPM, 1K RPD, 8K
TPM, 200K TPD), Gemini Flash-Lite (~500 RPD), Brevo (300 emails/day).
