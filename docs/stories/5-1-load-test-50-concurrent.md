# Story 5-1 — Load test: 50 concurrent lesson generations

Status: in-progress (harness built + reviewed; real 50-concurrent execution not yet run — pending explicit go-ahead on real spend)

## Story

As the **Dev 1 platform engineer preparing TransformED for Week 10's first paying student**,
I want a repeatable load-testing harness that drives 50 concurrent real requests through both the
book-upload endpoint (Phase A) and the lesson-generation endpoint (Phase B), measures enqueue
latency, real pipeline completion time, Redis/cost/circuit-breaker behavior, and reports the
results against named pass criteria,
so that Sprint 4's reliability-fix story (S4-2 / 5-2) has real, measured failure data to prioritize
against instead of the zero-concurrency-tested state recorded today in `DEFECT-REGISTER.md` D129.

## Acceptance Criteria

1. **Harness exists and targets the real endpoints, not a stand-in.** A new load-testing tool
   (`locust` or `k6`, per `docs/dev1-tracker.md` S4-1) drives HTTP load against the actual running
   API — not the eval harness's in-process `run_pipeline()` shortcut (see Dev Notes: the eval
   harness bypasses the HTTP layer, the rate limiter, the concurrency gate, and the ARQ enqueue
   entirely, so it cannot be reused to test any of them). Two distinct endpoints are exercised,
   because they are two different phases with two different named pass criteria (see AC-2/AC-3):
   - `POST /api/content/lessons` (`upload_lesson`, `router.py:686` — book upload / ingestion,
     Phase A)
   - `POST /api/content/books/{book_id}/chapters/{chapter_id}/lessons` (`generate_chapter_lesson`,
     `GENERATE_LESSON_PATH` = `router.py:66`, Phase B — the actual "generate a lesson" trigger)
2. **Epic-5 criterion, measured on the upload endpoint.** 50 concurrent `POST /api/content/lessons`
   requests: P95 response time < 2s, zero pipeline-job crashes, Redis memory reported stable
   before/after (per `docs/bmad/epics/epic-5-platform-core.md` "Load Test" section).
3. **Tracker criterion, measured on the generation endpoint.** 50 concurrent
   `POST .../lessons` (generate) requests, **spread across at least 17 distinct authenticated test
   users** — not 50 requests from one or a few users (see Scale & Load Q1: `max_concurrent_generations_per_user
   = 3` means fewer than 17 users cannot even reach 50 simultaneously-`generating` lessons without
   hitting 429s that measure the concurrency gate, not real pipeline load):
   - P99 time from HTTP request received to `arq_redis.enqueue_job()` returning < 500ms
   - Every accepted job reaches a terminal `lessons.status` (`ready` or `failed`) with no job left
     silently stuck in `generating` past `reap_stale_generating_lessons`'s 10-minute cron sweep
   - Real pipeline completion time (ARQ dequeue → `package_builder` finish) is measured per lesson
     and reported as P50 / P95 / max against the ≤15-minute target — reported as a **measurement**,
     not asserted as a hard pass/fail gate, because at the current `max_jobs = 5` per worker
     process (`workers/main.py:115`) and an unrecorded worker replica count, 50 concurrent
     submissions cannot all execute simultaneously; jobs queued behind the first
     `worker_replicas × 5` will show longer submission-to-completion time through no code defect.
     The AC is: **report actual queue depth and actual per-lesson execution duration separately**,
     so a "SLA miss" caused by queuing is never confused with a "SLA miss" caused by a slow node.
4. **No Redis drops.** Zero connection errors / pool-exhaustion errors observed against the shared
   `ConnectionPool(max_connections=20)` (`core/redis.py:34`) on the API process during the run. If
   any are observed, they are reported as a finding (with a `D-nn` register entry opened per
   binding rule 5), not silently retried away.
5. **Cost ceiling respected under load.** Every lesson in the run either completes under
   `max_lesson_cost_usd` ($3.00) or visibly hits the documented downshift-and-flag path (CLAUDE.md
   §14) — no lesson silently exceeds the ceiling. `cost_tracker.accumulate_cost`'s atomic
   `INCRBYFLOAT` (`cost_tracker.py:60`) is expected to hold under concurrency; the AC is to confirm
   this holds for real under the run, not to re-implement it.
6. **Circuit breaker behavior is observed and reported, not assumed.** `core/circuit_breaker.py`
   trips **per provider, globally** (not per-user, not per-instance — see Scale & Load Q3). The
   report must state explicitly whether any provider's circuit opened during the run and, if so,
   how many concurrent users' jobs were affected by that single open circuit (this is `DEFECT-REGISTER.md`
   D129's risk #1, made concrete).
7. **D45's race is deliberately probed, not just cited.** At least one harness scenario fires 2+
   truly-simultaneous identical `(chapter_id, tier)` generation requests for the same user,
   attempting to reproduce the known TOCTOU idempotency race (`DEFECT-REGISTER.md` D45). The report
   states whether it reproduced (both requests inserted/billed) or the existing mitigations
   (`max_concurrent_generations_per_user`, the 3/minute;20/hour limiter) prevented it in practice.
8. **Gate 7's own concurrency-count race is deliberately probed.** At least one harness scenario
   fires several truly-simultaneous generation requests from **one** test user already near their
   `max_concurrent_generations_per_user` limit, to attempt to oversubscribe the count-then-insert
   gate at `router.py:1308-1324` (the exact pattern CLAUDE.md's Development Rules section names as
   "the per-user concurrency gate `select(\"lesson_id\")` ... a known unbounded-read pattern").
   Reproduced or not, the outcome is documented.
9. **Results are documented and feed the register.** A written results report (this story's Dev
   Agent Record `Completion Notes`, or a linked file under `docs/reports/`) records: topology used
   (API replica count, worker replica count, `max_jobs` value — all must be stated, none assumed);
   P99 enqueue latency; P50/P95/max pipeline execution duration; crash count; Redis error count;
   cost-ceiling breach count; circuit-breaker trip count and blast radius; D45/Gate-7 race
   reproduction outcome. `DEFECT-REGISTER.md` D129 (currently "OPEN, NOT TESTED") is updated with
   the real outcome — this story is what closes that gap, and a stale "not tested" row after this
   story executes is itself a defect.

## Scale & Load

<!-- REQUIRED — see docs/SCALE-CONTRACT.md. Answer all six BEFORE writing Tasks/Subtasks.
     "N/A" is valid ONLY with a stated reason. A bare "N/A" is a missing answer. -->

1. **What is ONE unit of work, and what is its range?**
   One unit of work for *this story* is one load-test run: N simultaneous HTTP requests against
   one of the two endpoints in AC-1, followed by observing every accepted request through to a
   terminal outcome. Range: **min** = 2–3 concurrent real generations — `DEFECT-REGISTER.md` D129's
   own "recommended first step" before any larger burst, to observe the shared-circuit-breaker risk
   in isolation; **typical / target** = 50 concurrent, per both the tracker's S4-1 and Epic-5's
   Load Test scenario; **largest actually measured** = **none — this has never been run.** D129 is
   explicit: "every live confirmation this register has ... is ONE lesson generating at a time."
   This story is the first real measurement the Scale Contract can point to for concurrent load;
   until it executes, every number in this section describing *concurrent* behavior is a reasoned
   projection from single-lesson measurements (D127, ADR-001's memory figures), not a fact.
   **Beyond 50**: explicitly out of scope for this story — do not extrapolate a pass/fail verdict
   past the measured range; a follow-up story is required to test beyond it.

2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   - `max_jobs = 5` (ARQ, per worker process, `workers/main.py:115`) — past it, jobs queue in
     Redis (ARQ's own list-backed queue); nothing is lost or truncated, but submission-to-completion
     time for queued jobs grows linearly with queue depth. This is an **explicit, observable**
     degradation (visible in ARQ's queue metrics) — the AC-3 requirement to report queue depth
     separately from execution duration exists precisely so this degradation is *reported*, not
     silently blamed on a slow pipeline node.
   - `max_concurrent_generations_per_user = 3` (`config.py`) — past it, an explicit `429` with
     `Retry-After` (`router.py:1316-1324`, Gate 7). Already an explicit, surfaced degradation;
     verified in code, not new to this story.
   - Rate limits `5/minute` (upload) and `3/minute;20/hour` (generate) — past them, an explicit
     `429` (slowapi's built-in behavior). Verified.
   - Redis `ConnectionPool(max_connections=20)` (`core/redis.py:34`, one pool per process) — past
     it, `redis-py`'s async pool blocks the caller waiting for a free connection rather than
     raising immediately (library default). **This story's AC-4 exists because that blocking
     behavior under 50-concurrent real load has never been observed** — it may show up as
     latency, not an error, which would not trip a naive "no errors" pass criterion. The harness
     must specifically watch for this.
   - `arq_job_timeout_s = 1800` (30 minutes, `config.py:624`) — past it, ARQ cancels the job
     outright. Note this is **2× looser** than the tracker's 15-minute completion target: ARQ
     itself will not intervene on a lesson that takes 20 minutes, so a load-test-observed 20-minute
     completion is a real SLA miss this story must report even though the platform's own enforced
     ceiling would not have caught it.
   - `max_lesson_cost_usd = 3.00` — past it, downshift-to-cheapest-provider + complete + flag in
     admin (CLAUDE.md §14). Explicit, surfaced, pre-existing.

3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   - `max_jobs = 5` → **per worker process.** Total execution concurrency across the deployment =
     `5 × worker_replica_count`. **Worker replica count is not fixed anywhere in this codebase** —
     no `railway.toml` exists in the repo, and `docs/decisions/ADR-001-india-region-migration-topology.md`
     states API `numReplicas = 2` in production (line 69) but does not state a worker replica
     count. AC-9 requires this story to **record** the actual replica count of whatever environment
     it runs against — the result is meaningless without it.
   - `max_concurrent_generations_per_user = 3` → **per user**, correctly (a Supabase-backed count,
     shared truth across every API replica — unaffected by D49 below).
   - Rate limits (`5/minute`, `3/minute;20/hour`) → **intended** per-user (keyed on JWT `sub` since
     D52's fix), but **effectively per-instance** because `RATE_LIMIT_STORAGE_URL` still defaults
     to `memory://` (confirmed still the default at `core/rate_limit.py:69` as read for this
     story) — **D49 is open, not closed.** With API `numReplicas = 2` (ADR-001), the real ceiling
     a load test will observe is up to ~2× the configured number, split unpredictably by which
     replica a given request lands on. The harness must record which value it actually observes
     against the deployed replica count, not assume the configured number.
   - Redis `ConnectionPool(max_connections=20)` → **per process.** API and worker each call
     `init_redis()` independently (`main.py`'s lifespan, `workers/main.py`'s `startup()`) and get
     their own pool — not shared, not per-deployment.
   - Circuit breaker state (`circuit:{provider}:*` Redis keys) → **per provider, global across the
     whole deployment** — every API and worker process pointed at the same Redis reads/writes the
     same keys. **Not per-user, not per-instance.** This is D129's risk #1 and the single largest
     cross-user blast radius exposed by concurrent load: one user's transient provider failures can
     open a circuit that fails-fast every *other* concurrent user's calls to that provider for the
     next 10 minutes.
   - Cost ceiling → **per lesson** (`cost:{lesson_id}` Redis key), independent across concurrent
     lessons — confirmed safe via atomic `INCRBYFLOAT`.

4. **Which reads and writes are UNBOUNDED?**
   - The per-user concurrency gate's own read — `supabase.table("lessons").select("lesson_id").eq("user_id",...).eq("status","generating").gte("created_at", stale_before).execute()`
     (`router.py:1308-1315`, Gate 7) — carries **no `.limit()` and no `# BOUNDED:` comment.**
     CLAUDE.md's Development Rules section names this exact query as a known unbounded-read
     pattern. Under this story's own load design (≥17 users, each capped at 3 real `generating`
     rows by this very gate) the row count it returns in practice stays small — but the query is
     one regression away from unbounded if the enforcement or D53 staleness logic ever drifts.
     **Not fixed by this story** (out of scope — the harness only issues HTTP requests, it does not
     patch production code); flagged here so it is not silently rediscovered later, and left as an
     optional low-risk hygiene subtask (add a `# BOUNDED:` comment) rather than a required one.
   - The harness's own test-data setup (creating ≥17 test users/books to satisfy AC-3) must add
     `.limit()`/`# BOUNDED:` justification to any new Supabase query it writes, and
     `tests/unit/test_unbounded_queries.py` (the existing CI guard) must be re-run clean against
     any new harness-support code that lives inside `apps/api/` (e.g. a seed script) — it does not
     scan a standalone `k6`/`locust` script outside the Python package, so anything written in
     Python and imported by the app is in scope; anything written as pure `k6` JS is not scanned by
     that guard and needs no such comment.

5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   - `max_jobs = 5`'s own justification ("keep low to avoid OOM", `workers/main.py:116-117`) is
     sized against a **single-lesson** measurement: ADR-001 cites extraction peaking at "≤1.95 GB
     (Sprint 1, live-measured)" for one lesson generating alone. **That figure has never been
     re-derived for 5 (or more, across replicas) lessons extracting truly concurrently on one
     worker VM** — 5 × 1.95 GB ≈ 9.75 GB for extraction peaks alone, before any TTS/image/LLM
     provider client memory or FastAPI/Redis overhead is added. **Re-deriving this number under
     real 5-way concurrent execution is exactly what this story's execution must do** — report
     real measured worker memory during the run, and flag (do not silently accept) if `max_jobs = 5`
     is no longer a safe number once concurrency is real instead of assumed.
   - The tracker's own "≤15 min per lesson" SLA is itself inherited from single-lesson runs (D127's
     2026-08-21 real-world run) — D129 states plainly that every existing measurement is one lesson
     at a time. It has never been re-derived for what 15 minutes means when 5+ lessons compete for
     the same OpenAI/Sarvam/image-provider rate limits and the same globally-shared circuit
     breaker simultaneously. This story is the first attempt at that re-derivation, which is why
     AC-3 treats the number as something to *measure and report*, not silently assume still holds.
   - `max_concurrent_generations_per_user = 3` was sized directly against `max_lesson_cost_usd` as
     "the real spend control" (`config.py`'s own field description) — already re-derived correctly
     for the current (book, not single-upload) unit of work; not stale.

6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   - **Gate 7 (per-user concurrency count-then-insert, `router.py:1308-1324`).** The `generating`
     row count is read, then — after the catastrophe-page-span gate — a `lessons` row is inserted,
     with nothing atomic tying the two together. N truly-simultaneous requests from the *same*
     user can all read the same "2 of 3 used" count and all pass, oversubscribing the cap by up to
     N−1 lessons. Same shape as D45; **not previously observed under real concurrency** — AC-8
     exists to deliberately try to trigger it and report the result rather than reason about it in
     the abstract.
   - **Gate 5 / D45 (`(chapter_id, tier)` idempotency pre-check).** Registered, "Accepted for Phase
     6, bounded not fixed" (`DEFECT-REGISTER.md`). No `UNIQUE` constraint exists anywhere to fall
     back on. AC-7 deliberately fires simultaneous identical requests to observe this for real for
     the first time, rather than leave it as a documented-but-never-tested risk.
   - **ARQ `enqueue_job(..., _job_id=f"pipeline:{lesson_id}")`** (`router.py:1374-1376`) — safe:
     `lesson_id` is freshly minted by the immediately-preceding `INSERT`, so this specific enqueue
     cannot collide with another in-flight job id by construction (confirmed by the code's own
     comment at that call site).
   - **Circuit breaker `record_failure` / `is_circuit_open`** (`core/circuit_breaker.py`) — reads
     and writes the failure counter and state key as separate Redis calls (`INCR`, then `GET`,
     then conditionally `SET`), not one atomic Lua script. Under many concurrent failing calls,
     multiple requests can all observe the threshold breached and all independently `SET` the
     circuit to `OPEN` — **benign and idempotent** (worst case: `opened_at` is overwritten a few
     times with near-identical timestamps), not a correctness bug. Reasoned explicitly here rather
     than assumed safe by pattern-matching to the cost tracker's genuinely atomic increment.
   - **`cost_tracker.accumulate_cost`** — atomic `INCRBYFLOAT` (`cost_tracker.py:60`); confirmed
     safe under concurrent writers by construction, independently verified during the D132 fix.

## Tasks / Subtasks

- [x] **Task 1 — Choose and scaffold the harness tool** (AC: 1)
  - [x] Decide `locust` vs `k6` (neither is in `apps/api/pyproject.toml` or anywhere in the repo —
    confirmed via repo-wide search; this is genuinely greenfield tooling, not an extension of
    anything existing). Note `scripts/ws_load_test.py` (Dev 4's WebSocket load-test script) is a
    precedent for a self-contained async-Python harness style in this repo, but it load-tests the
    tutor WebSocket endpoint, not the content-generation HTTP path — not directly reusable, only a
    style reference.
  - [x] Explicitly evaluate and reject reusing `apps/api/tests/evals/runner.py` for load
    generation: it calls `run_pipeline()` **directly, in-process**, bypassing the HTTP layer, the
    rate limiter, Gate 5/6/7, and the ARQ enqueue path entirely (`runner.py:190-296`), and its own
    Scale & Load section (Story 3-57) states it is a **sequential** `for` loop by design — it
    cannot be safely or meaningfully repurposed for concurrent HTTP load without rewriting it into
    something that no longer resembles the eval harness.
  - [x] Scaffold the chosen tool under a new path (e.g. `apps/api/tests/loadtest/` or
    `scripts/loadtest/`, following the existing `scripts/ws_load_test.py` convention for
    load-test scripts kept outside the pytest tree).
- [x] **Task 2 — Seed ≥17 distinct test users + at least one shared uploaded/detected book+chapter
  fixture** (AC: 2, 3)
  - [x] Reuse or extend the eval-PDF fixture generator (`apps/api/tests/fixtures/generate_eval_pdfs.py`)
    for a real, chapter-detectable book rather than inventing a new fixture.
  - [x] Any new Supabase seed queries this adds must carry `.limit()`/`# BOUNDED:` justification —
    re-run `tests/unit/test_unbounded_queries.py` against any new Python seed code.
- [x] **Task 3 — Implement the Phase A (upload) load scenario** (AC: 2, 4)
  - [x] 50 concurrent `POST /api/content/lessons` requests, distinct users, distinct PDF payloads.
  - [x] Capture P95 response time, error count, and Redis connection-error count on the API process
    during the run.
- [x] **Task 4 — Implement the Phase B (generate) load scenario** (AC: 3, 4, 5, 6)
  - [x] 50 concurrent `POST .../lessons` (generate) requests across ≥17 users (respecting
    `max_concurrent_generations_per_user = 3` per user by construction of the request plan, not by
    accident).
  - [x] Poll each accepted `lesson_id` (via `lesson_jobs`/`lessons.status`, whichever the existing
    client-facing status read already uses) to a terminal state; record dequeue time (from
    `lesson_jobs`/ARQ result metadata) separately from HTTP-submission time so queue-wait and
    execution-duration are reported as distinct numbers (Scale & Load Q2).
  - [x] Record real Redis error counts, real cost-ceiling breach counts (`cost_tracker`), and
    real circuit-breaker state transitions (`circuit:{provider}:state` keys) observed during the
    run.
- [x] **Task 5 — Implement the two deliberate race-probe scenarios** (AC: 7, 8)
  - [x] D45 probe: N truly-simultaneous identical `(chapter_id, tier)` requests from one user.
  - [x] Gate 7 probe: several truly-simultaneous generation requests from one user already at or
    near `max_concurrent_generations_per_user`.
  - [x] Report reproduction outcome for each, explicitly (reproduced / not reproduced / blocked by
    existing mitigation, and which one).
- [ ] **Task 6 — Run, capture topology, and write the results report** (AC: 9)
  - [ ] Record the actual API replica count and worker replica count of the environment the run
    executed against (do not assume ADR-001's production figures apply to a test/staging run).
  - [ ] Record real worker memory during the 5-concurrent-job window (re-deriving the `max_jobs = 5`
    cap per Scale & Load Q5).
  - [ ] Update `DEFECT-REGISTER.md` D129 with the real measured outcome, replacing its current
    "OPEN, NOT TESTED" status.
  - [ ] If any new defect is found (Redis errors, an actual D45/Gate-7 double-insert, a
    circuit-breaker blast-radius incident, an `max_jobs`/OOM risk), open a new `D-nn` register
    entry per binding rule 5 — do not leave a finding as a comment with no ID.

## Dev Notes

- **Two endpoints, two phases, two named pass criteria — do not conflate them.**
  `docs/bmad/epics/epic-5-platform-core.md`'s "Load Test" section describes "50 concurrent users
  each uploading a PDF simultaneously... P95 upload response < 2s" — this is Phase A ingestion,
  measured on `upload_lesson` (`POST /api/content/lessons`, `router.py:686`). `docs/dev1-tracker.md`
  S4-1 describes "50 concurrent lesson generations... P99 enqueue latency <500ms; pipeline
  completion within SLA (≤15 min)" — this is Phase B generation, measured on
  `generate_chapter_lesson` (`POST /api/content/books/{book_id}/chapters/{chapter_id}/lessons`,
  `GENERATE_LESSON_PATH`, `router.py:1050`). Both are real, both are required (AC-2, AC-3); neither
  substitutes for the other. Note the naming is actively misleading: `POST /api/content/lessons`
  *sounds* like it generates a lesson but is book upload only — deliberate per the endpoint's own
  docstring (decision D-A, book-scale Phase 3): "between this change and Phase 6 there is no
  endpoint that generates a lesson" at that path.
- **`docs/dev1-tracker.md`'s S4-4 claim is stale against the real code, verify before reusing it.**
  S4-4 says "Per-route limits not yet configured on pipeline endpoints ✗" — but as read for this
  story, `upload_lesson` already carries `@limiter.limit("5/minute", key_func=_get_user_key)`
  (`router.py:692`) and `generate_chapter_lesson` already carries
  `@limiter.limit("3/minute;20/hour", key_func=_get_user_key)` (`router.py:1056`), matching the
  tracker's own "Ahead-of-Schedule Wins" table entry ("Add per-route limit to `POST
  /api/content/lessons` in Sprint 1 (S1-10)"). This story's load test will exercise whatever limits
  are actually live, not whatever S4-4's checkbox currently says — the discrepancy is noted here
  rather than silently papered over, per this repo's own standing lesson that "prose guidance does
  not hold" (CLAUDE.md, Defect Register section) and drifted docs are a recorded defect class.
- **D129 (`DEFECT-REGISTER.md`) is this story's direct predecessor.** It names the exact three
  concurrency risks this story must probe: the globally-shared circuit breaker (AC-6), D45 (AC-7),
  and D49's replica-multiplied rate limiter (Scale & Load Q3). D129 also explicitly recommends
  starting with "a SMALL controlled test (2-3 concurrent real lesson generations)... before any
  larger-scale load test" — Task 1-2's harness should support running at that smaller scale first
  as a smoke test before the full 50-concurrent run, not only support the final number.
- **D49 (`RATE_LIMIT_STORAGE_URL` default) is still open, confirmed by reading `core/rate_limit.py`
  for this story** — `storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URL", "memory://")` is
  unchanged. This matters directly for this story: if the load test is run against a
  multi-replica environment without that env var set, the rate limits it observes will not match
  the configured numbers, and the harness/report must say so rather than report a false pass.
- **`arq_job_timeout_s` (1800s) vs the 15-minute SLA target is a real, load-bearing gap**, not
  a typo: ARQ will let a job run twice as long as the tracker's target before intervening. This
  story reports against the 15-minute target as a measurement; it is Sprint 4's next story (S4-2 /
  5-2) that would decide whether to tighten `arq_job_timeout_s` or fix whatever node is slow,
  using this story's real numbers.
- **Source tree components touched:** none in `apps/api/app/` (this story adds a load-test tool
  and a fixture/seed script, not production code) except the optional low-risk `# BOUNDED:`
  comment hygiene fix noted in Scale & Load Q4, which is explicitly optional. New files live under
  a load-test-specific path (Task 1) plus whatever fixture reuse Task 2 needs.
- **Testing standards summary:** this story's own "test" is the load-test run itself and its
  captured metrics, not a pytest suite in the usual sense — but any new Python code it adds inside
  `apps/api/` (seed scripts, a k6/locust launcher wrapper) still goes through
  `tests/unit/test_unbounded_queries.py`, `ruff`, and `mypy` like any other change to that package.

### Project Structure Notes

- **`docs/bmad/epics/epic-5-platform-core.md`'s Technical Scope table names `backend/routers/payments.py`
  and `backend/workers/notification_worker.py`** — these paths do not exist in this repo and do not
  match its real convention. The actual convention, confirmed by directory listing, is
  `apps/api/app/modules/{module}/router.py` (e.g. `apps/api/app/modules/content/router.py`,
  `apps/api/app/modules/admin/router.py`) and `apps/api/app/workers/jobs/{job}.py` (e.g.
  `apps/api/app/workers/jobs/content_pipeline.py`, `book_ingest.py`). This does not block this
  story (S4-1 touches neither payments nor notifications) but is flagged here because the epic doc
  is evidently aspirational/stale on file paths in places, exactly as this story's brief warned —
  do not trust its paths for Stripe-related Sprint 4 stories (S4-3) without the same verification
  this story did for the content-pipeline paths.
- This story's own harness code should live outside `apps/api/app/` entirely (it is a test tool,
  not application code) — either `apps/api/tests/loadtest/` (keeps it inside the Python package for
  shared fixture/config reuse) or top-level `scripts/` (matching the `scripts/ws_load_test.py`
  precedent for a load-test script that is not a pytest suite). Either is acceptable; pick one and
  keep it consistent with whichever `locust`/`k6` choice Task 1 makes.
- No `packages/shared/` interface contracts are touched by this story.

### References

- [Source: docs/dev1-tracker.md#Sprint-4] — S4-1 raw task line (lines 1094-1097), Sprint 4 goal,
  and the "Ahead-of-Schedule Wins" table (per-route rate limiting already landed in Sprint 1).
- [Source: docs/bmad/epics/epic-5-platform-core.md#Production-Hardening] — "Load Test" section
  (50 concurrent users uploading, P95 <2s, no crashes, Redis memory stable) and the epic's
  Definition of Done load-test line.
- [Source: docs/DEFECT-REGISTER.md#D129] — "OPEN, NOT TESTED — no multiple-concurrent-real-user
  load has ever been run"; the three concurrency risks this story is scoped to probe.
- [Source: docs/DEFECT-REGISTER.md#D45] — `(chapter_id, tier)` idempotency TOCTOU race, "Accepted
  for Phase 6, bounded not fixed."
- [Source: docs/DEFECT-REGISTER.md#D49] — `RATE_LIMIT_STORAGE_URL` default `memory://`, replica
  multiplication; confirmed still open by direct code read for this story.
- [Source: docs/DEFECT-REGISTER.md#D52] — closed; historical context for why the rate limiter is
  keyed correctly by user today.
- [Source: docs/DEFECT-REGISTER.md#D50] — 300-DPI render/upload uncapped, outside `cost_tracker`;
  cited for the general pattern of "cheap wrong" failures the Scale Contract exists to catch.
- [Source: docs/SCALE-CONTRACT.md] — the six questions answered above; D45/D49/D50 worked examples.
- [Source: apps/api/app/modules/content/router.py:66,686-737,1050-1076,1212-1275,1296-1425] —
  `GENERATE_LESSON_PATH`, `upload_lesson`, `generate_chapter_lesson`, Gate 5 (idempotency), Gate 7
  (per-user concurrency count-then-insert).
- [Source: apps/api/app/workers/main.py:95-148] — `WorkerSettings`: `max_jobs = 5`,
  `job_timeout` from `settings.arq_job_timeout_s`, cron `reap_stale_generating_lessons`.
- [Source: apps/api/app/core/redis.py:17-34] — shared `ConnectionPool(max_connections=20,
  decode_responses=True)`, one per process via `init_redis()`.
- [Source: apps/api/app/core/circuit_breaker.py:1-37] — per-provider global Redis-backed state,
  `FAILURE_THRESHOLD=5`/`FAILURE_WINDOW_SECONDS=120`/`RECOVERY_TIMEOUT_SECONDS=600`.
- [Source: apps/api/app/core/cost_tracker.py:42-63] — `accumulate_cost`'s atomic `INCRBYFLOAT`.
- [Source: apps/api/app/core/rate_limit.py:26-90] — `_get_user_key`, D52/D64 history,
  `RATE_LIMIT_STORAGE_URL` default `memory://` (D49, confirmed still present).
- [Source: apps/api/app/config.py:232-303,624-654] — `max_lesson_cost_usd=3.00`,
  `max_concurrent_generations_per_user=3`, `arq_job_timeout_s=1800`,
  `extract_timeout_cap_s`/`arq_job_timeout_s` invariant.
- [Source: docs/decisions/ADR-001-india-region-migration-topology.md:69,77-78,233] — API
  `numReplicas = 2` in production; extraction memory peak "≤1.95 GB (Sprint 1, live-measured)";
  `max_jobs = 5` cited as the coupled scaling constraint.
- [Source: docs/stories/3-57-eval-harness-20-pdfs.md] and [Source:
  docs/stories/2-14-eval-harness-5-pdfs.md] — eval harness design; confirmed sequential, in-process
  (`run_pipeline()` direct call), not reusable for concurrent HTTP load generation.
- [Source: apps/api/tests/evals/runner.py:115-120,296,375-425] — confirms the in-process
  `run_pipeline()` call and the ARQ-enqueue bypass this harness must NOT inherit.
- [Source: scripts/ws_load_test.py] — Dev 4's existing WebSocket load-test script; style precedent
  only, not the same endpoint or protocol.
- [Source: apps/api/pyproject.toml:13-38] — confirmed no `locust`/`k6` dependency exists yet
  (greenfield tooling); `httpx>=0.27.0` already a dependency if a Python-async approach is chosen
  instead of `k6`.
- [Source: apps/api/tests/unit/test_unbounded_queries.py] — existing CI guard any new Python
  seed/harness code inside `apps/api/` must stay clean against.

## Sprint 4 Sequencing

- **Branch:** `sprint4/s4-1-load-test-concurrent`
- **Depends on:** None. All mechanisms this story exercises (rate limiter, per-user concurrency
  gate, circuit breaker, cost ceiling, ARQ pipeline) were built in earlier sprints and are already
  live; this story is standalone, greenfield load-testing tooling that does not require Stripe
  (S4-3/5-3), the RLS audit (S4-5/5-5), backups (S4-6/5-6), the runbook (S4-7/5-7), or the Imagen
  migration (S4-8/5-8) to start or finish.
- **Blocks:** **S4-2 / 5-2 (Pipeline reliability fixes from test sessions)** — S4-2's own AC is
  "All failure modes **from S4-1** resolved," so it cannot be meaningfully scoped, let alone
  completed, until this story's execution produces real failure data. Also **informs but does not
  block** S4-7 / 5-7 (the on-call runbook's "Redis unreachable" / "Supabase connection pool
  exhausted" scenarios are far better written from this story's real observations than from
  first principles) and S4-6 / 5-6 (disaster-recovery testing benefits from knowing real load
  characteristics) — neither is a hard dependency, both are better sequenced after.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (`claude-sonnet-5`), via a 6-agent workflow (4 parallel builders, 1 integration
pass, 1 adversarial pre-execution review).

### Debug Log References

- Confirmed local Redis reachable (`redis-cli ping` → `PONG`) and `arq`/`uvicorn`/`fastapi`
  importable in `.venv` before starting, to establish the harness is genuinely runnable in this
  environment (separate question from whether the real 50-concurrent execution is authorized).
- Confirmed via direct code read that `generate_chapter_lesson` (Phase B) requires only
  `CurrentUser` (any authenticated user, no allowlist), while `upload_lesson` (Phase A) requires
  `ApprovedUser` (JWT + `APPROVED_EMAILS`) — this shaped the harness design: Phase B uses 17 fresh
  disposable users (no allowlist needed), Phase A reuses the 3 existing approved accounts rather
  than expanding the allowlist.
- `ruff check`/`mypy`/`pytest tests/unit/test_unbounded_queries.py` all reconfirmed green by hand
  after the review agent's own fixes, since the review agent itself could only reach
  `python3 -m py_compile` in its sandbox and explicitly flagged that as a gap.

### Completion Notes List

- Tasks 1–5 (harness built): pure Python asyncio + httpx (matches `scripts/ws_load_test.py`'s
  existing style precedent; no new `locust`/`k6` dependency needed), under
  `apps/api/tests/loadtest/`: `models.py` (shared `TestUser`/`ScenarioResult` contract),
  `provisioning.py` (disposable-user minting/cleanup via the same Admin-API `generate_link`
  pattern proven in Story 5-5, since this project's asymmetric JWT signing keys make self-minted
  JWTs impossible here too), `fixtures.py` (real book/chapter fixture via the existing
  `eval_pdfs/short_10page.pdf`), `phase_a_upload.py`, `phase_b_generate.py`, `race_probes.py`
  (D45 + Gate-7), `report.py`, `run.py` (CLI, `--scale smoke|full`).
- **Adversarial review before any real run found and fixed 2 critical defects that would have
  caused real, permanent damage on first execution:**
  1. A partial-provisioning failure (one of 17 disposable-user creations failing after its real
     `auth.users` row was already written) would have orphaned up to 17 real rows permanently,
     since `asyncio.gather`'s default fail-fast behavior meant the cleanup `finally` block was
     never reached. Fixed: gather with `return_exceptions=True`, clean up every user actually
     created (successful or not) before re-raising.
  2. Phase A's design (reusing the 3 existing `APPROVED_EMAILS` accounts, since only Phase A needs
     the allowlist) meant every one of its 50 concurrent uploads would create a REAL, permanent
     `books`/`chapters`/`chunks` row on real accounts — at least one of which is a real developer
     account, not a disposable seed user — with **no cleanup path at all** (no `DELETE /books/{id}`
     endpoint exists in the app). Every full-scale run would have permanently and irreversibly
     polluted real accounts. Fixed: capture `book_id` from every upload response, added
     `cleanup_uploaded_books` (storage object + `DELETE .../books` row, cascading to
     chapters/chunks via the existing migrations' `ON DELETE CASCADE`), wired into `run.py`'s
     guaranteed cleanup path.
  3. (Medium) The D45 and Gate-7 race probes originally risked false results by colliding with
     Phase B's own pre-seeded state (same chapter, same tier) — fixed by using a different tier
     for the D45 probe and excluding Phase B's chapter from the Gate-7 probe's candidate set.
  4. (Low, hardening) `TestUser`'s default `repr()` would have printed a real, live access token in
     full on any incidental log/print/assertion — fixed with a custom `__repr__` that truncates it.
- Task 6 (the actual run) is **deliberately not done** — this story's own scope includes real
  financial spend (OpenAI/Sarvam/image-provider costs across up to 100 real generation/upload
  requests) and requires separate, explicit human go-ahead before executing, per this session's
  established practice for any real-money action. The harness is built, integrated, lint/type
  clean, and adversarially reviewed — ready to run at `--scale smoke` (cheap sanity check, ~3 real
  generations) or `--scale full` (the real AC-2/AC-3 50-concurrent target) once authorized.

### File List

- `apps/api/tests/loadtest/__init__.py` (new)
- `apps/api/tests/loadtest/models.py` (new)
- `apps/api/tests/loadtest/provisioning.py` (new)
- `apps/api/tests/loadtest/fixtures.py` (new)
- `apps/api/tests/loadtest/phase_a_upload.py` (new)
- `apps/api/tests/loadtest/phase_b_generate.py` (new)
- `apps/api/tests/loadtest/race_probes.py` (new)
- `apps/api/tests/loadtest/report.py` (new)
- `apps/api/tests/loadtest/run.py` (new)
- `docs/stories/5-1-load-test-50-concurrent.md` (this file — status, tasks, Dev Agent Record)
