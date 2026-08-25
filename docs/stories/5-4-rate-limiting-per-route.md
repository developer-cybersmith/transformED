# Story 5-4 — Rate limiting (slowapi middleware) — per-route limits

Status: done

## Story

As Dev 1 (platform/API owner),
I want the per-user upload rate limit on `POST /api/content/lessons` to be verifiably enforced —
correctly keyed by the caller's identity and correctly scoped across every API process the
deployment is actually running, not just on a laptop with one process —
so that a single user cannot burst-upload past the intended ceiling, one caller cannot lock out
every other user sharing an egress IP, and the "5/minute" number printed in docs and code is the
real ceiling in production, not a number that silently multiplies by however many processes
happen to be running that day.

## Acceptance Criteria

**Pre-existing behavior this story locks down (already implemented — see Dev Notes; treat any
regression here as a P0 defect, not a fresh feature):**

1. `POST /api/content/lessons` is decorated `@limiter.limit("5/minute", key_func=_get_user_key)`
   (`apps/api/app/modules/content/router.py:692`). A 6th upload from the same authenticated user
   within a rolling 60-second window returns HTTP `429` with a `Retry-After` header present and
   parseable as an integer number of seconds. Covered today by
   `tests/unit/test_content_router.py::test_upload_lesson_429_rate_limit` — this story adds no
   new test for the base case, it re-runs and asserts this one still passes.
2. The limiter key for any request carrying a valid Supabase-issued bearer token (HS256 or
   ES256/RS256) is `f"user:{sub}"` — never the caller's IP — so two different authenticated users
   never share a bucket and one authenticated user's burst never throttles another's. Covered
   today by `tests/unit/test_rate_limit_key.py` (9 tests, including the D52 and D64 regression
   tests). Only a request with **no** usable identity (missing/malformed/forged token) falls back
   to IP-keying, which is the documented, intentional degradation for anonymous traffic — not a
   gap this story closes.

**New work this story actually delivers:**

3. **[Review Finding — reworded 2026-08-25, was overclaiming delivered state]** The rate limiter's
   storage backend correctly enforces one combined ceiling per shared `storage_uri`, not one per
   `Limiter` instance — verified by constructing two `Limiter` instances against the same
   Redis-backed `storage_uri` (simulating two API processes) and confirming a burst split across
   both is throttled at the combined configured limit, not the limit multiplied by instance count.
   **This proves the mechanism; it does not by itself mean `RATE_LIMIT_STORAGE_URL` is actually
   pointed at a real shared Redis instance in any deployed environment today** — that rollout is
   explicitly still open (Task 2, blocked on ADR-001 §4's Redis-location decision) and is not part
   of what this AC claims.
4. App startup (`lifespan()` in `apps/api/app/main.py`) raises and refuses to start if
   `RATE_LIMIT_STORAGE_URL` resolves to the `memory://` default while `settings.debug` is
   `False` — converting D49's silent per-process capacity multiplication into a loud, explicit
   deploy-time failure, mirroring the existing `assert_required_buckets` startup-assertion
   pattern (`apps/api/app/main.py`, AC-7/Story 2-0/D1).
5. A guard test proves AC4 fires: constructing the app (or calling the extracted assertion
   function directly) with `RATE_LIMIT_STORAGE_URL` unset and `debug=False` raises; with
   `debug=True` or a non-`memory://` URL it does not. Mutation-checked — deleting the assertion
   must redden this test (CLAUDE.md binding rule 7: "a fix without a guard is FIXED-UNGUARDED").
6. `docs/DEFECT-REGISTER.md`'s D49 row is updated from open/"to add" to closed-and-guarded,
   citing this story's branch and the new test from AC5 — per the register's own convention that
   every other closed defect follows (e.g. D52, D64's rows).

## Scale & Load

1. **What is ONE unit of work, and what is its range?**
   One unit is a single rate-limit-checked HTTP request against a decorated route. Two routes
   currently carry a decorator, both in `content/router.py`: `POST /lessons` (this story's AC
   scope) at `5/minute` per user, and `POST /books/{book_id}/chapters/{chapter_id}/generate`
   (`router.py:1056`) at `3/minute;20/hour` per user — already shipped, out of this story's AC
   scope, but sharing the exact same `limiter` object and `storage_uri`, so AC3/AC4's fix changes
   its enforcement scope too, for free. Range for the upload route: 0 requests/minute (idle) up
   to the `5/minute` cap per user, unbounded in *aggregate* across users today (no per-deployment
   or per-instance total-throughput ceiling exists — only a per-user one). No real concurrent
   multi-user load has ever been measured against this endpoint — confirmed by `docs/dev1-tracker.md`'s
   S4-1 (50 concurrent generations) still being unchecked `[ ]`. **[Review Finding — corrected
   2026-08-25]** An earlier draft of this section cited a "D129" register entry for this claim;
   no such row exists in `docs/DEFECT-REGISTER.md` (confirmed by direct search) — removed rather
   than left as a false citation. The underlying claim above stands on the tracker line alone. This
   story's Scale & Load answers are therefore analytic (read from the code and the `fly.toml`
   deploy config), not drawn from a load test — S4-1, when it runs, is the first real measurement
   and may reveal this story's Redis-storage fix needs its own tuning (e.g. `limits` library
   Redis round-trip latency under the concurrency S4-1 will generate).

2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   - `"5/minute"` per user on upload — fixed regardless of how many books a user actually has
     queued or how large their files are. Past it: explicit `429` + `Retry-After` (slowapi's
     built-in `_rate_limit_exceeded_handler`, wired in `main.py:208`) — this is the *correct*
     pattern (explicit error, not silent truncation) and this story does not change it.
   - `RATE_LIMIT_STORAGE_URL` defaulting to `memory://` is itself a fixed-but-wrong-scoped
     budget: past "more than one API process," nothing errors and nothing warns above whatever
     log level the process happens to run at — the ceiling simply becomes `5 × (number of
     processes)/minute` per user, silently. This is the same *shape* of failure CLAUDE.md names
     as the signature defect class ("cheap wrong," not "expensive wrong," so the $3.00 cost
     ceiling can't catch it) even though the concrete mechanism here is a rate limit, not a token
     window. AC4 turns this from a silent multiplication into an explicit, loud, deploy-time
     failure — the fix this story actually contributes.
   - `MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024` (`router.py:58`) bounds each individual upload
     independent of the rate limit — not this story's concern, but worth naming so the two
     budgets (per-request size, per-minute count) aren't conflated: a user at the rate ceiling can
     still push up to `5 × 50 MB = 250 MB` of upload traffic per minute, a number nobody has
     explicitly sized against Fly's `shared-cpu-2x` API VM (`fly.toml`) — flagged, not fixed, here.

3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   Intended scope: **per user, per deployment** (one global 5/minute ceiling per authenticated
   user, no matter which process answers the request). **Actual scope today: per user, per
   *process*** — this is exactly D49. The deployment is Fly.io (`fly.toml`, `primary_region =
   "bom"`), not Railway — Railway is retired (`fly.toml`'s own header comment: "Railway is
   retired — railway.toml removed 2026-08-14"; confirmed no `railway.toml` exists anywhere in the
   repo outside stale worktree copies). `fly.toml`'s `[http_service]` block sets
   `min_machines_running = 1` for the `api` process group with `auto_start_machines = true` and no
   stated maximum — ADR-001 §2 explicitly characterizes the API as "bursty and request-scaled," so
   more than one live `api` machine under real load is the expected case, not an edge case. Under
   today's `memory://` storage, each of those machines keeps its own independent in-memory
   counter, so N live machines means the real per-user ceiling is `5×N/minute`, not `5/minute` —
   and a machine restart (routine on Fly) resets that machine's counters to zero regardless. AC3
   moves the scope to genuinely per-deployment by pointing every process at one shared Redis
   store — `limits`' Redis backend performs the increment-and-check atomically server-side
   (Lua script), so concurrent processes never under-count each other's requests. Where that
   Redis instance itself lives is still an open question this story does **not** resolve: per
   ADR-001 §4, Redis is "Railway Redis today" pending a decision between Upstash (Mumbai) and Fly
   Redis — this story's Tasks note that dependency explicitly rather than silently assuming
   Railway Redis is still reachable once Railway is fully decommissioned.

4. **Which reads and writes are UNBOUNDED?**
   None, with reason. `_get_user_key` performs one JWT decode per request — O(1), no Supabase
   query, no unbounded loop. The `limits` library backing `Limiter` stores one fixed-size counter
   per `(key, window)` pair with a TTL equal to the window (60s for `5/minute`), so key space
   growth is bounded by (distinct users active in the last window) × (number of decorated
   routes) — self-expiring, not accumulating without bound. This story introduces no new
   Supabase read or write, so `tests/unit/test_unbounded_queries.py`'s source scan is unaffected.

5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   The `"5/minute"` number itself is inherited and **has not been re-derived** for the current
   unit of work — flagged here, not fixed, because re-deriving it is a product decision, not a
   code change this story should make unilaterally. `docs/dev1-tracker.md`'s S1-10 line
   ("Apply `slowapi` rate limit: `\"5/minute\"` per user") predates the book-scale refactor: at
   that time, `POST /lessons` created one `lessons` row and enqueued the full generation pipeline
   per call, so "5 uploads/minute" implicitly meant "5 lesson-generation triggers/minute." Today
   (`router.py`'s own docstring on `upload_lesson`, book-scale Phase 3, Story 1-10): "this creates
   the `books` row and enqueues `book_ingest_job`; it no longer creates a `lessons` row and no
   longer enqueues the generation pipeline" — the unit of work behind the cap changed from "one
   lesson trigger" to "one book ingestion" (cheap: storage + chapter detection, not LLM
   generation) without the `5/minute` figure being revisited anywhere found in this repo. This is
   the same *class* of gap CLAUDE.md's binding rule names for the 50 MB cap ("re-derive every
   inherited cap when the unit of work changes") — surfaced here as a candidate defect-register
   entry for a human product decision, not silently reused nor silently changed by this story.
   By contrast, the generate endpoint's `"3/minute;20/hour"` **was** explicitly re-derived and
   documented against real cost math in the existing D49 register row (~$60/user/hour at the
   $3.00/lesson ceiling, per replica) — the asymmetry between a re-derived cap and an
   un-re-derived one sitting in the same file is itself worth a human's attention.

6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   Within a single storage backend, yes: `limits`' in-memory strategy is a fixed-window counter
   incremented under Python's async single-threaded event loop (no true parallel mutation within
   one process), and `limits`' Redis strategy performs the same check-and-increment as one atomic
   Lua script server-side, so two concurrent requests against the same Redis-backed key can never
   both read a stale count and both pass. What is **not** safe, and is explicitly out of this
   story's scope, is the *separate* check-then-act race this repo already knows about one layer
   up the stack: `generate_chapter_lesson`'s `(chapter_id, tier)` idempotency pre-check
   (**D45**, register) has no database UNIQUE constraint behind it, so two concurrent requests
   that each individually pass the rate limiter can still both insert a `lessons` row and both
   bill. The rate limiter bounds *request rate*; it does not and cannot make that separate insert
   safe — naming this so nobody reads a passing rate-limit test as proof the idempotency race is
   also handled.

## Tasks / Subtasks

- [x] **Task 1 — Confirm and pin down existing behavior (AC: #1, #2)**
  - [x] Ran `tests/unit/test_content_router.py::test_upload_lesson_429_rate_limit` and
        `tests/unit/test_rate_limit_key.py` (full file) against current `main`; both green (10/10)
        before touching anything.
  - [x] Read `apps/api/app/modules/content/router.py:686-706` and
        `apps/api/app/core/rate_limit.py` end to end; confirmed AC1/AC2 pre-existing (decorator at
        `router.py:692`, key func fully covered by D52/D64 regression tests) — not re-implemented.

- [~] **Task 2 — Redis-backed storage for the shared limiter (AC: #3)**
  - [ ] Confirm which managed Redis instance backs `RATE_LIMIT_STORAGE_URL` — **not done in this
        branch, and cannot be from the repo alone.** ADR-001 §4's Redis-location decision
        (Upstash Mumbai vs. Fly Redis) is still open; ops/deploy-config work, out of scope for a
        code branch. Task 3's guard makes the absence of this loud instead of silent in the
        meantime.
  - [ ] Set `RATE_LIMIT_STORAGE_URL` in every deployed environment — **same reason, not done.**
        Deploy-config change tracked wherever this repo's env vars are actually managed, not here.
  - [x] Added a unit test constructing two independent `Limiter` instances against the same
        fakeredis-backed `storage_uri` and asserting a burst split across both is throttled at the
        combined `5/minute`, not `10/minute` — `test_rate_limit_redis_storage.py`, plus a
        `memory://` control case proving the fakeredis test is exercising real cross-instance
        sharing, not some other effect.

- [x] **Task 3 — Startup guard closing D49 (AC: #4, #5)**
  - [x] Added `assert_rate_limit_storage_configured(*, debug, storage_uri=None)` in
        `apps/api/app/core/rate_limit.py`, mirroring `assert_required_buckets` — raises
        `RuntimeError` (citing D49 + ADR-001 §4) when resolved storage is `memory://` and
        `debug` is `False`.
  - [x] Called from `lifespan()` in `main.py`, first in the startup sequence (before Redis/ARQ/
        bucket checks), so a misconfigured deploy fails at boot.
  - [x] Added the guard test (`test_rate_limit_storage_guard.py`, 6 tests) covering the
        explicit-arg and real-env-var paths, the `debug=True` exemption, and a real `redis://`
        URL passing. Mutation-checked: temporarily replaced the guard condition with `if False`,
        confirmed exactly the 3 tests asserting the raise reddened (the 3 non-raising cases
        correctly stayed green), then restored.

- [x] **Task 4 — Close out the register and trackers (AC: #6)**
  - [x] `docs/DEFECT-REGISTER.md`'s D49 row: struck through, marked `CLOSED 2026-08-25`, cites
        this branch and both new test files.
  - [x] `docs/dev1-tracker.md` S4-4 flipped to `[x]`, completion date appended, Quick Status
        Dashboard updated (Sprint 4: Done 0→1, Partial 1→0), header date updated to 2026-08-25.
  - [x] Did not silently correct the stale "not yet configured ✗" line — added an explicit note
        in the tracker entry itself naming the S1-10 discrepancy (see Dev Notes' Process Note).

- [x] **Task 5 — Explicitly out of scope, flagged not fixed (no AC — documentation only)**
  - [x] Noted here (commit message + this file, no PR opened in this session): **D67** (register)
        — `GET /api/media/signed-url` has no `@limiter.limit` decorator at all; this story's AC
        only names `POST /api/content/lessons`. Recommend the team decide whether D67 becomes its
        own Sprint 4 story or stays deferred — not fixed in this branch.
  - [x] Noted: Q5's un-re-derived `5/minute` figure (Scale & Load #5 above) is a defect-register
        candidate for a human product decision — not unilaterally changed here.

### Review Findings

**6-layer `/bmad-code-review` (+2 extra layers per CLAUDE.md's 6-layer gate), 2026-08-25.** 8 parallel subagents (Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter, Story Quality, Test Coverage, AC Completeness, Process Integrity) reviewed branch `sprint4/s4-4-rate-limit-per-route` vs `main`. Findings normalized, deduplicated (several layers independently converged on the same issues — noted per finding), and classified below.

**[Review][Decision] — resolved 2026-08-25:**

- [x] [Review][Decision] Hard-fail startup guard has no rollback/warn-only mode, and no deployed environment currently has `RATE_LIMIT_STORAGE_URL` pointed at real Redis. **Resolved: keep hard-fail.** A silently-wrong rate limit multiplying by replica count is worse than a loud, obvious boot failure that forces the env var to actually get set before the next real deploy — no code change. [`apps/api/app/core/rate_limit.py:93-122`] (source: blind)
- [x] [Review][Decision] Scale & Load Q1 and References cite a phantom `docs/DEFECT-REGISTER.md#D129`. **Resolved: fix this story's wording only** — do not create a new register row (that's broader than this story's scope and affects 3 sibling files). See patch item below. (source: auditor+story-quality+process-integrity, independently confirmed 3×)

**[Review][Patch] — applied 2026-08-25:**

- [x] [Review][Patch] Guard's `storage_uri == "memory://"` exact-string check misses non-canonical variants that still resolve to real, unshared `MemoryStorage`: empty string `""`, case (`"MEMORY://"`), whitespace (`" memory://"`, `"memory:// "`), and suffix (`"memory://foo"`) — **empirically confirmed** (Scale & Load Hunter constructed real `Limiter` instances with each and verified they all build `MemoryStorage` while the guard doesn't raise for any of them). This is D49's exact failure mode surviving through an untested input class — a **scale finding with `observed_behaviour = silent-wrong-result`, which per the Scale Contract's own rule can never be dismissed.** **Fixed:** guard now resolves via `limits.storage.storage_from_string` (the same factory `Limiter` uses) and checks `isinstance(resolved, MemoryStorage)` — closes every variant at once. 5 new parametrized tests. [`apps/api/app/core/rate_limit.py:126-143`] (source: edge+blind+scale[empirical]+test-coverage+process-integrity — 5 independent layers)
- [x] [Review][Patch] No test guards that `assert_rate_limit_storage_configured` is actually **wired into** `main.py`'s `lifespan()` — deleting the call site entirely reddens zero tests (verified: Test Coverage layer literally deleted it and re-ran the full rate-limit suite green). `assert_required_buckets`, the pattern this claims to mirror, has exactly this guard (`test_bucket_manifest.py::test_startup_paths_call_shared_assertion`, a source-scan) — not copied here. **Fixed:** added `test_lifespan_actually_calls_the_guard`, mirroring that exact pattern; mutation-verified (removed the call site, confirmed only this new test reddens). [`apps/api/app/main.py:70`] (source: blind+test-coverage+process-integrity — 3 independent layers)
- [x] [Review][Patch] Guard re-reads `RATE_LIMIT_STORAGE_URL` from `os.environ` independently of the real `limiter` object's own construction (`rate_limit.py:87` and `:110` are two separate reads of the same env var) — a future refactor to one without the other silently reopens D49 with no test to catch it. **Fixed:** both now read one single module-level constant `_RATE_LIMIT_STORAGE_URI`, resolved once at import — true single source of truth. Verified directly by `test_guard_default_is_the_same_value_limiter_was_built_with`. [`apps/api/app/core/rate_limit.py:91,127`] (source: blind+edge+test-coverage)
- [x] [Review][Patch] Mutation check only exercised one direction (guard condition → `if False`, confirmed 3/6 tests redden) — the reciprocal (`if True`, proving the 3 "does not raise" tests are actually discriminating rather than vacuously true) was not performed. **Done:** reciprocal mutation performed — forcing an unconditional raise reddens `test_does_not_raise_when_storage_url_is_a_real_redis_uri` (the debug-mode case is unaffected by this specific mutation since it returns earlier via the separate `if debug: return` guard clause, which is its own trivially-correct short-circuit). [`apps/api/tests/unit/test_rate_limit_storage_guard.py`] (source: blind+test-coverage)
- [x] [Review][Patch] AC3's wording overclaims delivered state: "`RATE_LIMIT_STORAGE_URL` **is set** to a shared Redis-backed store... in every environment" (present tense, stated as accomplished) — but Task 2/Completion Notes correctly admit the actual env-var rollout is NOT done, only the underlying capability + unit test. **Reworded** to describe only what was verified, with the still-open rollout stated explicitly in the same AC rather than only in Task 2. [Story `## Acceptance Criteria` #3]
- [x] [Review][Patch] D67 citation's line number is wrong: story cites "line 341", the real entry is at line 333. Also unflagged: the register has an unrelated, already-CLOSED D67 at line 286 (Sarvam TTS voice-ID) — a genuine ID collision this story's citation doesn't surface. **Fixed** line number; collision noted inline and in `deferred-work.md`. [Story Dev Notes/References, `docs/DEFECT-REGISTER.md:333`]
- [x] [Review][Patch] AC2's own text says `test_rate_limit_key.py` has "8 tests" — actual count is 9 test instances (6 plain + 1 parametrized ×3 cases). **Fixed** in both places this story repeats the count.
- [x] [Review][Patch] AC1's own text requires `Retry-After` to be "present **and parseable as an integer number of seconds**" — `test_upload_lesson_429_rate_limit` (pre-existing, not modified by this story) only asserted header presence, never that its value is `int()`-parseable. **Fixed:** strengthened with `int(resp.headers["Retry-After"]) >= 0`.
- [x] [Review][Patch] `test_two_limiter_instances_share_one_redis_backed_ceiling` (AC3) constructs a generic `Limiter(key_func=get_remote_address, ...)`, not the actual production `app.core.rate_limit.limiter` singleton (which uses `_get_user_key`) — a regression isolated to how the real object is built wouldn't be caught by this test. **Fixed:** added `test_two_limiters_using_the_real_production_key_func_share_one_ceiling`, repeating the same proof with `_get_user_key`.
- [x] [Review][Patch] `docs/DEFECT-REGISTER.md`'s D49 row said "CLOSED" — accurate for the code-level guard, but the disposition text needed to be unambiguous that the per-replica multiplication is **not yet fixed in any live environment**, only guarded against at boot. **Tightened** the disposition text to state this explicitly, and to record the same-day hardening (non-canonical-variant fix) the review itself found.
- [ ] [Review][Patch] Remove/soften the phantom `D129` citation in this story's Scale & Load §1 and References — per the resolved decision above, fix wording here only, no new register row.

**[Review][Defer] — pre-existing, real, not this branch's job:**

- [x] [Review][Defer] `test_rate_limit_redis_storage.py`'s cross-instance test depends on an internal (not a documented public contract) call path of the `limits` library (`RedisStorage.__init__` → `self.dependency.from_url`) — a future `limits` version bump could silently break what the test proves without failing. No cleaner seam exists today. — deferred, pre-existing (third-party library internals)
- [x] [Review][Defer] `test_rate_limit_key.py`'s RS256 path is not independently tested — only ES256 exercises the shared `algorithms=["ES256","RS256"]` branch in `_get_user_key`. Pre-existing test, not touched by this story (AC2 explicitly locks down existing behavior without adding new tests). — deferred, pre-existing
- [x] [Review][Defer] No live-Redis integration test backs the fakeredis-based AC3 test — fakeredis's Lua emulation fidelity to real Redis is assumed, not independently verified against a real instance. Would need a dockerized Redis in CI — a bigger, separately-scoped addition. — deferred, pre-existing
- [x] [Review][Defer] `docs/DEFECT-REGISTER.md` has two unrelated entries both numbered D67 (line 286, CLOSED Sarvam TTS; line 333, this story's media signed-url citation) — a real ID collision in the register itself, not created by this story and not this branch's job to renumber. — deferred, pre-existing

**[Review][Dismiss] — noise, refuted, or already-justified (6):** heavyweight `lupa` dependency (no lighter alternative exists for proving real Lua-based atomic incr — already justified in Dev Notes); the D49/ADR-001 error-message test only pinning two substrings (reasonable minimum bar); the same rationale duplicated across docstring/exception/register/tracker/story (matches this repo's established, intentional cross-referencing convention, confirmed elsewhere in `dev1-tracker.md`/`DEFECT-REGISTER.md`); AC6 (doc-only) having no test (structural — no test framework in this repo asserts markdown content); and two claims that were raised as "unverifiable" (the "full suite passed" claim, and the mutation-check numbers) but were then **independently re-executed and confirmed accurate** by both the Test Coverage and Acceptance Auditor layers — refuted, not real findings.

## Dev Notes

- **The core AC is already implemented and tested — this is the single most important finding of
  this story.** `docs/dev1-tracker.md`'s S4-4 line ("Per-route limits not yet configured on
  pipeline endpoints ✗") is **stale**, confirmed by reading the real files: `router.py:692` already
  carries `@limiter.limit("5/minute", key_func=_get_user_key)` on `POST /lessons`, and
  `tests/unit/test_content_router.py::test_upload_lesson_429_rate_limit` already asserts the exact
  429-plus-`Retry-After` behavior the tracker's own AC line describes. The keying-by-IP regression
  named in this task's brief (**D52**) is likewise **already fixed and guarded** — closed
  2026-08-04, with a second independent regression (renumbered **D64**/D75 across several merges,
  same underlying bug class: an ES256-signed token hitting a hardcoded `algorithms=["HS256"]`
  decode) closed 2026-08-05 — both covered by `tests/unit/test_rate_limit_key.py`'s 9 tests. Do
  not re-implement either; this story's real job is Task 2/3 (D49) plus tightening the tracker.
- **D49 is the one genuinely open, unguarded gap**, and it is not hypothetical: the production
  deploy target is Fly.io (`fly.toml`), whose `api` process group is explicitly documented (ADR-001
  §2) as "bursty and request-scaled" with `auto_start_machines = true` and no fixed replica count —
  meaning more than one live `api` machine is the expected, not the edge, case. Under the current
  `storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URL", "memory://")` default
  (`core/rate_limit.py:87`), each such machine keeps an independent in-memory counter, so the real
  per-user ceiling silently multiplies by however many machines Fly happens to be running.
- **Process note, not a thing to silently fix:** `docs/dev1-tracker.md`'s Sprint 1 line (S1-10)
  reads "Apply `slowapi` rate limit: `\"5/minute\"` per user — **do not defer to Sprint 4**," and
  the tracker's own "Ahead-of-Schedule Wins" table repeats the instruction ("Add per-route limit
  to `POST /api/content/lessons` in Sprint 1 (S1-10)"). The decorator's presence (confirmed above)
  and the router's own docstring ("book-scale Phase 3, Story 1-10") suggest the limit actually
  *was* applied around the S1-10 timeframe, matching the instruction — yet S4-4 exists in the
  tracker as a separate `[ ]` **PARTIAL** task claiming the opposite ("not yet configured"). Two
  tracker entries disagree about the same fact and neither was corrected against the code before
  this story. Flagging this discrepancy rather than silently resolving it in either direction —
  it may indicate the *deferral itself* happened (contradicting the explicit "do not defer"
  instruction) and was then partially walked back, or it may simply be a tracker bookkeeping
  error. Either way, Task 4 corrects the tracker as part of this story's close-out, with the
  discrepancy noted in the PR description rather than papered over.
- **`docs/bmad/epics/epic-5-platform-core.md` does not mention rate limiting anywhere** — its
  "Production Hardening" section covers Load Test, RLS Audit, Backups, On-Call Runbook, and DPDP,
  but slowapi/rate limiting is absent, despite S4-4 being one of Sprint 4's Dev 1 tasks under this
  epic. This story is therefore grounded in the real code + `docs/dev1-tracker.md` +
  `docs/DEFECT-REGISTER.md`, not the epic doc, for anything rate-limit-specific.
- **The epic doc's "Technical Scope" table names `backend/routers/payments.py`** — this path does
  not exist in this repo and does not match its real convention. The actual module layout is
  `apps/api/app/modules/{module}/router.py` (confirmed for `content`, and matching CLAUDE.md's
  own Repo Structure section) — flagged per this story's brief as exactly the kind of
  aspirational/stale path the epic doc can contain; no file at the epic's stated path was touched
  or assumed to exist.
- **Railway is retired; the real deploy target is Fly.io.** CLAUDE.md's Locked Technology Stack
  table still lists "Deploy: Railway + GitHub Actions — railway.toml," and this task's own brief
  assumed Railway Redis — both are now stale relative to `fly.toml` and
  `docs/decisions/ADR-001-india-region-migration-topology.md`, which record Railway's retirement
  (`railway.toml removed 2026-08-14`) and the move to a single Fly app (`hie-api`, `primary_region
  = "bom"`). This story's Scale & Load section is grounded in `fly.toml`, not the stale Railway
  assumption. Redis itself has **not** yet moved off Railway per ADR-001 §4 (still an open
  decision between Upstash Mumbai and Fly Redis) — Task 2 names this dependency explicitly rather
  than assuming a Redis URL is available to hardcode.
- **Testing standards**: this repo's existing rate-limit tests are read-and-mirror candidates —
  `test_rate_limit_key.py` calls `limiter.reset()` between tests to avoid cross-test bucket
  pollution (see its usage in `test_content_router.py`/`test_generate_lesson_endpoint.py`); any
  new test in Task 2/3 should follow the same pattern. Per CLAUDE.md's Defect Register binding
  rule 2, assert an observable outcome (a real 429/Retry-After, a real raised exception) — not
  only a call recorded on a mock.

### Project Structure Notes

- All touched/added code stays inside `apps/api/app/core/rate_limit.py` and `apps/api/app/main.py`
  — both already-established locations, no new module boundary crossed. No change to
  `apps/api/app/modules/content/router.py` is required by this story's AC (the decorator there is
  already correct); if Task 1's read turns up anything unexpected, note it rather than editing the
  router as part of this story.
- New tests belong in `apps/api/tests/unit/` alongside the existing `test_rate_limit_key.py` and
  `test_content_router.py`, matching this repo's `tests/unit/` (fast, mocked-dependency) vs.
  `tests/integration/` (real-dependency) split.
- No Supabase migration, no `packages/shared` contract, and no frontend change is implicated by
  this story — it is entirely a backend config/startup-guard change.

### References

- [Source: apps/api/app/core/rate_limit.py] — the `Limiter` construction, `_get_user_key`, and its
  load-bearing D52/D64 comments.
- [Source: apps/api/app/modules/content/router.py:686-706] — `upload_lesson`, the existing
  `@limiter.limit("5/minute", key_func=_get_user_key)` decorator on `POST /lessons`.
- [Source: apps/api/app/modules/content/router.py:1050-1137] — `generate_chapter_lesson`, the
  sibling `3/minute;20/hour` limiter and its own extensive docstring on D45/D49/idempotency.
- [Source: apps/api/app/main.py:59-90, 205-209] — `lifespan()` startup-assertion pattern
  (`assert_required_buckets`) this story's Task 3 mirrors; `app.state.limiter` / exception handler
  wiring.
- [Source: apps/api/tests/unit/test_rate_limit_key.py] — existing D52/D64 regression coverage.
- [Source: apps/api/tests/unit/test_content_router.py:764-811] —
  `test_upload_lesson_429_rate_limit`.
- [Source: apps/api/tests/unit/test_generate_lesson_endpoint.py:1601-1806] — sibling rate-limit
  tests for the generate endpoint, including the D49 storage-URI note in their own docstrings.
- [Source: docs/dev1-tracker.md#Sprint-4 (S4-4, lines ~1107-1112)] — the assigned AC line and
  PARTIAL status.
- [Source: docs/dev1-tracker.md#S1-10 (line ~559-566)] — "do not defer to Sprint 4" instruction,
  the discrepancy this story's Dev Notes flags.
- [Source: docs/dev1-tracker.md#Ahead-of-Schedule-Wins (line ~1164)] — the `slowapi` middleware
  row.
- [Source: docs/DEFECT-REGISTER.md#D52 (line 221)] — closed, fixed 2026-08-04.
- [Source: docs/DEFECT-REGISTER.md#D64/D75 (line 329)] — the ES256 regression of D52, closed
  2026-08-05.
- [Source: docs/DEFECT-REGISTER.md#D49 (line 218)] — open, the gap this story closes.
- [Source: docs/DEFECT-REGISTER.md#D45 (line 214)] — the separate, out-of-scope idempotency race
  named in Scale & Load Q6.
- [Source: docs/DEFECT-REGISTER.md#D67 (line 333)] — the adjacent, unaddressed `media` router
  rate-limit gap flagged in Task 5. **[Review Finding — corrected 2026-08-25]** Line number fixed
  (was miscited as 341). Also note: the register has a second, unrelated, already-CLOSED entry
  also numbered D67 at line 286 (Sarvam TTS voice-ID default) — a real, pre-existing ID collision,
  not introduced by this story and not this branch's job to renumber (see
  `docs/stories/deferred-work.md`).
- **[Review Finding — removed 2026-08-25]** A prior draft cited a "D129" register entry here; no
  such row exists in `docs/DEFECT-REGISTER.md`. The underlying Scale & Load Q1 claim is unaffected
  and now cites only `docs/dev1-tracker.md`'s S4-1 line directly.
- [Source: docs/SCALE-CONTRACT.md] — the six questions answered above.
- [Source: fly.toml] — real current deploy topology (Fly, not Railway); `min_machines_running = 1`,
  `auto_start_machines = true`, no stated max.
- [Source: docs/decisions/ADR-001-india-region-migration-topology.md §2, §4] — Railway retirement,
  "bursty and request-scaled" API characterization, open Redis-location decision.
- [Source: docs/bmad/epics/epic-5-platform-core.md] — checked and found to have no rate-limiting
  content at all; "Technical Scope" table's `backend/routers/payments.py` path confirmed stale
  against this repo's real `apps/api/app/modules/{module}/router.py` convention.
- [Source: CLAUDE.md#Development-Rules] — D52/D49 citations, "re-derive every inherited cap," "a
  fix without a guard is FIXED-UNGUARDED."

## Sprint 4 Sequencing

- **Branch:** `sprint4/s4-4-rate-limit-per-route`
- **Depends on:** None. The decorator/keying AC (#1, #2) are already merged to `main`; the
  Redis-storage and startup-guard work (AC #3-#5) touch only `core/rate_limit.py` and `main.py`
  and do not require S4-1's load test, S4-3's Stripe integration, or S4-5's RLS audit to exist
  first. This is the lightest-weight Sprint 4 story and can be picked up first or run fully in
  parallel with the others.
- **Blocks:** **S4-1** (load test: 50 concurrent lesson generations) benefits from, but is not
  strictly blocked by, this story landing first — running S4-1 before AC3/AC4 land would measure
  the *current* per-process-multiplied ceiling rather than the intended per-deployment one, likely
  producing misleading throughput numbers if S4-1 runs against more than one live process.
  Recommend sequencing this story before S4-1 for that reason, even though no hard dependency
  exists. Does not block S4-2 (reliability fixes), S4-3 (Stripe), S4-5 (RLS audit), S4-6
  (backups/DR), S4-7 (runbook), or S4-8 (Imagen fallback) — none of those touch rate limiting.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5), 2026-08-25.

### Debug Log References

- Full unit suite (`apps/api/tests/unit`) before and after: 1241 passed / 6 skipped / 3
  pre-existing unrelated failures (D134, `test_extract_page_bounds.py`, pypdfium2 API mismatch) —
  identical failure set both times, zero regressions introduced.
- Mutation check on `assert_rate_limit_storage_configured`: guard condition replaced with
  `if False`, 3 of 6 `test_rate_limit_storage_guard.py` tests reddened as expected, restored.
- `fakeredis[lua]` (adds `lupa`) required for `test_rate_limit_redis_storage.py` — plain
  `fakeredis` doesn't serve `EVALSHA`/Lua scripts, which `limits`' `RedisStorage` needs for its
  atomic incr. Added to `pyproject.toml`'s `dev` extra; `uv lock` re-run (`uv sync --extra dev`
  itself is currently broken in this sandbox on an unrelated `torch` wheel-platform mismatch —
  pre-existing, not touched by this story; `uv lock` alone resolves and updates the lockfile
  without needing to install/download `torch`).

### Completion Notes List

- AC1/AC2 (decorator + per-user keying) were already implemented and tested — verified, not
  re-built. `docs/dev1-tracker.md`'s S4-4 "not yet configured ✗" line was stale; corrected with an
  explicit discrepancy note rather than silently.
- AC3 (Redis-backed shared storage) is proven at the code level (fakeredis-backed test showing
  two `Limiter` instances share one ceiling). Actually pointing `RATE_LIMIT_STORAGE_URL` at a
  real shared Redis instance in each deployed environment is a deploy/ops action blocked on
  ADR-001 §4's still-open Redis-location decision (Upstash Mumbai vs. Fly Redis) — out of a code
  branch's reach, left explicitly open in Task 2.
- AC4/AC5 (startup guard) fully implemented, tested, and mutation-checked.
- AC6 (register + tracker close-out) done: `docs/DEFECT-REGISTER.md` D49 closed, `docs/
  dev1-tracker.md` S4-4 flipped and dashboard updated.
- D67 (media signed-url endpoint has no rate limit) and the un-re-derived `5/minute` figure are
  both explicitly flagged, not fixed, per Task 5 — recommend the team decide on both separately.

**Post-review (2026-08-25):** 8-layer `/bmad-code-review` run (the skill's 4 built-in layers +
4 additional layers CLAUDE.md's gate requires). 2 decisions resolved (keep hard-fail; fix the
phantom D129 citation's wording only, no new register row), 10 patches applied, 4 items deferred
to `docs/stories/deferred-work.md`, 6 dismissed (2 of those were actively refuted by independent
re-execution — the "full suite passed" and mutation-check claims both checked out exactly as
stated when the Test Coverage and Acceptance Auditor layers re-ran them themselves). The headline
patch: the original guard's exact-string `"memory://"` check missed non-canonical variants
(empty string, case, whitespace, a URI suffix) that all still resolved to real `MemoryStorage` —
empirically proven by the Scale & Load Hunter constructing real `Limiter` instances with each.
Replaced string-matching with `limits.storage_from_string` + `isinstance(..., MemoryStorage)`,
the same factory `Limiter` itself uses. Both mutation-check directions now performed. Full unit
suite after all patches: 1248 passed (was 1241, +7 new tests) / 6 skipped / same 3 pre-existing
unrelated failures (D134) — zero regressions. Ruff and mypy clean on every touched file.
No PR opened in this session (no `gh` action taken); branch `sprint4/s4-4-rate-limit-per-route`
has 6 commits (story-only → implementation → style fixup → review findings → patch fixes) and is
not yet pushed to remote.

### File List

- `apps/api/app/core/rate_limit.py` — `assert_rate_limit_storage_configured()`; post-review:
  resolves via `limits.storage_from_string` + `isinstance(..., MemoryStorage)` instead of string
  match; `_RATE_LIMIT_STORAGE_URI` module-level constant as single source of truth
- `apps/api/app/main.py` — imports and calls the guard first in `lifespan()`
- `apps/api/tests/unit/test_rate_limit_storage_guard.py` — 12 tests (6 original + 5 non-canonical
  variant cases + 1 lifespan-wiring source-scan; 2 of the original 6 rewritten post-review)
- `apps/api/tests/unit/test_rate_limit_redis_storage.py` — 3 tests (2 original + 1 using the real
  production `_get_user_key`)
- `apps/api/tests/unit/test_content_router.py` — strengthened `test_upload_lesson_429_rate_limit`
  with an `int()`-parseability assertion on `Retry-After` (post-review)
- `apps/api/pyproject.toml` — `fakeredis>=2.23.0` → `fakeredis[lua]>=2.23.0`
- `apps/api/uv.lock` — regenerated (`uv lock`) for the `lupa` addition
- `docs/DEFECT-REGISTER.md` — D49 row closed, disposition tightened post-review
- `docs/dev1-tracker.md` — S4-4 flipped, dashboard + header updated
- `docs/stories/5-4-rate-limiting-per-route.md` — this file (Tasks/Subtasks, Review Findings,
  Dev Agent Record, AC/Scale-&-Load wording fixes)
- `docs/stories/deferred-work.md` — 4 items deferred from this story's code review
