# Phase 7 run recipe — driving the whole stack against live infrastructure

**Written by:** Story W4 (AC4) · **For:** the Phase 7 acceptance run
**Why this exists:** Phase 7 is a browser run performed by a person. It should not require
rediscovering how to start the stack — and three separate stale-process incidents during Phase 6
cost more debugging time than the code did.

---

## Before you start — the failure that wasted the most time

**Check nothing stale is already listening.** During Phase 6 a stale `uvicorn` served **3** book
routes while the source had **4**, and the check written to catch it used
`netstat | grep "LISTENING.*:8077"` — which can never match Windows `netstat` column order, so it
reported "free" unconditionally. Two stale ARQ workers running pre-Story-1-13 code separately
failed every lesson within seconds and produced three false gate failures.

```bash
# Correct on Windows — the port precedes LISTENING in the output
netstat -ano | grep -E ":8077[[:space:]]" | grep LISTENING
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'arq|uvicorn' } | ForEach-Object { '{0} | {1}' -f \$_.ProcessId, \$_.CommandLine }"
```

Kill anything left over before starting. Then, after the API is up, **verify the running code is
the code you think it is** — `app.routes` does NOT work on this FastAPI version (module routes are
`_IncludedRouter` branches with no `.path`):

```bash
python -c "import requests,json; d=requests.get('http://127.0.0.1:8077/openapi.json').json(); \
print([p for p in d['paths'] if 'book' in p])"
# Expect FOUR: /books, /books/{book_id}, /books/{book_id}/chapters,
#              /books/{book_id}/chapters/{chapter_id}/lessons
```

---

## 1. Backend API

From `apps/api`, with the gate env. Two variables must be exported **after** sourcing, because
bash strips the quotes from the JSON-array value and pydantic-settings then rejects it:

```bash
set -a && . /path/to/gate.env && set +a
export CORS_ORIGINS='["http://localhost:3000"]'   # bash eats the inner quotes otherwise
export REDIS_URL='redis://127.0.0.1:56379'        # .env's localhost:6379 has nothing on it
export SUPABASE_JWT_SECRET="<the HS256 secret the gate tokens are signed with>"
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8077
```

## 2. Worker

**This is where money is spent.** The full worker runs `content_pipeline_job` and will call
OpenAI, TTS and image providers.

```bash
./.venv/Scripts/python.exe -m arq app.workers.main.WorkerSettings
```

For an **ingest-only, zero-cost** run — books are detected, lessons stay `generating` — subclass
`WorkerSettings` with `functions = [book_ingest_job]` only. That is how Phase 6's gate observed
real ingestion and the real chapter-card and idempotency behaviour without paying.

## 3. Frontend

```bash
cd apps/web
NEXT_PUBLIC_API_URL=http://127.0.0.1:8077/api pnpm dev
```

**The `/api` suffix is load-bearing** — `lib/api.ts:4` includes it and every service uses relative
paths without a leading slash. Setting it without `/api` 404s every call and looks like a backend
outage. That is **D57**.

Supabase auth vars must match the project the API is pointed at, or the JWT the browser sends will
not verify.

## 4. What to drive

Per the tracker's Phase 7 acceptance list:

1. Upload a real 1,000+ page textbook through the UI
2. Chapters appear — Phase 6 measured **1,151 pages → 21 chapters in 90.3 s**
3. List them at `/books/{id}`
4. Generate **two different chapters at two different tiers**
5. Both produce schema-valid packages with **no truncation warning**
6. Play both in the player; take both quizzes
7. Full suite + `ruff` + `mypy`, **repo-wide** (binding rule 1)
8. Mutation check: change `chapter_index` back to a constant → a test **must** fail

Chapters over ~40 pages will legitimately return `truncation_expected: true` — that is **D46**,
not a failure. Step 5's "no truncation warning" means picking chapters under that span; the
corpus book's chapters run 10–98 pages, so choose deliberately and record which.

## 5. What this run discharges

One run, five outstanding verifications:

| | |
|---|---|
| Story 1-13 AC10 | the eleven nodes produce a package from ~40 pages (**D43**) |
| Phase 5 | Implemented → Verified |
| Phase 6 | its own exit items 3–4, "lesson generates" |
| Phase 6.5 | AC10 — a real socket on a real session receives `lesson_ready` |
| Track W (W0–W4) | every W exit criterion is browser-driven |

**If it fails, all five stay unverified.** They were carried forward together on the D43
exception; they are discharged together or not at all.
