# On-Call Runbook

**Scope:** the single Fly.io deployment of `hie-api` (`bom`/Mumbai per `fly.toml`; Redis is
Upstash — the India-region migration completed 2026-08-14, ADR-001/D158; **D145 is a known,
still-open exception: the live region list has been observed drifted to `sin`/Singapore**). Any
host/dashboard link below is this-environment-only; re-verify after any future region change
rather than assuming it still applies.

**Owner rotation:** Week 10 on-call (`docs/dev1-tracker.md` W10-3).

**First step for ANY incident:** `GET /api/admin/health` (`deep_health`). This is the only real,
existing probe of Redis + Supabase reachability in this codebase today — it is distinct from the
plain `GET /health` liveness probe, which returns `{"status": "ok"}` unconditionally and does
**not** check either dependency. There is no paging/alerting integration wired yet (grepped,
none found) and no live queue-depth dashboard (`DeepHealthStatus.worker_queue_depth` is hardcoded
`None`) — detection below is manual, admin-endpoint-driven, not "wait for an alert."

---

## 1. ARQ job stuck

**Detection:** `GET /api/admin/jobs?status_filter=running` — look for a row whose `started_at` is
old relative to `arq_job_timeout_s` (default 1800s / 30 min). Alternatively, wait for the
`reap_stale_generating_lessons` cron (`apps/api/app/workers/jobs/reap_stale_lessons.py`, runs at
`:00/:10/:20/:30/:40/:50`, D53/D91) — it already finds and fails these on its own, bounded to 100
rows per pass (`_REAP_BATCH_LIMIT`).

**Diagnosis:** `GET /api/admin/jobs/{job_id}` for the job's `last_node` / `node_outputs` /
`error`. If the worker process itself is down (not just one slow job), Redis is the more likely
root cause — see §3 below; ARQ cannot dequeue anything without it.

**Resolution (≤5 steps):**
1. Confirm via `GET /api/admin/jobs/{job_id}` that the job is genuinely stuck (no `node_outputs`
   progress across repeated checks a few minutes apart), not just legitimately slow — real
   50-concurrent load-test data (Story 5-1/5-2, D154) measured P50=20.6min / P95=25.2min for a
   full pipeline run, comfortably under the 30-min job timeout, so a job at 15-20 minutes with no
   progress signal is not automatically "stuck."
2. If genuinely stuck, wait for the next reaper tick (≤10 min) rather than intervening — it will
   mark it `failed` automatically.
3. If it needs resolution sooner, use `POST /api/admin/jobs/{job_id}/retry` (Story 3-58) to
   re-enqueue from the last checkpoint (`last_node`/`node_outputs` — never re-runs completed LLM
   calls).
4. **Concurrency warning (D109, registered, not fixed):** this retry endpoint has no DB-level lock
   preventing two people (or one person double-clicking) from retrying the same job concurrently.
   One person retries; confirm `lesson_jobs.status`/`lessons.status` converge before anyone
   attempts a second retry.
5. If the reaper itself isn't running (no jobs ever transition, worker process appears wedged
   entirely) — escalate to §3 (Redis unreachable) or a direct Fly worker-machine restart
   (`flyctl machine restart -a hie-api`, worker process group).

---

## 2. Cost ceiling breach mid-pipeline

**Detection:** `GET /api/admin/costs` (bounded, `.limit(10_000)`, `truncated` flag — Story
3-51/D59(a); never run a raw unbounded query instead), or `lesson_jobs.error` prefixed
`cost_ceiling_exceeded:`.

**Diagnosis:** The system's actual designed behavior is **downshift-and-complete, not abort**
(`app/core/cost_tracker.py`'s `CostCeilingError`, `settings.max_lesson_cost_usd` default `$3.00`,
Redis key `cost:{lesson_id}`). A lesson hitting this ceiling should still reach `ready`, just via
cheaper providers for its remaining nodes — this is expected, working behavior, not a failure to
fix.

**Resolution (≤5 steps):**
1. Confirm the lesson actually completed (`lessons.status = 'ready'`) despite the ceiling hit —
   if so, this is the system working as designed; no action needed beyond noting it.
2. If the lesson did NOT complete, treat it as a separate node failure (see §4, node 500-loop) —
   the cost ceiling itself does not fail a job, so a non-`ready` outcome here means something else
   also went wrong.
3. If cost volume looks anomalous (many lessons hitting the ceiling, not isolated), check whether
   a provider's per-unit price changed or a prompt regressed — this is a product/model question,
   not an infra incident.
4. Do not manually re-trigger the lesson to "fix" a downshift — a downshifted-but-`ready` lesson
   is not broken. If a manual re-trigger is genuinely needed, note **D45**: the
   `(chapter_id, tier)` idempotency pre-check has no UNIQUE constraint, so a concurrent duplicate
   trigger can double-bill the same student.
5. Escalate to Dev 1 (content pipeline owner) only if `GET /api/admin/costs` shows the ceiling
   itself appears mis-set or is firing on lessons that clearly shouldn't be near it.

---

## 3. Redis unreachable

**Detection:** `GET /api/admin/health` → `redis` field, or the Upstash console directly.

**Diagnosis — real blast radius, not independent of the other scenarios:** ARQ cannot dequeue any
job at all without Redis. `app/core/circuit_breaker.py` and `app/core/cost_tracker.py` both call
`get_redis()`, which raises `RuntimeError` if `init_redis()` never completed. **This failure is
upstream of §1 (ARQ stuck) and §2 (cost ceiling) — if Redis is down, both of those will also look
broken, and fixing Redis is the actual fix, not treating them as three unrelated incidents.**

**Resolution (≤5 steps):**
1. Confirm via `GET /api/admin/health` that `redis` (not just `supabase`) is the failing field.
2. Check the Upstash instance directly (console) for an outage, exhausted connections, or a
   plan/quota limit.
3. If Upstash itself is healthy but the app can't reach it, check `REDIS_URL` is still a
   currently-valid Fly secret (`flyctl secrets list -a hie-api` — same drift class as
   D145/D146/D150/D157 — a secret or config value that silently stopped matching reality).
4. Once Redis is confirmed reachable again, re-check `GET /api/admin/health` — do not assume a
   Redis-side fix has propagated without re-probing.
5. After Redis recovery, re-check §1 and §2 symptoms — jobs that looked "stuck" due to Redis
   being down should resume on their own once the worker reconnects; only intervene further if
   they don't.

---

## 4. Pipeline node 500-loop

**Detection:** repeated `lesson_jobs.node_outputs` entries for the same `last_node` across
retries (via `GET /api/admin/jobs/{job_id}`), or Langfuse traces if wired for the affected node —
verify actual wiring before relying on it; don't assume every node is traced.

**Diagnosis / resolution — three real layers already exist; a true infinite loop means all three
failed, which is itself the escalation trigger:**
1. **Per-node retry** (`app/core/retry.py`): 3 attempts for critical nodes / 2 for optional,
   exponential backoff with jitter (`(2**attempt) + random()`), retries only
   `{429, 500, 502, 503, 504}` — `{400, 401, 403, 404, 422}` are never retried (by design; a 401
   won't fix itself by retrying).
2. **Per-provider circuit breaker** (`app/core/circuit_breaker.py`): opens after 5 failures in a
   120s window, half-open probe after 600s. Redis keys `circuit:{provider}:state` /
   `:failures` / `:opened_at`. **No admin action or code-level reset function exists** — a
   confirmed false-open is cleared with a direct Redis `DEL circuit:{provider}:state`, nothing
   else.
3. **ARQ job-level retry** (`app/workers/main.py`): `max_tries=3` at the whole-job level, on top
   of the two node-level layers above.
4. If a node is genuinely looping past all three layers, capture the real error from
   `node_outputs`/logs before touching anything — this is the signal Dev 1 needs to fix the root
   cause, not just clear the symptom.
5. As an immediate mitigation once the root cause is captured: `POST /api/admin/jobs/{job_id}/retry`
   (same D109 concurrency caveat as §1) after confirming the underlying issue (e.g. a bad
   provider key, a malformed prompt) isn't going to reproduce identically on retry.

---

## 5. Supabase down

**Detection:** `GET /api/admin/health` → `supabase` field.

**Resolution (≤5 steps) — confirm-and-communicate only; this entry does NOT contain restore
mechanics, per the "don't duplicate a drifting copy of a restore procedure" rule:**
1. Confirm via `GET /api/admin/health` that `supabase` (not `redis`) is the failing field.
2. Check the Supabase project status page / dashboard directly for a known incident.
3. Communicate to users (status page / in-app messaging) that generation and playback are
   degraded — do not attempt silent recovery while the outage is ongoing.
4. **Gap, stated explicitly rather than silently omitted:** the intended step 4/5 here is "follow
   the disaster-recovery procedure," which should live in a doc produced by **Story 5-6** (Fly.io
   backups + DR tested) — **that story has not started yet, and no such doc exists today.** Until
   it does, restore is a manual, ad hoc action via Supabase's own dashboard (Project Settings →
   Database → Backups) with no tested, repo-owned procedure behind it.
5. Once Story 5-6 ships, replace this entry's step 4 with a link to its DR doc instead of this
   note — tracked so this runbook doesn't silently go stale once that doc exists.

---

## 6th scenario? — payment webhook failure (reconciliation, per AC 4)

**Status: reconciliation deferred — not a gap in this runbook, a stated sequencing dependency.**

`docs/bmad/epics/epic-5-platform-core.md`'s runbook section names a 4th scenario,
"Stripe webhook failing," that `docs/dev1-tracker.md`'s S4-7 list (the mandatory floor used
above) doesn't include. Real, current state as of this writing:

- The payment vendor is **Razorpay, not Stripe** — Stripe Checkout (the original Story 5-3) was
  closed without merging; Razorpay's backend (create-order + webhook + `lesson_access`) is PR #157,
  currently **open and approved but not yet merged to `main`**.
- `main` has **no payments module at all today** (`apps/api/app/modules/payments/` does not exist
  on `main`; confirmed via `git ls-tree`) — only stale local `__pycache__` artifacts from a
  previous branch checkout, no tracked source.
- Because the real webhook handler isn't live yet, there is no real failure shape to document —
  writing this entry now would be speculation, exactly what this runbook's Dev Notes commit to
  avoiding ("written from what Sprint 4 actually observed," not first-principles guessing).

**Recommendation:** once the Razorpay PR merges and has run against real traffic (or at least a
real webhook replay), add this as its **own scenario entry** rather than folding it into an
existing one — a payment webhook failure is a delivery/idempotency problem (duplicate or missed
webhook, `lesson_access` not granted despite a real charge), not a pipeline-node or
infra-dependency failure, so it doesn't fit the shape of any of the 5 entries above. Revisit this
section the moment that PR merges; do not let it silently stay "deferred" past that point.

---

## Tested-by sign-off

_To be completed by a teammate who did not author this runbook (AC 7) — walk each scenario above
against the real admin endpoints / real Redis keys named, and record what did not work as
written._

| Name | Date | Scenarios walked | Gaps found |
|------|------|-------------------|------------|
| _(pending)_ | | | |
