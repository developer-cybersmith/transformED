# Dev 4 — Branch → Task Map

**Owner:** Dev 4 · developerteam3@cybersmithsecure.com  
**Domain:** WebSocket · JWT · 7-state tutor · Redis buffer · Interventions  
**Last updated:** 2026-07-08  
**Scope:** All 28 fetched remote branches (24 task branches + 4 sprint integration branches)

> This is the authoritative map of which branch covers which tracker tasks.
> Sprint integration branches (`dev4/s*`) are the hand-off points for cross-dev merging.
> Task branches (`sprint*/s*-*`, `feature/*`, `fix/*`) are the individual delivery units.

---

## 🔒 SECURITY — Open Issue (pending 4-dev team decision)

**WS endpoint `/ws/{session_id}` is fully unauthenticated.**

The `session_id` URL param is unverified. Any client knowing a valid `session_id` can:
- Drive the tutor FSM for another student's session via the 9 `_TUTOR_CLIENT_EVENTS`
- Fire `lesson_complete` to terminate another student's lesson early
- Spam `quiz_failed` or `teachback_failed` to corrupt their session state

This applies to `dev4/s1`, `dev4/s2`, `dev4/s3`, `dev4/s4` — all sprint branches are affected.

**Related branch:** `fix/4-17-jwt-es256-verification` (open, not merged)

**Team must decide before any real-student deployment:**
- Option A: Require a signed query-param token on WS connect handshake
- Option B: Verify `session_id` ownership against JWT `sub` via Redis lookup on first message
- Option C: Treat all client-sent lifecycle outcomes as server-authoritative (client sends event, server validates against DB before dispatching)

**Do not merge `dev4/s*` to a production main branch without this decision.**

---

## Sprint Integration Branches

These are created from the last Dev 4 PR merge of each sprint. They are **cumulative** — each one contains all Dev 4 work up to and including that sprint.

> **Integration workflow:** once all devs push their `dev{N}/s1` branches, they are merged together into a new integration main for Sprint 1 testing. Sprint 0 is pre-work/setup and is not part of cross-dev integration.

| Branch | Base commit | PR anchor | Dev 4 tasks included | Status |
|--------|------------|-----------|----------------------|--------|
| `dev4/s1` | `f704a47` | last = PR #28 | Sprint 0 (all) + Sprint 1 (6/7 tasks) | Ready for cross-dev merge |
| `dev4/s2` | `a4c6e18` | last = PR #35 | Above + Sprint 2 (all 6) + `ws_message_routing` backfill | Ready |
| `dev4/s3` | `c9920be` | last = PR #39 | Above + Sprint 3 (4 verified tasks) | Ready — see Sprint 3 gap note |
| `dev4/s4` | `2110bdf` | last = PR #42 | Above + Sprint 4 (all 6 partial) | Partial — pending production data |

### What each sprint branch contains cumulatively

```
dev4/s1  ──────────────────────────────────────────────── f704a47
         │ Sprint 0 (all 7 tasks via feature/dev4-redis-ces-buffer,
         │   s0-6-mock-ws-client, s0-10-websocket-test-fix)
         │ Sprint 1: jwt_all_routes, redis_signal_buffer, arq_lesson_ready,
         │   idle_to_teaching, session_state_init, session_redis_persistence
         │ ⚠️  ws_message_routing NOT included (completed in Sprint 2 branch)

dev4/s2  ──────────────────────────────────────────────── a4c6e18
         │ Everything in dev4/s1 PLUS:
         │ Sprint 1 backfill: ws_message_routing (via s2-3-quizzing-teachback-flow)
         │ Sprint 2: full_state_machine, all_transitions, quizzing_teachback_flow,
         │   session_restore, intervention_selection, ws_message_types_final

dev4/s3  ──────────────────────────────────────────────── c9920be
         │ Everything in dev4/s2 PLUS:
         │ Sprint 3 verified: ces_computation, max_distraction_cap,
         │   fatigue_once, intervention_routing
         │ ⚠️  4 Sprint 3 tasks unverified (no branch/story — see gap note below)

dev4/s4  ──────────────────────────────────────────────── 2110bdf
         │ Everything in dev4/s3 PLUS:
         │ Sprint 4: ws_load_test, reconnect_test, threshold_tuning,
         │   intervention_response_review, cooldown_tuning, intervention_copy_review
         │   (all Partial — methodology done, production runs pending)
```

---

## Cross-Sprint Task Completion

These tasks belong to one sprint in the tracker but were implemented inside a different sprint's branch. This is noted explicitly so the right sprint integration branch is used when integrating.

| Tracker task | Assigned sprint | Completed in branch | Completed in sprint | Included in |
|---|---|---|---|---|
| `redis_lpush_pattern` | Sprint 0 | `sprint1/s1-jwt-auth-tests` | Sprint 1 | `dev4/s1` ✓ |
| `ws_message_routing` | Sprint 1 | `sprint2/s2-3-quizzing-teachback-flow` | Sprint 2 | `dev4/s2` ✓ — **absent from `dev4/s1`** |
| `attention_ingestion` | Sprint 3 | Folded into Sprint 2 branches | Sprint 2 | `dev4/s2` — unverified, no story |
| `ces_redis_buffer` | Sprint 3 | Folded into Sprint 2 branches | Sprint 2 | `dev4/s2` — unverified, no story |
| `intervention_trigger` | Sprint 3 | Folded into Sprint 2 branches | Sprint 2 | `dev4/s2` — unverified, no story |
| `cooldown_enforcement` | Sprint 3 | Folded into Sprint 2 branches | Sprint 2 | `dev4/s2` — unverified, no story |

> **Impact on integration:** When merging `dev4/s1` with other devs' Sprint 1 branches, `ws_message_routing` (WebSocket lifecycle event routing) will be missing. It lands in the `dev4/s2` integration. Other devs should be aware that WebSocket client-driven events (`segment_complete`, `quiz_complete`, etc.) are a Sprint 2 feature from Dev 4's side.

---

## Quick Reference — All 28 Branches

| Branch | PR | Status | Sprint | Tasks Covered |
|--------|----|--------|--------|---------------|
| `dev4/s1` | — | Integration | S0+S1 | See sprint table above |
| `dev4/s2` | — | Integration | S0–S2 | See sprint table above |
| `dev4/s3` | — | Integration | S0–S3 | See sprint table above |
| `dev4/s4` | — | Integration | S0–S4 | See sprint table above |
| `feature/dev4-redis-ces-buffer` | #9 | Merged | Sprint 0 | `ws_handler_scaffold`, `jwt_middleware`, `redis_lpush_pattern`, `langgraph_scaffold`, `tutor_stub`, `sentry_wired` |
| `feature/dev4-session-lifecycle` | #11 | Merged | Sprint 1 | `session_state_init`, `session_redis_persistence` |
| `fix/sprint1-arq-lesson-ready-pubsub` | #17 | Merged | Sprint 1 | `arq_lesson_ready` (cross-process fix) |
| `fix/4-17-jwt-es256-verification` | — | **OPEN** | Sprint 1 | JWT ES256/JWKS follow-up (Story 4-17) |
| `sprint0/s0-3-ces-buffer-tests` | #25 | Merged | Sprint 0 | Stacking base — see note |
| `sprint0/s0-6-mock-ws-client` | #22 | Merged | Sprint 0 | `mock_ws_client` |
| `sprint0/s0-10-websocket-test-fix` | #18 | Merged | Sprint 0 | Patch only (1-line init fix) |
| `sprint1/s1-jwt-auth-tests` | #26 | Merged | Sprint 1 | `jwt_all_routes` + `redis_lpush_pattern` (Sprint 0 backfill) |
| `sprint1/s1-5-idle-teaching-live` | #28 | Merged | Sprint 1 | `idle_to_teaching` + `arq_lesson_ready` |
| `sprint1/s1-2-lesson-ready-fix` | #30 | Merged | Sprint 1 | Stacking/integration base — no unique task work |
| `sprint2/s2-1-full-state-machine` | #32 | Merged | Sprint 2 | `full_state_machine` |
| `sprint2/s2-2-all-transitions` | #29 | Merged | Sprint 2 | `all_transitions` |
| `sprint2/s2-3-quizzing-teachback-flow` | #31 | Merged | Sprint 2 | `quizzing_teachback_flow` + `ws_message_routing` (Sprint 1 backfill) |
| `sprint2/s2-4-session-restore` | #34 | Merged | Sprint 2 | `session_restore` |
| `sprint2/s2-5-intervention-selection` | #33 | Merged | Sprint 2 | `intervention_selection` |
| `sprint2/s2-6-ws-message-types-final` | #35 | Merged | Sprint 2 | `ws_message_types_final` |
| `sprint3/s3-3-ces-computation` | #36 | Merged | Sprint 3 | `ces_computation` |
| `sprint3/s3-6-max-distraction-cap` | #37 | Merged | Sprint 3 | `max_distraction_cap` |
| `sprint3/s3-7-fatigue-once` | #38 | Merged | Sprint 3 | `fatigue_once` (verification + story only) |
| `sprint3/s3-8-intervention-routing` | #39 | Merged | Sprint 3 | `intervention_routing` |
| `sprint4/s4-4-ws-load-test` | #40 | Merged | Sprint 4 | `ws_load_test` [Partial] |
| `sprint4/s4-5-reconnect-test` | #41 | Merged | Sprint 4 | `reconnect_test` [Partial] |
| `sprint4/s4-analysis-skeletons` | #42 | Merged | Sprint 4 | `threshold_tuning`, `intervention_response_review`, `cooldown_tuning`, `intervention_copy_review` [all Partial] |

---

## Detailed Branch Contents

### Sprint Integration Branches

#### `dev4/s1` — Sprint 1 integration hand-off · Base: `f704a47`

Created from the merge commit of PR #28 (last real Sprint 1 Dev 4 work before Sprint 2 began).

**Contains all task branches merged before that point:**
- `feature/dev4-redis-ces-buffer` (PR #9)
- `feature/dev4-session-lifecycle` (PR #11)
- `fix/sprint1-arq-lesson-ready-pubsub` (PR #17)
- `sprint0/s0-10-websocket-test-fix` (PR #18)
- `sprint0/s0-6-mock-ws-client` (PR #22)
- `sprint1/s1-jwt-auth-tests` (PR #26)
- `sprint1/s1-5-idle-teaching-live` (PR #28)

**Sprint 1 task missing from this branch:** `ws_message_routing` — completed in Sprint 2. See cross-sprint table.

---

#### `dev4/s2` — Sprint 2 integration hand-off · Base: `a4c6e18`

Created from the merge commit of PR #35 (last Sprint 2 Dev 4 work).

**Adds over dev4/s1:**
- `sprint2/s2-2-all-transitions` (PR #29)
- `sprint2/s2-3-quizzing-teachback-flow` (PR #31) ← also closes `ws_message_routing`
- `sprint2/s2-1-full-state-machine` (PR #32)
- `sprint2/s2-5-intervention-selection` (PR #33)
- `sprint2/s2-4-session-restore` (PR #34)
- `sprint2/s2-6-ws-message-types-final` (PR #35)

**Sprint 1 backfill landed here:** `ws_message_routing` (via PR #31).

---

#### `dev4/s3` — Sprint 3 integration hand-off · Base: `c9920be`

Created from the merge commit of PR #39 (last Sprint 3 Dev 4 work).

**Adds over dev4/s2:**
- `sprint3/s3-3-ces-computation` (PR #36)
- `sprint3/s3-6-max-distraction-cap` (PR #37)
- `sprint3/s3-7-fatigue-once` (PR #38)
- `sprint3/s3-8-intervention-routing` (PR #39)

> ⚠️ **Sprint 3 gap:** 4 tasks (`attention_ingestion`, `ces_redis_buffer`, `intervention_trigger`, `cooldown_enforcement`) are marked Completed in the tracker with no dedicated branch, no completion date, and no story file. The code exists (folded into Sprint 2 branches), but they were never verified as standalone Sprint 3 tasks.

---

#### `dev4/s4` — Sprint 4 integration hand-off · Base: `2110bdf`

Created from the merge commit of PR #42 (last Sprint 4 Dev 4 work).

**Adds over dev4/s3:**
- `sprint4/s4-4-ws-load-test` (PR #40)
- `sprint4/s4-5-reconnect-test` (PR #41)
- `sprint4/s4-analysis-skeletons` (PR #42)

> All Sprint 4 tasks are [Partial] — harnesses and methodology docs are ready, but production runs require the India-region server deployment (Sprint 3 prerequisite).

---

## Feature Branches

### `feature/dev4-redis-ces-buffer` — PR #9 · Merged · Sprint 0 omnibus

**Sprint 0 omnibus** — landed before the one-task-one-branch rule.

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/core/websocket.py` | +8 | WebSocket handler wiring |
| `apps/api/app/modules/tutor/service.py` | +172 | `process_attention_signal()`, Redis CES buffer (LPUSH/LTRIM/LRANGE) |
| `docs/dev4-websocket-tutor-tracker.md` | +501 | Tracker file created; Sprint 0 tasks verified |
| `scripts/check_dev4_progress.py` | +462 | Progress auto-check script |

**Tasks covered:** `ws_handler_scaffold`, `jwt_middleware`, `redis_lpush_pattern`, `langgraph_scaffold`, `tutor_stub`, `sentry_wired`

---

### `feature/dev4-session-lifecycle` — PR #11 · Merged · Sprint 1

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/core/websocket.py` | +50 | `_init_session_state()`, Redis key init on connect |
| `apps/api/tests/test_websocket_session.py` | +81 | Session lifecycle tests |
| `pnpm-lock.yaml` / `pnpm-workspace.yaml` | +5126 | Workspace lockfile |

**Tasks covered:** `session_state_init`, `session_redis_persistence`

---

## Fix Branches

### `fix/sprint1-arq-lesson-ready-pubsub` — PR #17 · Merged · Sprint 1

Bug #6 fix: ARQ worker was calling `manager.send()` cross-process. Replaced with Redis pub/sub.

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/core/pubsub.py` | +120 | `_run_lesson_subscriber()`, Redis psubscribe → forward to WS |
| `apps/api/app/main.py` | +44 | `start_lesson_ready_listener()` wired into lifespan |
| `apps/api/app/workers/jobs/content_pipeline.py` | +25 | Worker publishes to Redis channel |
| `apps/api/tests/test_lesson_ready_integration.py` | +327 | End-to-end integration tests (5) |
| `apps/api/tests/test_lesson_ready_pubsub.py` | +294 | Unit tests (6) |

**Tasks covered:** `arq_lesson_ready`

---

### `fix/4-17-jwt-es256-verification` — **OPEN · not yet merged · Sprint 1 follow-up**

| File | Purpose |
|------|---------|
| `apps/api/app/dependencies.py` | ES256 via JWKS support in `get_current_user()` |
| `apps/api/tests/test_auth.py` | ES256 token path + `aud` validation gap fix |
| `apps/api/pyproject.toml` | Dependency update for JWKS |
| `docs/stories/4-17-jwt-es256-verification.md` | Story |

**Tasks covered:** Story 4-17 — JWT ES256/JWKS follow-up to `jwt_all_routes`

> ⚠️ 3 commits, not yet merged. **Not included in `dev4/s1`** (came after PR #28). Will land in `dev4/s2` once merged.

---

## Sprint 0 Task Branches

### `sprint0/s0-3-ces-buffer-tests` — PR #25 · Merged

> Stacking/integration base. Tip commit IS the PR #25 merge. Content that landed through it: `test_lesson_ready_pubsub.py`, story 4-3. CES buffer tests landed separately via `sprint1/s1-jwt-auth-tests`.

---

### `sprint0/s0-6-mock-ws-client` — PR #22 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `scripts/mock_ws_client.py` | +88 | CLI smoke-test: connect, send `attention_signal`, print responses |

**Tasks covered:** `mock_ws_client`

---

### `sprint0/s0-10-websocket-test-fix` — PR #18 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/modules/tutor/state_machine/__init__.py` | +1 | Expose `graph` submodule for test imports |

> **Patch only** — 1-line fix, not a tracker task.

---

## Sprint 1 Task Branches

### `sprint1/s1-jwt-auth-tests` — PR #26 · Merged

> Two tasks bundled. PR #23 was a prior attempt; PR #26 superseded it.

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/tests/test_tutor_service.py` | +294 | 19 CES buffer tests + JWT route tests |
| `docs/stories/4-2-ces-buffer-tests.md` | +119 | Story for `redis_lpush_pattern` |

**Tasks covered:** `jwt_all_routes` + `redis_lpush_pattern` (Sprint 0 backfill)

---

### `sprint1/s1-5-idle-teaching-live` — PR #28 · Merged

> Two tasks bundled. PR #27 first attempt; PR #28 stack reconciliation.

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/core/websocket.py` | +8 | `_handle_session_start()` dispatch |
| `apps/api/app/modules/tutor/service.py` | +11 | `start_session()` |
| `apps/api/app/modules/tutor/state_machine/graph.py` | +110 | FSM one-transition-per-dispatch; `route_entry`; `recursion_limit=5` |
| `apps/api/tests/test_lesson_ready_pubsub.py` | +71 | lesson_ready pubsub tests |
| `apps/api/tests/test_tutor_graph.py` | +237 | 13 FSM tests |
| `docs/stories/4-3-lesson-ready-pubsub-test-fix.md` | +137 | Story |
| `docs/stories/4-4-idle-to-teaching-live.md` | +194 | Story |

**Tasks covered:** `idle_to_teaching` + `arq_lesson_ready`

---

### `sprint1/s1-2-lesson-ready-fix` — PR #30 · Merged

> Stacking/integration base. Merged by Dev 2 as housekeeping. No unique task work.

---

## Sprint 2 Task Branches

### `sprint2/s2-1-full-state-machine` — PR #32 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/modules/tutor/state_machine/graph.py` | +47 | `intervention_type` derivation; fatigue-once end-to-end; `in_teachback`; Langfuse |
| `apps/api/tests/test_tutor_graph.py` | +258 | 41 tests |
| `docs/stories/4-7-full-state-machine.md` | +191 | Story |

**Tasks covered:** `full_state_machine`

---

### `sprint2/s2-2-all-transitions` — PR #29 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/tests/test_tutor_graph.py` | +209 | 25 tests: all 14 transitions + 3 guard-blocked cases |
| `docs/stories/4-5-all-transitions-tested.md` | +146 | Story |

**Tasks covered:** `all_transitions`

---

### `sprint2/s2-3-quizzing-teachback-flow` — PR #31 · Merged

> Also closes `ws_message_routing` (Sprint 1 task backfilled here).

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/core/websocket.py` | +36 | 9 lifecycle events allow-listed and routed |
| `apps/api/app/modules/tutor/service.py` | +31 | `advance_tutor_state()` |
| `apps/api/app/modules/tutor/state_machine/graph.py` | +11 | `route_from_teach_back` default fixed |
| `apps/api/tests/test_tutor_graph.py` | +86 | TEACH_BACK interrupt-block + full flow step-through |
| `apps/api/tests/test_websocket_session.py` | +48 | E1–E4 event dispatch tests |
| `docs/stories/4-6-quizzing-teachback-flow.md` | +208 | Story |

**Tasks covered:** `quizzing_teachback_flow` + `ws_message_routing` (Sprint 1 backfill)

---

### `sprint2/s2-4-session-restore` — PR #34 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/core/websocket.py` | +51 | `_restore_or_init_session()`: reconnect → Redis read → `state_change` sync |
| `apps/api/tests/test_websocket_session.py` | +99 | F1–F6 reconnect tests |
| `docs/stories/4-9-session-restore.md` | +148 | Story |

**Tasks covered:** `session_restore`

---

### `sprint2/s2-5-intervention-selection` — PR #33 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/core/pubsub.py` | +12 | Lesson package cached at `lesson_package:{sid}` (24h TTL) |
| `apps/api/app/modules/tutor/service.py` | +62 | Package cache read; segment tracking; `tutor_intervene` WS send |
| `apps/api/tests/test_lesson_ready_pubsub.py` | +48 | Cache write + TTL |
| `apps/api/tests/test_tutor_service.py` | +183 | Delivery, degrade, segment increment |
| `docs/stories/4-8-intervention-selection.md` | +187 | Story |

**Tasks covered:** `intervention_selection`

---

### `sprint2/s2-6-ws-message-types-final` — PR #35 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `docs/ws-message-contract.md` | +270 | Published contract: all inbound + outbound shapes with JSON examples |
| `docs/stories/4-10-ws-message-types-final.md` | +138 | Story |

**Tasks covered:** `ws_message_types_final`

---

## Sprint 3 Task Branches

> ⚠️ **Sprint 3 gap:** 4 tasks (`attention_ingestion`, `ces_redis_buffer`, `intervention_trigger`, `cooldown_enforcement`) have no dedicated branch, no completion date, and no story file. They are marked Completed in the tracker but were never verified as standalone Sprint 3 tasks. Code was folded into Sprint 2 branches.

### `sprint3/s3-3-ces-computation` — PR #36 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/modules/tutor/service.py` | +55 | Real §11 weighted formula; `None`-weight redistribution; non-finite rejection |
| `apps/api/tests/test_tutor_service.py` | +216 | Group G tests: formula, clamp, benchmark (~7µs/call) |
| `docs/stories/4-11-ces-computation.md` | +193 | Story |

**Tasks covered:** `ces_computation`

---

### `sprint3/s3-6-max-distraction-cap` — PR #37 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/tests/test_tutor_graph.py` | +55 | Integration proof: interventions 1–3 fire; 4th blocked |
| `docs/stories/4-12-max-distraction-cap.md` | +142 | Story |

**Tasks covered:** `max_distraction_cap` (guard logic already in `graph.py` from Sprint 2)

---

### `sprint3/s3-7-fatigue-once` — PR #38 · Merged

| File | Purpose |
|------|---------|
| `docs/dev4-websocket-tutor-tracker.md` | Tracker reconciliation |
| `docs/stories/4-13-fatigue-once.md` | Story |

**Tasks covered:** `fatigue_once` — verification only; test already existed on main via `s2-1`

---

### `sprint3/s3-8-intervention-routing` — PR #39 · Merged

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/app/modules/tutor/router.py` | +2 | Stale `encouragement` type removed |
| `apps/api/tests/test_tutor_graph.py` | +39 | Parametrised ×3: each event → own type → distinct message |
| `docs/stories/4-14-intervention-routing.md` | +153 | Story |

**Tasks covered:** `intervention_routing`

---

## Sprint 4 Task Branches

### `sprint4/s4-4-ws-load-test` — PR #40 · Merged · [Partial]

| File | Lines | Purpose |
|------|-------|---------|
| `scripts/ws_load_test.py` | +261 | N sessions × M signals; p50/p95/max latency; exit 0 iff 0 drops |
| `apps/api/tests/test_ws_load_test.py` | +138 | 7 unit tests for `summarize()` |
| `docs/sprint4-ws-load-test.md` | +118 | Results (self-test: 50/50, 0 dropped, p50≈3.4ms) |
| `docs/stories/4-15-ws-load-test.md` | +200 | Story |

**Tasks covered:** `ws_load_test` — **production run pending India-region deploy**

---

### `sprint4/s4-5-reconnect-test` — PR #41 · Merged · [Partial]

| File | Lines | Purpose |
|------|-------|---------|
| `apps/api/tests/test_websocket_session.py` | +30 | `test_f7_reconnect_restores_each_of_7_states` (×7 states) |
| `docs/stories/4-16-reconnect-test.md` | +122 | Story |

**Tasks covered:** `reconnect_test` — **live network-fault simulation pending staging server**

---

### `sprint4/s4-analysis-skeletons` — PR #42 · Merged · [All Partial]

| File | Lines | Purpose |
|------|-------|---------|
| `docs/sprint4-ces-threshold-analysis.md` | +96 | Threshold sweep methodology |
| `docs/sprint4-intervention-review.md` | +79 | Ack-rate-per-type methodology |
| `docs/sprint4-cooldown-tuning.md` | +80 | Cooldown LAG analysis methodology |
| `docs/sprint4-intervention-copy-review.md` | +71 | 5-point copy review checklist |

**Tasks covered:** `threshold_tuning`, `intervention_response_review`, `cooldown_tuning`, `intervention_copy_review` — **all pending real session data**

---

## Coverage Gaps

Tasks with no dedicated branch:

| Task | Sprint | Tracker status | Where the code lives | Missing |
|------|--------|----------------|----------------------|---------|
| `ws_handler_scaffold` | 0 | Completed | `feature/dev4-redis-ces-buffer` | Branch, story |
| `jwt_middleware` | 0 | Completed | `feature/dev4-redis-ces-buffer` | Branch, story |
| `langgraph_scaffold` | 0 | Completed | `feature/dev4-redis-ces-buffer` | Branch, story |
| `tutor_stub` | 0 | Completed | `feature/dev4-redis-ces-buffer` | Branch, story |
| `sentry_wired` | 0 | Completed | `feature/dev4-redis-ces-buffer` | Branch, story |
| `ws_message_routing` | 1 | Completed | `sprint2/s2-3-quizzing-teachback-flow` | Dedicated S1 branch |
| `attention_ingestion` | 3 | Completed (no date) | Sprint 2 branches (unverified) | Branch, date, story |
| `ces_redis_buffer` | 3 | Completed (no date) | Sprint 2 branches (unverified) | Branch, date, story |
| `intervention_trigger` | 3 | Completed (no date) | Sprint 2 branches (unverified) | Branch, date, story |
| `cooldown_enforcement` | 3 | Completed (no date) | Sprint 2 branches (unverified) | Branch, date, story |
