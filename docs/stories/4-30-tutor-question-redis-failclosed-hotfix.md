---
title: "Story 4-30 — Hotfix: Ask-Tutor 500s when Redis rate-limit check fails (D164)"
status: done
owners: [Dev 2]
sprint: hotfix
---

# Story 4-30 — Hotfix: Ask-Tutor 500s when the Redis rate-limit check itself fails (D164)

## Problem Statement

Found live, 2026-09-07, capturing UI screenshots for the user manual immediately after D163
deployed: submitting a real question via "Ask Tutor" now reaches the backend with a real
`session_id` (D163 fixed), but the backend itself 500s:

```
File "app/modules/assessment/service.py", line 2444, in answer_tutor_question
    question_number = await redis.incr(count_key)
redis.exceptions.ResponseError: max requests limit exceeded. Limit: 500000, Usage: 500000.
```

This is **D162** (the production Upstash Redis instance is at its hard request cap) hitting a
**different, more serious** code path than the one D162 originally documented. D162 was scoped
around a failed ad-hoc `LPUSH` while seeding demo chart data — a dev-tooling inconvenience the
user explicitly chose to defer ("skip it for now"). This is not that: `answer_tutor_question`'s
`redis.incr(count_key)` (the per-session tutor-question rate limit, Scale & Load Q6's atomic
check-then-act) has **no fallback at all**, unlike the two other Redis call sites reachable in
this exact request:

- `seed_personalized_ces_threshold` (`create_session_endpoint`'s own call) already catches any
  Redis failure and logs "falling back to global settings.ces_threshold" — non-fatal.
- The WebSocket session-state init (`core/websocket.py`) already catches it too ("Failed to init
  session state") — non-fatal.

`answer_tutor_question`'s rate-limit increment is the one caller in this whole request path that
has no such guard, so a real student asking a real question during this Redis outage gets a hard
500 — and the frontend (`AskTutorPanel.tsx`'s `handleSubmit`) has no error-state rendering for
that response at all, so the panel just silently closes and resumes playback with no indication
to the student that their question was lost.

**Important distinction from a simple non-fatal catch-and-continue**: `redis.incr`'s return value
here is not cosmetic telemetry (like the CES-threshold cache or session-state init) — it is the
one and only enforcement point for the per-session tutor-question cap
(`settings.tutor_qa_max_questions_per_session`), a real cost/abuse guard (every answered question
makes a real `LLM_TUTOR` call). Silently bypassing the cap on Redis failure would let an outage
turn into an unbounded-cost hole. The correct degrade is to **fail closed** — treat a failed
rate-limit check the same as a genuine over-cap hit (decline gracefully, no LLM call, no crash),
reusing the exact response shape already used for a real cap breach, not inventing a new one.

## Acceptance Criteria

- **AC1** — `answer_tutor_question`'s `redis.incr(count_key)` / `redis.expire(count_key, ...)`
  calls are wrapped so any Redis failure (matches the real observed
  `redis.exceptions.ResponseError`, caught broadly as `Exception` per this module's own existing
  convention — no new library-specific exception-hierarchy assumption introduced) results in the
  same graceful decline already returned for a genuine over-cap hit
  (`TutorQuestionResult(received=True, answer=None, declined=True)`), never a 500.
- **AC2** — The decline is logged via the existing `_log_tutor_question_event` with a distinct
  `finish_reason="redis_unavailable"` (not `"rate_limited"`) so admin/observability can tell a
  genuine per-session cap hit apart from a Redis-outage-driven decline.
- **AC3** — No embedding call, pgvector search, or `LLM_TUTOR` call happens on this path (matches
  the existing over-cap short-circuit exactly) — a Redis outage must not let the rate limiter's
  own failure become a way to skip the limiter and still get an answer.
- **AC4** — A warning is logged (not silently swallowed) naming the session id and the real
  exception, so this is discoverable in Fly logs without needing a student to report it.
- **AC5** — New tests in `test_tutor_question_endpoint.py` prove: (a) a Redis error on `incr`
  declines rather than 500s, (b) `finish_reason="redis_unavailable"` is what gets logged, (c) no
  embedding/LLM call happens in this case — following this file's own existing
  `_redis_mock`/`_supabase_mock`/`_patch_embeddings_and_llm` fixtures rather than inventing new
  ones.
- **AC6** — `docs/DEFECT-REGISTER.md` gets a new **D164** row (not folded into D162 — same
  underlying Redis exhaustion, but a different code path with a different, worse failure mode: a
  hard 500 rather than a silent degrade, on a security-relevant rate limiter rather than cosmetic
  telemetry).
- **AC7** — Existing guard tests for `assessment/service.py`/`assessment/router.py` (this module
  has no dedicated `test_dunder_all_*`/`test_no_hardcoded_*` guard beyond the repo-wide
  `test_node_return_shape.py`/`test_unbounded_queries.py`, confirmed by grep before starting) still
  pass.

## Scale & Load

1. **Unit of work**: one Redis `INCR` per tutor-question submission, already atomic and already
   the correct check-then-act pattern (Scale & Load Q6) — unchanged by this fix.
2. **Fixed budget vs. variable input**: `settings.tutor_qa_max_questions_per_session` is the fixed
   budget; this fix does not change it, weaken it, or bypass it — it changes only what happens when
   the mechanism ENFORCING it is itself unavailable, and the answer is fail-closed (treat as if
   the budget were already exhausted), never fail-open.
3. **Scope**: per-session (`count_key = f"session:{session_id}:tutor_question_count"`), unchanged.
4. **Unbounded reads/writes**: none introduced.
5. **Inherited caps re-derived**: N/A — this fix does not touch the cap value itself.
6. **Concurrency**: unaffected — the real atomic `INCR` is still the single source of truth when
   Redis is healthy; this fix only defines behavior for the case where the call itself raises,
   which cannot race with anything since nothing was incremented.

## Dev Notes

- Root cause confirmed directly from a live Fly log traceback (`mcp__fly__fly-logs`), immediately
  after verifying D163's fix worked (a real `session_id` now reaches this endpoint for the first
  time) — this bug was previously unreachable in production because D163 always 500'd first.
- Deliberately fail CLOSED, not open: this is the one Redis call site in this request's whole
  execution path where "just log and continue" would be the WRONG degrade, since unlike CES
  threshold seeding or WS session-state init, this call's return value is a real cost/abuse gate,
  not telemetry.
- Frontend gap named but NOT fixed here (out of scope for a backend-only hotfix; flagged for a
  follow-up): `AskTutorPanel.tsx`'s `handleSubmit` has no distinct rendering for
  `declined: true, finish_reason` — it already renders the generic decline copy for a genuine
  rate-cap decline, so this fix's new decline path is not silently swallowed by the frontend, it
  just isn't distinguishable from a normal rate-cap decline to the student. Acceptable for this
  hotfix: the student experience (a graceful "we can't answer that right now" message) is
  correct and non-broken either way.

## Dev Agent Record

### Completion Notes

- **AC1-AC4 — DONE.** `answer_tutor_question`'s rate-limit step wrapped in `try`/`except
  Exception`; on failure, logs a warning and returns the same declined result as a genuine
  over-cap hit, with `finish_reason="redis_unavailable"`.
- **AC5 — DONE.** 3 new tests added.
- **AC6 — DONE.** D164 registered in `docs/DEFECT-REGISTER.md`.
- **AC7 — DONE.** Confirmed via grep: no `test_dunder_all_*`/`test_no_hardcoded_*` guard names this
  module specifically; repo-wide `test_node_return_shape.py`/`test_unbounded_queries.py` re-run
  clean.

### File List

- `apps/api/app/modules/assessment/service.py` — `answer_tutor_question`'s rate-limit step
- `apps/api/tests/unit/test_tutor_question_endpoint.py` — 3 new tests
- `docs/DEFECT-REGISTER.md` — D164 registered

## References

- [Source: apps/api/app/modules/assessment/service.py:2440-2447] — the unguarded `redis.incr`/
  `redis.expire` call this story wraps
- [Source: apps/api/app/modules/assessment/service.py:2093-2149] — `seed_personalized_ces_threshold`'s
  existing non-fatal Redis-failure pattern, the style precedent (though NOT the fail-open behavior
  itself, which does not apply here — see Dev Notes)
- [Source: apps/api/tests/unit/test_tutor_question_endpoint.py] — existing rate-limit tests and
  fixtures this story's new tests extend
- [Source: docs/DEFECT-REGISTER.md, D162] — the underlying Redis exhaustion this is a second,
  distinct symptom of

## Follow-up (same PR, 2026-09-07)

### CI fix

First CI run on this PR failed `ruff format --check` — `tests/unit/test_tutor_question_endpoint.py`
was `ruff check`-clean (linting) but not `ruff format`-clean (formatting); the two are separate
checks and only the latter was skipped locally before the first push. Fixed by running
`ruff format` on the file; no behavior change, re-verified all 20 tests in the file still pass.

### Dashboard link (unrelated to D164, bundled into this PR per explicit user direction)

User-reported gap, unrelated to the Redis fix: the lesson player had no way back to the dashboard
during an active lesson (`IDLE`/`PLAYING`/`PAUSED`/`QUIZ`/`TEACH_BACK`) — only the `ENDED`
lesson-complete screen had a "Back to Dashboard" link. Added a persistent small link
(top-right corner, mirrors the existing tier-badge's floating-pill style, top-left) in
`Player.tsx`, hidden once `status === 'ENDED'` to avoid duplicating that screen's own prominent
CTA. Progress is already saved continuously (`saveProgress()`/`restoreProgress()`), so leaving
mid-lesson was already safe — this only adds a way to actually do it without closing the tab.

3 new tests in `Player.test.tsx`: link present and points to `/dashboard` while `PLAYING`;
present across `IDLE`/`PAUSED`/`QUIZ`/`TEACH_BACK`; hidden (exactly one dashboard link, the
ENDED screen's own) once `ENDED`. Full frontend suite re-run: 93 files / 1142 tests, zero
regressions. `tsc --noEmit`/`eslint` clean.

#### File List (this follow-up)

- `apps/api/tests/unit/test_tutor_question_endpoint.py` — `ruff format` applied, no logic change
- `apps/web/src/components/player/Player.tsx` — new Dashboard link
- `apps/web/src/__tests__/components/player/Player.test.tsx` — 3 new tests
