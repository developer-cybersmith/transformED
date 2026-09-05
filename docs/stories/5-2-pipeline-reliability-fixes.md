# Story 5-2 — Pipeline reliability fixes from test sessions

Status: in-progress (AC1 partial: D152, D153 found + fixed via S4-1 runs #9/#10; AC2 confirmed)

## Story

As the on-call developer responsible for the content generation pipeline going into Week 10
launch,
I want every failure mode that S4-1's 50-concurrent-lesson load test actually surfaces —
plus the four named risk categories (retry exhaustion, cost-ceiling breach mid-flight, Redis
connection drops, node timeout under load) tested explicitly even if the load test does not
organically trigger all four — triaged into `docs/DEFECT-REGISTER.md`, fixed, and guarded by a
regression test,
so that no failure mode discovered under concurrent real-student load can reach production as a
silent failure (a lesson that reports `completed`/`failed` incorrectly, a stuck `generating` row,
an under- or over-reported cost, or a duplicate charge) rather than a loud, surfaced one.

## Acceptance Criteria

**This story cannot enumerate its own bugs in advance — see Dev Notes "Living checklist" — so
the ACs below are a *triage protocol and mandatory checklist*, not a fixed list of known defects.**
Every AC is testable against that protocol, not against a specific (currently unknown) failure.

1. **Every failure S4-1 (5-1) actually observed is registered before it is fixed.** For each
   distinct failure mode the load test run produced (job stuck in `running`/`generating`,
   unhandled exception, timeout, wrong final status, wrong `cost_usd`, duplicate billing, etc.),
   a new `D-nn` entry exists in `docs/DEFECT-REGISTER.md` — evidence (what was observed, how many
   of N concurrent jobs, log/trace reference), severity, and root-cause hypothesis — **before**
   any fix for it is written, per CLAUDE.md binding rule 5.
2. **Retry exhaustion is explicitly tested, not only observed.** A scenario that exhausts
   `with_retry`'s `max_attempts` (3 for critical nodes, 2 for optional — `core/retry.py`) is
   deliberately forced (e.g. a provider mock that always returns a retryable 503) under
   concurrent load, and the resulting `lesson_jobs`/`lessons` state is asserted to be an explicit
   `failed` with a real, non-empty `error` message — never a job silently vanishing or a row
   stuck in `running`.
3. **Cost ceiling breach mid-flight is explicitly tested under concurrency**, not only
   single-lesson. Given N concurrent lessons each accumulating cost via
   `core/cost_tracker.accumulate_cost()` (Redis `INCRBYFLOAT`, atomic per key), each lesson that
   crosses `settings.max_lesson_cost_usd` independently: (a) premium/media nodes
   (`lesson_planner`, `slide_generator`, `tts_node`, `image_generator`) downshift to the cheaper
   model/provider and the lesson completes (per S2-13's already-implemented downshift path) —
   confirmed to still hold under concurrent load, not just serially; (b) Phase 1 economy nodes'
   accepted terminate-and-flag behavior (S2-13 Dev Notes: `llm_mini` has nothing cheaper to
   downshift to) is confirmed to fail with an explicit `cost_ceiling_exceeded:` status, never a
   silent hang; (c) no lesson's real spend, read back from `lesson_jobs.cost_usd` post-hoc,
   exceeds the ceiling by more than one node's worth of already-in-flight spend.
4. **Redis connection drops are explicitly tested under concurrent load**, not assumed fixed by
   D19 (closed 2026-07-29) alone. D19 closed the exception-classification defect
   (`redis.exceptions.TimeoutError`/`ConnectionError` not matching the builtins) for the
   single-lesson case; this AC re-verifies `is_circuit_open()` fails open, `guard_breaker` does
   not count a Redis error as a provider failure, and a mid-run Redis blip does not cascade into
   an incorrectly-opened circuit breaker, specifically while multiple lessons are concurrently
   reading/writing the same `circuit:{provider}:*` keys and the same `cost:{lesson_id}` keys.
5. **Node timeout under load is explicitly tested**, and the current timeout budget's shape is
   named as a finding if it proves inadequate: today there is no per-node timeout distinct from
   (a) the OpenAI SDK's own `openai_request_timeout_s`/`openai_image_request_timeout_s`
   (120s/180s, `config.py:606-613`) and (b) the single whole-pipeline `arq_job_timeout_s` (1800s,
   `config.py:624`) enforced only by ARQ cancelling the job outright. A load scenario in which
   many concurrent provider calls run slow (not erroring, just slow — e.g. a provider under real
   rate-limit pressure) must be run, and the outcome — job legitimately still running vs. job
   incorrectly cancelled vs. job silently stuck — must be captured and, if a gap is found, either
   fixed with a real per-node budget or registered as a `D-nn` with an explicit owner/trigger
   (not silently left as-is).
6. **The shared, per-provider circuit breaker's cross-user blast radius (D129 risk #1) is
   explicitly measured under load.** With ≥2 concurrent lessons, one lesson's provider failures
   are forced past `FAILURE_THRESHOLD` (5/120s, `core/circuit_breaker.py`) and the *other*
   lesson's requests to the same provider are confirmed to fail-fast (`CircuitOpenError`) — this
   is documented as a measured, accepted characteristic (global breaker is intentional per its
   own module docstring) unless the load test shows it materially worse than expected, in which
   case it is registered, not silently absorbed.
7. **No silent failures**: for every failure mode found (S4-1's run, and this story's four
   mandatory categories), the final `lessons`/`lesson_jobs` state is always one of the four legal
   `lesson_jobs.status` values (`pending`/`running`/`completed`/`failed`) with a real `error`
   string on any `failed` row — never a row silently stuck in `running`/`generating` past
   `arq_job_timeout_s`, and never a `logger.warning` as the only trace of a degradation that
   changed the lesson's content or cost.
8. **Every fix ships with a regression test that fails before the fix and passes after
   (RED-GREEN verified, not merely asserted).** Per CLAUDE.md binding rule 7 ("a fix without a
   guard is FIXED-UNGUARDED, not fixed"), no defect closed by this story may cite "None" or
   "DISCIPLINE only" in the register's Guard column unless the review explicitly accepts that
   (matching the D131/D129-style "registered, not fixed" pattern) — and any such acceptance must
   name an owner and a trigger, per binding rule 5.
9. **`reap_stale_generating_lessons` is confirmed correct under concurrent load**, since it is
   the backstop for every failure mode above that leaves a row stuck: with several jobs stuck at
   once, the reaper's `_REAP_BATCH_LIMIT = 100` bound and its `started_at`-based (not
   `created_at`-based, per D91) staleness signal are confirmed not to false-positive-reap a job
   that is merely slow-but-alive, and not to leave more than one reap cycle's worth of stuck rows
   unreaped.
10. **A findings summary is committed** (either as new/updated `D-nn` entries in
    `docs/DEFECT-REGISTER.md`, or a short results doc alongside S4-1's own load-test report)
    listing every failure mode found, whether each was fixed-and-guarded or registered-as-known,
    and cross-referencing the specific regression test for each fix — so S4-7 (on-call runbook)
    and W10-2 (monitoring dashboards) can be written against real, named failure modes rather
    than guesses.

## Scale & Load

<!-- REQUIRED — see docs/SCALE-CONTRACT.md. Answer all six BEFORE writing Tasks/Subtasks.
     "N/A" is valid ONLY with a stated reason. A bare "N/A" is a missing answer.
     One-line test: "What input makes this silently wrong rather than loudly broken?" -->

1. **What is ONE unit of work, and what is its range?**
   One unit of work for this story is **one triaged failure mode** surfaced by S4-1's load test
   (or by this story's own four mandatory categories), carried from observation through register
   entry through fix through regression test. The *range* is genuinely unknown before S4-1 runs —
   this is the story's defining characteristic, stated explicitly rather than guessed at: D129
   (this register) already names the load test itself as never having been run, so the count and
   shape of failures is unmeasured. What is known and bounds the *pipeline's* unit of work
   underneath these failures: one lesson generation = one ARQ job = one LangGraph run over up to
   ~15 nodes, `arq_job_timeout_s=1800` (30 min) as the outer bound, `max_lesson_cost_usd=$3.00` as
   the cost bound, and S4-1's own load shape of 50 concurrent such jobs. Beyond 50 concurrent:
   unmeasured — this story's regression tests should run at a smaller, controlled concurrency
   (2-3, per D129's own recommended first step) plus whatever S4-1 measures at 50, not invent a
   third number.
2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   - `arq_job_timeout_s = 1800s` (whole pipeline) — past it, ARQ cancels the job
     (`asyncio.CancelledError`), and `content_pipeline_job`'s cancellation handler marks the
     lesson `failed` with `error="job cancelled (ARQ timeout or worker shutdown)"` via
     `asyncio.shield` — this is an **explicit failure**, already correct. This story's AC-5 tests
     whether that single 1800s budget is the right shape once many concurrent jobs are competing
     for the same rate-limited providers, since no smaller per-node budget currently exists.
   - `with_retry(max_attempts)` — 3 for critical nodes, 2 for optional (`core/retry.py`). Past
     exhaustion, the last exception propagates — AC-2 confirms this is always an explicit
     `failed` status with a real error message, never silently swallowed.
   - `openai_request_timeout_s=120s` / `openai_image_request_timeout_s=180s` (`config.py:606-613`)
     — per-HTTP-call budgets, explicit `httpx.Timeout` objects (a bare float would silently
     overwrite the `connect=5.0` sub-timeout — D4's own fix). Past them, `httpx.TimeoutException`
     is raised, which `with_retry` classifies as transient and retries up to `max_attempts`.
   - `max_lesson_cost_usd = $3.00` — past it, `check_ceiling()` returns `True`; premium/media
     nodes downshift-and-complete (S2-13), Phase 1 economy nodes terminate-and-flag (accepted gap,
     S2-13 Dev Notes) — both are explicit, not silent. AC-3 re-verifies this specifically under
     concurrent multi-lesson load, since the existing S2-13 tests and D16/D17 closures were all
     single-lesson.
   - `FAILURE_THRESHOLD=5` failures / `FAILURE_WINDOW_SECONDS=120s` (circuit breaker) — past it,
     the breaker opens for `RECOVERY_TIMEOUT_SECONDS=600s` and **every** caller of that provider
     fails fast with `CircuitOpenError` (explicit, not silent) — but this budget's *scope* is
     global-per-provider, not per-lesson (see Q3) — AC-6 measures the cross-lesson consequence.
   - `_REAP_BATCH_LIMIT=100` (`reap_stale_lessons.py`) — bounded on purpose, next scheduled run
     picks up the remainder; not a silent-truncation risk since nothing is dropped, only deferred.
3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   - `arq_job_timeout_s`, `with_retry` attempts, per-provider HTTP timeouts: **per job / per
     provider call** — correctly scoped, unaffected by concurrency.
   - `cost:{lesson_id}` (Redis key, `INCRBYFLOAT`): **per lesson** — correctly scoped and already
     atomic under concurrent writers to the *same* lesson (unlikely) and safe across *different*
     lessons (independent keys).
   - `circuit:{provider}:*` (Redis keys): **per provider, GLOBAL across every lesson and every
     user** — this is the one limit in this story's scope whose scope is a genuine cross-tenant
     risk, named explicitly by D129 risk #1 and re-measured by AC-6. It is not a bug to fix
     unilaterally (the breaker's own docstring states this is intentional — detecting an unhealthy
     *provider*, not a per-user signal) but its blast radius must be measured, not assumed.
   - `max_concurrent_generations_per_user=3` (`config.py:292`): **per user** — correctly scoped,
     out of this story's direct fix scope (it is S4-1/router.py's concern) but interacts with
     AC-3's cost-ceiling-under-concurrency test, since it bounds how many of one user's lessons
     can be simultaneously accumulating cost.
   - `RATE_LIMIT_STORAGE_URL` defaulting to `memory://` (D49): **per-replica**, not per-deployment
     — silently multiplies every ceiling by replica count. Out of this story's direct fix scope
     (S4-4 owns rate limiting) but is a precondition this story's load test must run against a
     Redis-backed limiter, or its concurrency numbers are meaningless the moment a second replica
     exists.
4. **Which reads and writes are UNBOUNDED?**
   No new unbounded reads/writes are introduced by this story itself (a triage-and-fix story adds
   register entries and regression tests, not new query paths) — but two already-registered
   unbounded reads are directly load-bearing for this story's own verification and must not be
   silently re-introduced by any fix: **D115** (the embedded `lessons` relation on
   `content/router.py`'s chapter list has no `.limit()` on the embedded side — if a fix here adds
   any new admin/reporting query to summarize triage findings, it must carry its own bound or
   `# BOUNDED:` justification per `tests/unit/test_unbounded_queries.py`) and the reaper's own
   `_REAP_BATCH_LIMIT=100` (AC-9 confirms this bound holds under this story's own induced-failure
   load, not just nominal load). Any regression test that queries `lesson_jobs`/`lessons` across
   the concurrent test's N lessons must use an explicit `.limit()`/`.eq(lesson_id, ...)`, never a
   bare `.select("*")` over the whole table.
5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   `FAILURE_THRESHOLD=5`/`FAILURE_WINDOW_SECONDS=120s` and `RECOVERY_TIMEOUT_SECONDS=600s` were
   sized (per `core/circuit_breaker.py`'s own docstring, PRD §14) against **single-lesson,
   single-provider-call** failure behavior — never re-derived against N concurrent lessons all
   calling the same provider. Under 50 concurrent lessons, a genuine transient provider blip
   (not an outage) could plausibly generate 5 failures across 5 *different* lessons within 120s
   far more easily than one lesson alone ever could, opening the shared breaker for 10 minutes
   for every concurrent user — a materially different regime than the threshold was tuned for.
   This story's AC-6 is exactly the re-derivation this cap has never had; if the load test shows
   the threshold trips too easily under real concurrency, that is this story's most likely
   concrete fix (e.g. a per-provider threshold re-tuned against measured concurrent-call failure
   rates, not a guess) — register it (`D-nn`) rather than silently bumping the constant.
   `arq_job_timeout_s=1800s` was sized (per its own settings validator's comment) against
   `extract_timeout_cap_s + 300`, i.e. against one lesson's own worst-case extraction time — it
   has never been re-derived against provider response-time degradation under concurrent load
   (AC-5's subject).
6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   Two check-then-act sequences already registered as unsafe are directly in this story's blast
   radius and must not be treated as newly discovered: **D45** — the `(chapter_id, tier)`
   idempotency pre-check-then-insert has no UNIQUE constraint, so concurrent identical requests
   can both bill (accepted-bounded, not fixed, per its own register entry — out of this story's
   fix scope, S1-14/router.py's, but directly relevant to what this story's concurrent load test
   will observe and must not misattribute as a *new* pipeline-reliability bug). **The circuit
   breaker's own read-then-conditionally-write HALF_OPEN promotion** (`is_circuit_open_inner`)
   is a check-then-act itself: two concurrent calls both observing `elapsed >= RECOVERY_TIMEOUT`
   could both attempt the promotion `set()` — harmless here since both writes set the same value
   (`HALF_OPEN`), so this is safe by idempotency, not by locking, and should be noted as such
   rather than re-litigated as a new finding. `accumulate_cost`/`check_ceiling` themselves are
   safe: `INCRBYFLOAT` is atomic per key, and `check_ceiling` reads the post-increment total, so
   no lost-update race exists there — AC-3 exists to *confirm* this holds under load, not because
   a defect is suspected in the arithmetic itself (D16's closure already proved the arithmetic
   real).

## Tasks / Subtasks

- [ ] **Task 1 — Pre-flight: confirm S4-1 (5-1) has run and its raw output is available (AC: #1)**
  - [ ] 1.1 Read S4-1's committed load-test results (log output, Sentry/Langfuse traces, or the
        results doc S4-1's own AC requires). If S4-1 has not yet run, this story cannot proceed
        past Task 2 (see Dev Notes "Sequencing" and "Living checklist") — stop and flag the
        blocker rather than inventing failures to fix.
  - [ ] 1.2 Extract every distinct failure signature from S4-1's run: exceptions raised, jobs
        that timed out, jobs that finished with unexpected final state, cost discrepancies.

- [ ] **Task 2 — Triage: register every distinct failure from S4-1 BEFORE fixing anything (AC: #1, #8)**
  - [ ] 2.1 For each distinct failure signature from Task 1, write a new `D-nn` entry in
        `docs/DEFECT-REGISTER.md` following the existing table format (evidence, severity, fix
        plan, guard) — evidence and severity filled in immediately; fix plan/guard filled in as
        Tasks 3-6 close each one.
  - [ ] 2.2 Cross-check each new entry against already-open entries this session found (D129,
        D45, D49, D131) so a failure is never double-registered under a new number when it is
        actually a known, already-scoped risk materializing (per CLAUDE.md binding rule 5's
        "do not re-register, cite" convention, `DEFECT-REGISTER.md:599`).

- [ ] **Task 3 — Mandatory checklist item: retry exhaustion under load (AC: #2, #8)**
  - [ ] 3.1 Write a controlled test (real Redis via fakeredis or the test harness's existing
        pattern, provider mocked to always return retryable 503/429) that forces
        `with_retry`'s `max_attempts` to exhaust for a critical node, under 2-3 concurrent lessons
        (per D129's recommended controlled-first-step scale).
  - [ ] 3.2 Confirm the resulting `lesson_jobs`/`lessons` row lands on an explicit `failed` status
        with a real error string — not a hang, not a silently-retried-forever loop (ARQ's own
        `max_tries=3` at the job level is a second, coarser retry layer above `with_retry`'s
        per-call layer — confirm the two do not compound into an unexpectedly long total wall
        time under load, and document the actual worst case if they do).
  - [ ] 3.3 If a real gap is found (e.g. the two retry layers interact in a way that silently
        multiplies total attempts far beyond either layer's own stated budget — the same shape
        as D4's already-closed "9 requests per logical call" defect, but at the ARQ layer instead
        of the SDK layer), register and fix with a regression test; if no gap is found, note the
        confirmation in the D-nn entry from Task 2 (or a new entry if this genuinely is a new,
        not-from-S4-1 finding, per the mandatory-checklist framing in the story's Background).

- [ ] **Task 4 — Mandatory checklist item: cost ceiling mid-flight under concurrency (AC: #3, #8)**
  - [ ] 4.1 Write a controlled concurrent test: N lessons (start at 2-3, scale toward S4-1's
        measured concurrency) each seeded in Redis just under `max_lesson_cost_usd`, each making
        one more real-shaped charge that crosses the ceiling independently and simultaneously.
  - [ ] 4.2 Confirm each lesson's downshift-or-terminate decision is made against *its own*
        `cost:{lesson_id}` key only (no cross-lesson bleed — the atomic per-key `INCRBYFLOAT`
        should already guarantee this; this task is confirmation, not new implementation, unless
        a gap is found).
  - [ ] 4.3 Confirm `lesson_jobs.cost_usd` (D86's fix) is read-before-clear and correctly
        persisted for every one of the N concurrent lessons, including the ones that fail via
        `cost_ceiling_exceeded:` — not just the completing ones.
  - [ ] 4.4 If a gap is found, register and fix with a regression test using the REAL
        `accumulate_cost`/`check_ceiling` functions against fakeredis (D16's own lesson: a test
        that stubs `check_ceiling` to a fixed return value cannot distinguish a real ceiling trip
        from a false one).

- [ ] **Task 5 — Mandatory checklist item: Redis connection drops under load (AC: #4, #8)**
  - [ ] 5.1 Re-run D19's own closed regression tests
        (`test_redis_errors_are_retried_then_succeed`, `test_is_circuit_open_fails_open_on_a_write_failure_too`,
        `test_redis_failure_does_not_open_the_breaker`) but under concurrent multi-lesson load
        rather than single-call isolation, to confirm the fix generalizes.
  - [ ] 5.2 Simulate a mid-run Redis connection drop (forced `ConnectionError`/`TimeoutError` from
        the redis client) while 2-3 lessons are concurrently reading/writing `circuit:{provider}:*`
        and `cost:{lesson_id}` keys; confirm every in-flight lesson fails open on the breaker
        check (continues rather than blocking) and that a failed cost read/write degrades per
        `accumulate_cost`'s and the completion path's existing try/except-and-degrade pattern
        (never crashes an otherwise-successful node).
  - [ ] 5.3 If a gap is found (e.g. a Redis drop during the HALF_OPEN promotion write under
        concurrent access), register and fix with a regression test mirroring D19's own
        mutation-verified pattern (9/9 caught).

- [ ] **Task 6 — Mandatory checklist item: node timeout under load (AC: #5, #8)**
  - [ ] 6.1 Write a controlled test where a provider mock responds slowly (not erroring — e.g.
        90-150s, inside `openai_request_timeout_s=120s` for some calls, past it for others) under
        concurrent load, and observe whether `arq_job_timeout_s=1800s`'s all-or-nothing outer
        bound produces acceptable behavior or whether individual slow nodes should have their own
        budget distinct from the whole-pipeline timeout.
  - [ ] 6.2 If the load test (S4-1) or this task's own controlled scenario shows the current
        two-tier timeout shape (per-HTTP-call + whole-pipeline) is inadequate under real
        concurrent-provider-latency conditions, register the gap as a `D-nn` with an explicit
        owner and trigger (per binding rule 5) even if a full per-node timeout budget is deferred
        past this story — do not silently ship a "seems fine" conclusion without the test that
        earned it.
  - [ ] 6.3 If a fix is warranted and scoped small enough for this story (e.g. a per-node
        `asyncio.wait_for` wrapper around the highest-risk premium nodes), implement it with a
        RED-GREEN-verified regression test; if the fix is a larger design change (a full per-node
        timeout framework), register it and hand off rather than half-implementing it here.

- [ ] **Task 7 — Circuit breaker cross-user blast radius under load (AC: #6, #8)**
  - [ ] 7.1 With ≥2 concurrent lessons against the same provider, force ≥5 failures from one
        lesson's calls within the 120s window and confirm the *other* lesson's calls fail fast
        (`CircuitOpenError`) rather than each independently retrying against a dead provider.
  - [ ] 7.2 Document this as either (a) a measured, accepted characteristic — the breaker is
        deliberately global per its own module docstring — with a note in D129's entry that this
        risk has now been measured, not just hypothesized; or (b) if the measured blast radius is
        materially worse than expected (e.g. it silently fails *every* subsequent call rather than
        fast-failing visibly), register and fix.

- [ ] **Task 8 — Reaper correctness under concurrent stuck-row load (AC: #9)**
  - [ ] 8.1 With several lessons deliberately left stuck (via Tasks 3-7's forced failures, if any
        genuinely produce a stuck-not-failed row) or synthetically seeded, run
        `reap_stale_generating_lessons` and confirm it reaps all of them within
        `_REAP_BATCH_LIMIT=100` and does not false-positive-reap a merely-slow-but-alive job
        (D91's own risk).
  - [ ] 8.2 If `_REAP_BATCH_LIMIT=100` proves too small for the number of stuck rows this story's
        own failure-forcing produces (unlikely at 2-3-lesson controlled scale, possible at S4-1's
        50-lesson scale), register a `D-nn` re-deriving the bound rather than silently raising it.

- [ ] **Task 9 — Close out: findings summary and register reconciliation (AC: #10)**
  - [ ] 9.1 Confirm every `D-nn` entry opened in Task 2 (and any opened during Tasks 3-8) has
        either a Guard column citing a real, RED-GREEN-verified regression test, or an explicit
        "registered, not fixed" rationale with owner and trigger (matching the D131/D129 pattern)
        — never a blank Guard column with no rationale.
  - [ ] 9.2 Run the full existing regression suite (`pytest apps/api/tests`) to confirm zero
        newly-introduced regressions, reporting the before/after pass count exactly as prior
        closed entries in this register do (e.g. D78's "52 failed/2062 passed/86 skipped before,
        52 failed/2063 passed/86 skipped after" convention) — not a vague "tests pass" claim.
  - [ ] 9.3 Update `docs/dev1-tracker.md`'s Sprint 4 section per the Dev 1 Sprint Tracker
        Auto-Update Rule (checkbox, dashboard, header date) once this story is complete.

## Dev Notes

- **Living checklist, not a final list.** This story's Tasks/Subtasks section is written against
  what is knowable *before* S4-1 (5-1) has run: the four named risk categories from the tracker's
  one-line AC, plus every already-registered concurrency risk this session's research surfaced
  (D129, D45, D49, D19-closed, D131). Once S4-1 actually executes and produces real failure data,
  this section must be revisited and extended with the *actual* failures observed — Task 2 exists
  specifically to force that update to happen through the register (a durable, reviewable record)
  rather than through silent edits to this file's own checklist. Treat every subtask under Tasks
  3-8 as the mandatory-minimum floor, not the ceiling, of what this story covers.
- **Existing reliability machinery this story extends, not rebuilds:**
  - `with_retry()` (`apps/api/app/core/retry.py`) — exception classification for OpenAI SDK (D3),
    SDK-vs-decorator retry-count conflict (D4), Redis exception shadowing (D19, closed), httpx
    protocol errors (D20). Backoff: `wait = (2**attempt) + random.random()`, full jitter.
  - `core/circuit_breaker.py` — per-provider (global scope), Redis-backed, `FAILURE_THRESHOLD=5`/
    `FAILURE_WINDOW_SECONDS=120`/`RECOVERY_TIMEOUT_SECONDS=600`. `is_circuit_open()` fails open on
    a Redis read failure (D19's fix). `guard_breaker()` sits *outside* `with_retry` so one logical
    call records exactly one breaker outcome regardless of internal retry count (Story 2-32 AC-3)
    — excludes `CircuitOpenError` and `CostCeilingError` from counting as provider failures.
  - `core/cost_tracker.py` — `accumulate_cost()` (atomic Redis `INCRBYFLOAT`, `cost:{lesson_id}`
    key, 24h TTL refreshed on every write) and `check_ceiling()` (reads current total, compares to
    `settings.max_lesson_cost_usd=$3.00`). Called from exactly 4 sites (D50): the LLM provider
    (`providers/llm/openai.py:343`), embeddings (`providers/embeddings/openai.py:175`), TTS and
    image generation (`graph.py:3465`/`:3719`). D10/D16/D17 (all closed) cover unpriced-model
    fail-open, stubbed-vs-real-arithmetic test gaps, and `None`/negative token count crashes.
  - The ARQ job / checkpoint pattern (`apps/api/app/workers/jobs/content_pipeline.py`,
    `apps/api/app/modules/content/pipeline/graph.py`): each node writes `last_node` +
    `node_outputs[node_name]` to `lesson_jobs` after completing; on ARQ retry (`max_tries=3`,
    `workers/main.py:132`), each node's own checkpoint read (`node_outputs.get(node_name)`) skips
    re-running if already cached — confirmed present in `extract_node`, `structure_node`,
    `chunk_node`, `embed_node`, `lesson_planner_node` (grep hits at `graph.py:275,513,583,663,775,
    889,945,1149,1461`). The `attempt = f"{job_id}:{job_try}"` LangGraph `thread_id` uniquifier
    (Story 2-28 AC-5, `content_pipeline.py:118`) is separate from the checkpoint key space — it
    scopes only `MemorySaver`'s in-process state, never `node_outputs`'s
    `f"{node}:{section_id}"` keys, so a retry never re-bills a completed section.
  - `reap_stale_generating_lessons` (`apps/api/app/workers/jobs/reap_stale_lessons.py`, D53/D91) —
    the backstop for any job that dies without reaching `content_pipeline_job`'s own except
    blocks (OOM, container eviction, deploy). Uses `lesson_jobs.started_at` when available,
    falling back to a `2x arq_job_timeout_s` queue-wait-inclusive bound.
- **Cost ceiling behavior is NOT uniform across node types** — this is load-bearing for AC-3 and
  worth restating precisely: premium/media nodes (`lesson_planner`, `slide_generator`, `tts_node`,
  `image_generator`) downshift to a cheaper model/provider and complete the lesson (S2-13); Phase 1
  economy nodes (`summarise_segment`, `quiz_generator`, `segment_complexity`, `jargon_extractor`,
  `intervention_msgs`, `narration_script`) terminate-and-flag instead, because `llm_mini` is
  already the cheapest configured tier with nothing to downshift to — an explicitly accepted,
  documented deviation from CLAUDE.md §14's literal "never abort" wording (S2-13 Dev Notes,
  `dev1-tracker.md:744`). Any AC or test in this story that assumes uniform downshift-never-abort
  behavior across all node types would be wrong on Phase 1 nodes specifically.
- **Testing standards summary:** every regression test added by this story must (a) exercise the
  REAL `accumulate_cost`/`check_ceiling`/`is_circuit_open`/`with_retry` functions against
  fakeredis or the project's existing Redis test harness — never a stub that returns a
  hand-picked value the test then merely echoes back (D16's own closed-defect lesson); (b) be
  RED-GREEN verified by reverting the fix and confirming the new test fails for the *predicted*
  reason before restoring it (D19's and D78's own closure convention); (c) run under the
  project's existing concurrency-test patterns if one exists in `tests/unit/` (search for
  existing `asyncio.gather`-based concurrent test fixtures before inventing a new harness); (d)
  report a full before/after regression count, not just "tests pass" (binding rule 1 — CI scope
  is repo-wide, not touched-files-only).

### Project Structure Notes

- **Epic-5's own spec document (`docs/bmad/epics/epic-5-platform-core.md`) names
  `backend/routers/payments.py` and `backend/workers/notification_worker.py` as the Stripe/email
  file locations.** Verified against the real repo: no `backend/` directory exists at all, and no
  `payments`/`notification` module exists yet under `apps/api/app/modules/` (confirmed —
  `apps/api/app/modules/` contains only `auth`, `content`, `media`, `assessment`, `analytics`,
  `tutor`, `admin`; S4-3 Stripe Checkout has not started). The repo's real, consistent convention
  is `apps/api/app/modules/{module}/router.py` (every existing module follows this — `auth/`,
  `content/`, `admin/`, `assessment/`, `tutor/`, `analytics/`, `media/` all have a `router.py` at
  that exact path). **This story does not touch payments/notifications**, but the epic doc's path
  claims are flagged here per the task's instruction to verify concrete claims against the real
  repo rather than trust an aspirational spec doc — a future S4-3 story picking up the epic's
  Technical Scope table should correct the path there too, not copy it forward.
- This story's own real touch points, all verified present and correctly named:
  `apps/api/app/core/retry.py`, `apps/api/app/core/circuit_breaker.py`,
  `apps/api/app/core/cost_tracker.py`, `apps/api/app/workers/jobs/content_pipeline.py`,
  `apps/api/app/workers/jobs/reap_stale_lessons.py`, `apps/api/app/workers/main.py` (ARQ
  `WorkerSettings`), `apps/api/app/modules/content/pipeline/graph.py` (node checkpoint sites),
  `apps/api/app/config.py` (all the timeout/cost/concurrency settings cited above), and
  `docs/DEFECT-REGISTER.md` (the triage destination for every finding).
- No conflicts found between the dev1-tracker's one-line S4-2 AC and the epic doc — the epic doc
  simply does not go into pipeline-reliability detail at the level the tracker's four named risk
  categories do; the tracker (`docs/dev1-tracker.md`) and this session's own defect-register
  research (D129 especially) are the stronger primary sources for this specific story, not the
  epic's "Production Hardening" section, which covers only the load test's own pass criteria
  (P95 latency, no crashes, Redis memory stable) and not the fix-triage protocol this story is.

### References

- [Source: docs/dev1-tracker.md#Sprint-4] — S4-1 and S4-2 task definitions, S4-2's one-line AC.
- [Source: docs/dev1-tracker.md#Ahead-of-Schedule-Wins] — `core/retry.py`, `core/circuit_breaker.py`,
  `core/cost_tracker.py` build-vs-intended-sprint table.
- [Source: docs/bmad/epics/epic-5-platform-core.md#Production-Hardening] — Load Test / RLS Audit /
  Backups / On-Call Runbook subsections (epic-level framing; verified against real repo per
  Project Structure Notes above).
- [Source: CLAUDE.md#Development-Rules] — binding rules 5 ("a documented limitation is NOT an
  accepted one") and 7 ("a fix without a guard is FIXED-UNGUARDED").
- [Source: docs/SCALE-CONTRACT.md#The-six-questions] — full text behind the Scale & Load section
  above.
- [Source: docs/DEFECT-REGISTER.md#D129] — "no multiple-concurrent-real-user load has ever been
  run against this pipeline" — the entry that explicitly scopes this risk to Sprint 4 and names
  the circuit breaker, D45, and D49 as the three known concurrency risks to test first.
- [Source: docs/DEFECT-REGISTER.md#D45] — `(chapter_id, tier)` idempotency check-then-insert race,
  accepted-bounded not fixed.
- [Source: docs/DEFECT-REGISTER.md#D49] — `RATE_LIMIT_STORAGE_URL` defaulting to `memory://`,
  per-replica not per-deployment scope.
- [Source: docs/DEFECT-REGISTER.md#D19] — closed 2026-07-29, Redis exception shadowing fix; three
  layers (fail-open read+write, transient classification, breaker-exclusion).
- [Source: docs/DEFECT-REGISTER.md#D3-D4] — OpenAI SDK exception classification and SDK-vs-decorator
  retry-count conflict (both closed, `docs/stories/2-32-provider-retry-classification.md`).
- [Source: docs/DEFECT-REGISTER.md#D10-D16-D17] — cost-ceiling fail-open-on-unpriced-model,
  stubbed-test-cannot-distinguish-real-trip, `None`/negative token count crash (all closed).
- [Source: docs/DEFECT-REGISTER.md#D50] — `accumulate_cost` called from exactly 4 sites; render/
  storage cost invisible to the ceiling (accepted-for-Phase-6, not this story's fix scope).
- [Source: docs/DEFECT-REGISTER.md#D53-D91] — reaper job rationale and `started_at`-vs-`created_at`
  staleness-signal history.
- [Source: apps/api/app/core/retry.py] — `with_retry()` decorator, exception classification tables,
  backoff formula.
- [Source: apps/api/app/core/circuit_breaker.py] — `CircuitState`, `FAILURE_THRESHOLD`,
  `RECOVERY_TIMEOUT_SECONDS`, `is_circuit_open()`, `guard_breaker()`.
- [Source: apps/api/app/core/cost_tracker.py] — `accumulate_cost()`, `check_ceiling()`,
  `CostCeilingError`, `clear_lesson_cost()`.
- [Source: apps/api/app/workers/jobs/content_pipeline.py] — job lifecycle, checkpoint/thread_id
  uniquification, cost-ceiling-vs-generic-failure branching, cancellation handling.
- [Source: apps/api/app/workers/jobs/reap_stale_lessons.py] — `_REAP_BATCH_LIMIT`,
  `_QUEUE_WAIT_MULTIPLIER`, staleness-signal precedence.
- [Source: apps/api/app/workers/main.py] — `WorkerSettings.max_jobs=5`, `job_timeout`,
  `max_tries=3`, `keep_result_seconds=86_400`.
- [Source: apps/api/app/config.py] — `arq_job_timeout_s=1800`, `openai_request_timeout_s=120`,
  `openai_image_request_timeout_s=180`, `max_lesson_cost_usd=3.00`,
  `max_concurrent_generations_per_user=3`, `extract_timeout_cap_s` validator invariant.
- [Source: apps/api/tests/unit/test_retry.py] — existing retry-classification test suite to
  extend, not replace.
- [Source: apps/api/tests/unit/test_unbounded_queries.py] — CI source-scan guard any new query
  added by this story's fixes must satisfy.
- [Source: docs/stories/2-32-provider-retry-classification.md] — prior story covering the
  OpenAI-exception-classification defect this story's Task 3 re-verifies under load.

## Sprint 4 Sequencing

- **Branch:** `sprint4/s4-2-reliability-fixes`
- **Depends on:** **5-1** (S4-1, the 50-concurrent-lesson load test) — hard dependency, not a
  soft one: this story's entire concrete scope (Task 1, Task 2) is triaging *S4-1's own output*.
  This story cannot meaningfully start beyond Task 2's checklist-only items (Tasks 3-8's mandatory
  categories can be scoped and even test-scaffolded in parallel, per Dev Notes, but Task 2's
  register entries and this story's completion both require S4-1's real run to have happened).
- **Blocks:** **5-7** (S4-7, the on-call runbook) — its AC requires "5 most likely failure
  scenarios with step-by-step resolution" and explicitly lists scenarios ("ARQ job stuck, cost
  ceiling breach mid-pipeline, Redis unreachable... pipeline node 500-loop") that are exactly this
  story's four mandatory categories; writing a runbook before this story's triage is done would
  be guessing at failure modes rather than documenting real ones. Also informs **W10-2**
  (monitoring dashboards / alerts for pipeline failures and cost-ceiling breaches) and **W10-4**
  (first real paying-user job monitored live) at Week 10, though neither is blocked outright since
  both are scheduled after this story regardless.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

- **AC1 (partial), 2026-09-04**: two real failures found via S4-1's runs #9/#10 and triaged per protocol (registered before fixed):
  - **D152** — the load-test harness itself was deleting disposable test users (cascading away their lessons) while some real ARQ pipeline jobs were still running, corrupting real, paid, in-flight generation work. Fixed: `_wait_for_lessons_terminal()` confirms every lesson's real terminal status (via service-role API, immune to test-user token expiry) before cleanup proceeds; if a 1-hour backstop is hit, cleanup is explicitly skipped rather than risk destroying in-flight work. PR #185.
  - **D153** — Phase A's reported "50% upload failure rate" was never random: 100% of large (~19.7MB) book uploads failed (`httpcore.WriteError`, a dropped TLS connection), 0% of small-file uploads did. Root cause: the storage upload call had zero retry protection, unlike every other network call in this codebase. Fixed: wrapped with the existing `@with_retry(max_attempts=3)`. PR #186.
  - Remaining AC1 work: the real 20-25 minute (P50/P95) pipeline completion time under 50-concurrent load (vs. the 15-minute target) is D129's own headline finding, not a new D-nn under this story — tracked there, not duplicated here.
- **AC2, 2026-09-04**: retry exhaustion was ALREADY correctly implemented (every path that exhausts `with_retry` and propagates results in `lesson_jobs.status='failed'` + `lessons.status='failed'` with a real, non-empty error, per the existing `test_failure_paths_write_schema_valid_status` parametrized suite) — this AC's specific, previously-unverified claim was "under concurrent load," which the single-lesson tests didn't cover. Added `test_concurrent_retry_exhaustion_across_two_lessons_does_not_cross_contaminate` (`test_timeout_contract.py`): two lessons' retries exhaust simultaneously (sharing one Supabase client mock, matching the real single-process/many-concurrent-jobs deployment shape), asserts both independently reach `failed` with correctly-attributed, non-cross-contaminated error/cost data. Mutation-verified: temporarily made the failure-cost write ignore its real per-lesson value (hardcoded `999.0`), confirmed the test reddens, reverted cleanly. No code fix needed — a confirming test, not a bug fix.
- **AC3, 2026-09-04**: `accumulate_cost`'s atomicity claim ("INCRBYFLOAT is atomic, safe under concurrent workers") had never actually been exercised by a real-concurrency test anywhere in this codebase — every existing cost-tracker test used a mocked `AsyncMock`, which has no shared state to corrupt in the first place and so cannot prove or disprove a race. Added two real-Redis-arithmetic tests to `test_cost_tracker.py` (via `fakeredis.aioredis`, the same pattern `test_cost_ceiling_failopen.py` already established): `test_accumulate_cost_never_loses_an_update_under_real_concurrency` (50 truly-concurrent charges to one lesson sum exactly, proving no lost updates) and `test_concurrent_lessons_cost_accumulation_does_not_cross_contaminate` (two different lessons' concurrent charges against one shared Redis instance stay fully isolated). Mutation-verified: temporarily replaced the real `INCRBYFLOAT` with a naive read-modify-write (GET, add in Python, SET, with an `asyncio.sleep(0)` yield to force the race window) — both tests correctly reddened (0.01 instead of the expected 0.5), reverted cleanly. No code fix needed — `accumulate_cost`'s existing implementation was already correct; this closes the gap between "claimed atomic" and "proven atomic."
- **AC4, 2026-09-04**: existing tests (`test_is_circuit_open_fails_open_when_redis_is_down`, `test_is_circuit_open_fails_open_on_a_write_failure_too`, `test_redis_failure_does_not_open_the_breaker`) already proved the fail-open/no-false-failure contract for ONE call against an always-broken mock — none proved it holds when several lessons concurrently share ONE real Redis connection for the same provider's breaker keys while only SOME of those concurrent operations hit a blip. Added `test_concurrent_calls_survive_an_intermittent_redis_blip_for_one_of_them` (`test_breaker_accounting.py`): 10 concurrent `guard_breaker` calls for one provider, all against one real `fakeredis` instance wrapped so every 3rd underlying Redis operation raises a real `ConnectionError` while the rest succeed normally — asserts every call still returns its own correct result and the breaker never incorrectly opens. Mutation-verified: narrowed `_safe_record`'s exception handler from `except Exception` to `except ValueError`, confirmed this NEW test reddens (a Redis blip during `record_success` now crashed the whole concurrent batch) — notably, none of the three existing single-call tests caught this same mutation, since none of them exercise the success-path recording under concurrency. Reverted cleanly. No code fix needed — `_safe_record`'s existing broad exception handling was already correct; this closes a real, previously-unverified gap between "proven for one call" and "proven under real concurrent sharing."
- **AC5, 2026-09-04**: registered as **D154**, not fixed, per this AC's own explicit permitted disposition. Checked all three named failure shapes: "job legitimately still running" (confirmed by S4-1 run #10's own real data — P50=20.6min/P95=25.2min, both under the 1800s ARQ ceiling), "job incorrectly cancelled" (already correctly handled, `test_cancelled_job_marks_lesson_failed_and_reraises`), "job silently stuck" (already correctly handled by the reaper, `test_reap_stale_lessons.py`, 6 tests). The real, confirmed gap: no timeout budget exists between a single provider call (120-180s) and the whole pipeline (1800s) — for the entire 20-25 minutes a real lesson is generating, there's no signal for which node it's in or whether that node is progressing normally. Diagnostic granularity gap, not a correctness defect — no lesson was ever observed silently stuck or incorrectly killed. Fixing it means deciding, per node, what "too slow" means and what to do about it — a real design decision, not a bug fix; registered with owner TBD and pointed at W10-2 monitoring (not yet built) as the more natural home than a new ad-hoc per-node timeout mechanism.
- **AC6, 2026-09-04**: the shared, per-provider circuit breaker's cross-user blast radius (D129 risk #1) was previously only asserted via a mocked `is_circuit_open` side_effect sequence standing in for "some other call tripped it" — never actually measured end-to-end with two distinct lessons and real Redis state. Added `test_one_lessons_failures_trip_the_breaker_for_a_different_lesson_too` (`test_breaker_accounting.py`): lesson A's 5 real logical calls exhaust retries and really trip the breaker via real, unmocked `record_failure`/`is_circuit_open` against real `fakeredis` state; lesson B (different lesson_id, fresh provider instance, a client that would happily succeed) then gets a real `CircuitOpenError` on its very FIRST request, its own SDK client never even reached. Mutation-verified: made `record_failure` a no-op, confirmed the test reddens (breaker never trips, lesson B wrongly succeeds), reverted cleanly. Confirms the documented, intentional characteristic (global breaker, not per-lesson) holds for real, exactly as designed — not materially worse than expected, so no new defect; the existing D129 risk #1 citation stands as the record of this accepted tradeoff.

**Story 5-2 status as of 2026-09-04: AC1-AC6 addressed** (AC1 partial — D129's own capacity numbers are the headline finding, tracked there rather than duplicated here; AC2-AC6 each closed with either a real fix + guard, or a mutation-verified confirming test, or a registered-not-fixed D-nn per each AC's own permitted disposition — every confirming test above was mutation-checked, which is AC8's own requirement, applied throughout rather than as a separate pass). **Not yet done**: AC7 (an explicit audit that every failure mode found here always resolves to one of the four legal `lesson_jobs.status` values with a real error, never a silent `logger.warning`-only degradation — likely already true given AC2-AC6's own findings, but not yet stated as its own checked item), AC9 (`reap_stale_generating_lessons` confirmed correct under concurrent load specifically — existing tests cover single-job staleness detection, not several stale jobs reaped at once), AC10 (the final findings summary tying this story's entries together for S4-7/W10-2 to build on). None of this story's branches (D152/#185, D153/#186, AC2/#187, AC3/#189, AC4/#190, AC5/#191, AC6/this branch) have merged to `main` yet — review/merge order determines whether the D149/D152 numbering collision with PR #188 (independently registered by another dev for unrelated work) needs manual renumbering.

### File List
