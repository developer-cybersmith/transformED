# Backend Issues Found — Live End-to-End Testing (2026-07-13)

**Reported by:** Dev 2 (Dell)
**Context:** Testing Story 1-8 (Upload Flow — Real API Integration) required running the actual backend (`apps/api`) end-to-end for the first time — real Supabase project, real ARQ worker, real browser session — rather than relying on unit tests alone. Several issues surfaced that block the upload/onboarding flow from working correctly against the real stack. This document reports what was found, where, and who owns each area, per the ownership table in `CLAUDE.md` §21.

No fixes are described here — this is a findings report for review before any change is proposed.

---

## Summary

| # | Issue | File | Owner (CLAUDE.md §21) | Severity |
|---|-------|------|------------------------|----------|
| 1 | JWT verification rejects all real tokens | `apps/api/app/dependencies.py` | Dev 4 — JWT middleware | Critical — blocks every authenticated endpoint |
| 2 | Learner DNA endpoint crashes for new users | `apps/api/app/modules/assessment/service.py` | Dev 3 — Learner DNA | High — 500 instead of 404 for the expected "not onboarded yet" case |
| 3 | Lesson status never reaches the polling API | `apps/api/app/workers/jobs/content_pipeline.py` | Dev 1 — content pipeline | Critical — no lesson (success or failure) can ever be reported as done |
| 4 | Image upload instability during extraction | `apps/api/app/modules/content/pipeline/graph.py` (`extract_node`) | Dev 1 — content pipeline | Medium — unclear if self-healing; needs investigation |

Plus two environment/process notes below that blocked full testing but aren't code bugs.

---

## 1. JWT verification rejects all real tokens (Critical)

**File:** `apps/api/app/dependencies.py`, `get_current_user()`
**Owner:** Dev 4 (JWT middleware)

**Observed:** Every API call carrying a real, valid Supabase session token returns `401 Unauthorized`, including the very first authenticated request after a normal sign-in.

**Root cause:** `get_current_user()` verifies the token like this:

```python
payload: dict[str, Any] = jwt.decode(
    token,
    settings.supabase_jwt_secret,
    algorithms=["HS256"],
    audience="authenticated",
    options={"require": ["sub", "exp", "iat"]},
)
```

This assumes the project uses the legacy shared-secret (HS256) signing scheme. Checking this project's live JWKS endpoint directly:

```
GET https://kxhgvwopdszclfyrrkqm.supabase.co/auth/v1/.well-known/jwks.json
→ {"keys":[{"alg":"ES256","kty":"EC", ...}]}
```

This project signs tokens with **ES256** (asymmetric key), not HS256. `jwt.decode(..., algorithms=["HS256"])` rejects every such token as an invalid algorithm/signature. There is no JWKS handling anywhere in `apps/api` (confirmed via repo-wide search).

**Impact:** Every authenticated endpoint across every module (`content`, `assessment`, `tutor`, `admin`, etc.) 401s for any real user session. This is not specific to one route — it affects the entire authenticated surface of the API.

**Related:** `apps/api/pyproject.toml` declares `PyJWT>=2.8.0` without the `crypto` extra. ES256 verification requires the `cryptography` package; it's only present in the current environment transitively (pulled in by another dependency), so a fresh install elsewhere would fail differently even if the algorithm logic were corrected.

---

## 2. Learner DNA endpoint crashes for new users (High)

**File:** `apps/api/app/modules/assessment/service.py`, `get_learner_dna_data()`
**Owner:** Dev 3 (Learner DNA)

**Observed:** `GET /api/assessment/user/dna` returns `500 Internal Server Error` for a user who hasn't completed onboarding yet — i.e., the exact case this endpoint's own docstring says it should handle with a clean 404.

**Root cause:**

```python
resp = await asyncio.to_thread(
    lambda: supabase.table("learner_dna")
    .select("user_id, badge_labels, profile_text, session_count, last_updated")
    .eq("user_id", user_id)
    .maybe_single()
    .execute()
)
if resp.data is None:
    raise HTTPException(status_code=404, ...)
row = resp.data
```

When zero rows match, this version of the Supabase Python client's `.maybe_single().execute()` returns `None` directly — not a response object with `.data = None`. So `resp` itself is `None`, and `resp.data` raises `AttributeError: 'NoneType' object has no attribute 'data'` instead of reaching the intended 404 branch.

**Evidence (server log):**
```
File ".../app/modules/assessment/service.py", line 861, in get_learner_dna_data
    if resp.data is None:
       ^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'data'
```

**Impact:** Any client checking onboarding status for a brand-new user (exactly what the onboarding flow does on mount) gets a 500 instead of the expected 404, which several call sites specifically branch on.

---

## 3. Lesson status never reaches the polling API (Critical)

**File:** `apps/api/app/workers/jobs/content_pipeline.py`
**Owner:** Dev 1 (content pipeline)

**Observed:** After uploading a PDF and letting the pipeline run to completion (success or failure), `GET /api/content/lessons/{id}` keeps reporting `status: "running"` indefinitely. Querying the database directly confirms the real state:

```
lessons table:      status = "generating"   (never changes)
lesson_jobs table:  status = "failed", error = "...", last_node = "chunk"
```

**Root cause:** `GET /api/content/lessons/{id}` (in `router.py`) reads its status from the **`lessons`** table, not `lesson_jobs`:

```python
lesson_resp = supabase.table("lessons").select("*").eq("lesson_id", lesson_id)...
```

But `content_pipeline_job` only ever writes to **`lesson_jobs`**:

```python
async def _update_lesson_status(supabase, lesson_id, status, error=None):
    """Update lesson_jobs.status (and optionally error) in Supabase."""
    try:
        payload = {"status": status}
        if error:
            payload["error"] = error[:2000]
        supabase.table("lesson_jobs").update(payload).eq("lesson_id", lesson_id).execute()
    except Exception:
        logger.warning(...)
```

This helper is called on every transition (`running` at start, `failed` on any exception/cancellation). The success path (a separate inline block) also only updates `lesson_jobs`:

```python
supabase.table("lesson_jobs").update({
    "status": "completed",
    "completed_at": ...,
}).eq("lesson_id", lesson_id).execute()
```

Nothing anywhere in this file ever writes to the `lessons` table after the initial upload-time insert (which sets `status = "generating"`).

**Impact:** This is not specific to any one failure mode — it means **no lesson can ever be reported as `ready` or `failed` to the client, under any circumstances**, success or failure. The polling contract the frontend depends on (`queued|running|ready|failed`) can structurally never return anything but the initial state via this endpoint. This blocks the entire upload → generation → lesson-ready flow for every user.

---

## 4. Image upload instability during extraction (Medium — needs investigation)

**File:** `apps/api/app/modules/content/pipeline/graph.py`, `extract_node`
**Owner:** Dev 1 (content pipeline)

**Observed:** During PDF extraction, uploading extracted page images to Supabase Storage fails repeatedly with connection-level errors, consistently across every test run and every image:

```
extract_node: image upload attempt 1/5 failed for <id>/p33_17.png: EOF occurred in violation of protocol (_ssl.c:2427)
extract_node: image upload attempt 2/5 failed for <id>/p33_17.png: Server disconnected
extract_node: image upload attempt 3/5 failed for <id>/p33_17.png: Server disconnected
```

This happened for every image, across three separate test lessons, not as an isolated blip.

**Root cause:** Not investigated further — flagging for the owning dev to assess whether this is a genuine concurrency/connection-handling issue in the upload path (e.g., too many simultaneous connections, connection pool exhaustion, missing keep-alive/retry-after handling) or environment-specific network behavior. The retry mechanism (5 attempts) appears to allow the pipeline to eventually proceed past this node in practice, but the underlying cause of the consistent first-attempt failures is unclear and worth a look.

**Impact:** Adds latency and log noise to every extraction run; unclear whether it could cause outright failure under different conditions (e.g., a slower network, more images, tighter timeouts).

---

## Environment / Process Notes (not code bugs — blocked full testing)

These aren't attributed to a specific dev's code, but are worth documenting since they blocked verifying the pipeline all the way to a successful `ready` state:

- **`OPENAI_API_KEY` is a placeholder** (`sk-dummy...`) in the local `.env`. `embed_node` (real OpenAI embeddings call, no fallback) and the onboarding profile-generation LLM call both fail with `401 Incorrect API key` as a result. A real key is needed to test the pipeline past the embedding stage.
- **The ARQ worker is a separate process from the API server.** Running `uvicorn app.main:app` alone enqueues jobs but never executes them — nothing consumes the queue without also running `python -m arq app.workers.main.WorkerSettings`. This isn't documented anywhere in the repo (no README describes local dev setup for `apps/api`), and it's easy to assume the API process handles jobs itself.

## Context (expected, not a bug)

Nodes 5–15 of the pipeline (`lesson_planner`, `slide_generator`, `summarise_segment`, `quiz_generator`, `tts_node`, `image_generator`, `package_builder`, etc.) are currently stub implementations — hardcoded empty lists and `# TODO` placeholders. This matches `dev1-tracker.md`'s own dashboard (Sprint 2: 0/14 done) and is expected, not a defect. Noting it here only because it means: even once issues #1 and #3 above are resolved and a real OpenAI key is present, a "successful" lesson would still contain no real slides, quiz, audio, or images until that Sprint 2 work lands.
