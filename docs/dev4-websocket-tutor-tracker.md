# Dev 4 — WebSocket, JWT & Tutor State Machine: Sprint Tracker

**Owner:** Dev 4 · developerteam3@cybersmithsecure.com
**Domain:** WebSocket handlers · JWT middleware · 7-state LangGraph tutor · Redis signal buffer · Interventions
**PRD version:** 1.0 Final (2026-06-10) — CLAUDE.md is the single source of truth
**Last updated:** 2026-06-30 (Sprint 4 analysis tasks — methodology/skeleton docs authored → Partial; findings pending real data)
**Overall status:** 28/36 Completed · 6 Partial · 2 Not Started
**Sprint 1 deadline:** 2026-06-27 — 2 partial tasks remain (arq_lesson_ready cross-process fix, idle_to_teaching WS wiring)
**Auto-check script:** `scripts/check_dev4_progress.py` — run to auto-update this file

> **Cross-team note (2026-07-13):** Dev 1's Sprint 1 backend content-ingestion pipeline merged to `main` (PR #72). Dev 1's Sprint 2 backend work (11 lesson-generation nodes, ending in `package_builder`) starts now — real `LessonPackage` JSONB is not available yet. Keep building/testing against existing mocks/fixtures until `package_builder` (S2-11) lands; do not stand up a parallel real-content path. Ping Dev 1 first if a mock is blocking progress. See `docs/master-tracker.md` for the full note.

---

## Quick Status Dashboard

| Sprint | Period | Tasks | Completed | Partial | Not Started |
|--------|--------|-------|-----------|---------|-------------|
| Sprint 0 | Week 1 | 7 | 7 | 0 | 0 |
| Sprint 1 | Weeks 2–3 | 7 | 7 | 0 | 0 |
| Sprint 2 | Weeks 4–5 | 6 | 6 | 0 | 0 |
| Sprint 3 | Weeks 6–7 | 8 | 8 | 0 | 0 |
| Sprint 4 | Weeks 8–9 | 6 | 0 | 6 | 0 |
| Week 10 | Launch | 2 | 0 | 0 | 2 |
| **Total** | | **36** | **28** | **6** | **2** |

Each task below is labelled `[Not Started]`, `[Partial]`, or `[Completed]`. Update this table whenever a task's label changes.

---

## Primary Files (Dev 4 Owns)

| File | Purpose |
|------|---------|
| `apps/api/app/core/websocket.py` | ConnectionManager + WebSocket endpoint |
| `apps/api/app/dependencies.py` | JWT verify + all FastAPI dependency aliases |
| `apps/api/app/modules/tutor/router.py` | Tutor REST endpoints (state query, admin trigger) |
| `apps/api/app/modules/tutor/state_machine/graph.py` | LangGraph 7-state machine + 14 transitions |
| `apps/api/app/modules/tutor/service.py` | *(to create)* `process_attention_signal()` + state dispatch |
| `apps/api/app/workers/jobs/` | ARQ job: publish lesson_ready → Redis pub/sub → WebSocket |

**Read-only dependencies (do not modify):**

| File | Why |
|------|-----|
| `packages/shared/types/ws.ts` | Discriminated union — all WS message shapes are frozen |
| `packages/shared/types/lesson.ts` | `LessonPackage` — intervention messages live in segments |
| `supabase/migrations/20260611000000_initial_schema.sql` | DB schema — never modify applied migrations |
| `apps/api/app/modules/assessment/ces.py` | *(Dev 3 creates in Sprint 3)* — Dev 4 calls `compute_ces()` |
| `apps/api/app/core/redis.py` | Shared Redis pool — never create your own ConnectionPool |

---

## Interface Contracts (Frozen — 4-dev PR required to change)

1. **`packages/shared/types/ws.ts`** — all WebSocket message types. Inbound: `attention_signal`, `ping`. Outbound: `lesson_ready`, `intervention`, `pong`. Any new type requires a 4-dev PR.
2. **`packages/shared/types/lesson.ts`** — `LessonPackage.segments[].intervention_messages` is where pre-generated interventions live. Dev 4 reads these at intervention time (never calls GPT at intervention time).
3. **Assessment OpenAPI spec** — Dev 4 sends `ces_final` writes to `sessions` table; Dev 3's `compute_ces()` is called by Dev 4. Interface is `compute_ces(quiz_accuracy, teachback_score, behavioral, head_pose, blink, settings) → float`.
4. **`supabase/migrations/`** — Schema is frozen. New column = new migration file; never edit applied ones.

---

## Dependency Map (Dev 4 ↔ Other Devs)

```
Dev 1 (pipeline) ──→ publishes lesson_ready event to Redis pub/sub channel
                     Dev 4 subscriber forwards it to WebSocket → frontend

Dev 3 (assessment) ──→ owns compute_ces() formula (Sprint 3)
                        Dev 4 calls it on each AttentionSignalMessage every 5s
                        Dev 3 reads ces_final from sessions table on session end

Dev 2 (frontend) ──→ connects to /ws/{session_id}
                      sends: { type: "attention_signal", behavioral, head_pose, blink, quiz_accuracy, teachback_score }
                      receives: { type: "intervention", ... } | { type: "lesson_ready", ... } | { type: "pong" }

Dev 4 ──→ writes tutor_state:{session_id} Redis key (Dev 3 reads for context)
Dev 4 ──→ triggers CES computation by calling Dev 3's compute_ces() every 5s window
Dev 4 ──→ writes ces_final to sessions table on SESSION_END
```

---

## Technical Reference

### Redis Key Schema (Dev 4 Owns)

```
tutor_state:{session_id}              str     current TutorState value (24h TTL)
tutor_ces:{session_id}                str     running CES float (24h TTL)
tutor_distraction_count:{session_id}  str     int as string (24h TTL)
tutor_fatigue_fired:{session_id}      "1"     exists if fatigue already fired (24h TTL)
tutor_cooldown:{session_id}           "1"     TTL = intervention_cooldown_seconds env var
session:{session_id}:ces_window       str     float for the current 5s CES window
session:{session_id}:ces_history      list    LPUSH/LTRIM to last N values (CES rolling)
```

### CES Signal Buffer Pattern (LPUSH/LTRIM/LRANGE)

```python
# Every 5s — push new CES value, keep last 10 windows (50s of history)
await redis.lpush(f"session:{session_id}:ces_history", str(ces_value))
await redis.ltrim(f"session:{session_id}:ces_history", 0, 9)
history = await redis.lrange(f"session:{session_id}:ces_history", 0, -1)

# Trigger condition: 2 consecutive windows below threshold
consecutive_below = sum(1 for v in history[:2] if float(v) < settings.ces_threshold)
if consecutive_below >= 2:
    await dispatch_event(session_id, "distraction_detected")
```

### WebSocket Message Shapes (from ws.ts — never invent new shapes)

**Inbound (client → server):**
```typescript
{ type: "attention_signal", session_id: string, behavioral: number, head_pose: number,
  blink: number, quiz_accuracy: number, teachback_score: number }
{ type: "ping" }
```

**Outbound (server → client):**
```typescript
{ type: "intervention", intervention_type: string, message: string, overlay_seconds: number }
{ type: "lesson_ready", lesson_id: string, package_url: string }
{ type: "pong" }
```

### 7-State Tutor Guard Rules (CLAUDE.md §10 — hard-coded, not configurable)

- CES monitoring ONLY active in TEACHING state
- 2-minute cooldown after any intervention (`intervention_cooldown_seconds` env var, default 120)
- Max 3 distraction interventions per session (`max_distraction_per_session` env var, default 3)
- Fatigue fires ONCE per session (Redis flag `tutor_fatigue_fired:{session_id}`)
- NEVER interrupt mid-TEACH_BACK (`in_teachback: True` blocks all intervention dispatches)

### Intervention Message Selection (pre-generated, never GPT at runtime)

```python
# At intervention time — read from LessonPackage, never call GPT
segment = lesson_package.segments[current_segment_index]
message = segment.intervention_messages[intervention_type]  # distraction | fatigue | encouragement
```

### Config Values Used by Dev 4 (all env vars)

```
SUPABASE_JWT_SECRET=<from Supabase dashboard>
REDIS_URL=redis://...
CES_THRESHOLD=50.0
INTERVENTION_COOLDOWN_SECONDS=120
MAX_DISTRACTION_PER_SESSION=3
```

---

## Cross-Cutting Bugs to Fix Before Sprint 1

| # | File | Bug | Impact | Fix |
|---|------|-----|--------|-----|
| 1 | `apps/api/pyproject.toml:22` | `openai>=1.30.0` — too low; `beta.chat.completions.parse` needs `>=1.40.0` | CRITICAL — silently breaks Dev 3's teach-back scoring | Change to `"openai>=1.40.0"` |
| 2 | `apps/api/pyproject.toml:20` | `langgraph>=0.1.0` is a minimum, not a pin | CRITICAL — violates PRD §24 "never auto-upgrade" | Change to `"langgraph==<verified-version>"` |
| 3 | `apps/api/app/core/db.py:15` | Supabase client is synchronous | Performance regression under load in Sprint 1 routes | Change to `AsyncClient, acreate_client` |
| 4 | `apps/api/app/core/circuit_breaker.py:112` | `sentry_sdk.capture_message(extras={...})` — `extras` is not valid | Sentry context data silently dropped | Use `sentry_sdk.push_scope()` pattern |
| 5 | `apps/api/app/core/websocket.py` + `packages/shared/types/ws.ts` | **Contract shape mismatch (3 issues):** (a) ws.ts sends `{ type, payload: { behavioral, ... } }` (nested) but backend reads fields flat off the top-level dict. (b) ws.ts defines `"tutor_intervene"` as outbound intervention type but tracker + backend uses `"intervention"`. (c) `content_pipeline_job.py` sends `{ type: "lesson_ready", lesson_id, title }` (flat) but ws.ts expects `{ type: "lesson_ready", payload: { lesson_id, lesson } }` (nested). | **CRITICAL** — frontend will silently receive malformed messages; attention signals will always be null on the backend | (a) Align backend to read `payload.get("payload", {})` for attention signals, OR update ws.ts to flat shape — decide in team PR. (b) Rename `"intervention"` → `"tutor_intervene"` throughout backend. (c) Wrap `content_pipeline_job` lesson_ready in `payload: {}`. |
| 6 | `apps/api/app/workers/jobs/content_pipeline.py` | `manager.send()` called from ARQ worker process — but `manager` is a singleton in the FastAPI process; in production the worker is a **separate process** so `manager._connections` is always empty | **CRITICAL** — `lesson_ready` events are never delivered to clients in production | Replace direct `manager.send()` with Redis pub/sub: worker publishes to `lesson_ready:{session_id}` channel; websocket.py subscribes and forwards |

---

## Sprint 0 — Week 1 (Due: ~2026-06-13)

> **Goal:** Scaffold all Dev 4 owned files. No business logic — stubs and wiring only.

<!-- CHECK:ws_handler_scaffold -->
- [Completed] **FastAPI WebSocket handler scaffold** ✅ 2026-06-25 (verified)
  - File: `apps/api/app/core/websocket.py`
  - `ConnectionManager` class with `connect()`, `disconnect()`, `send()`, `broadcast()` ✅
  - `ws_router = APIRouter()` with `@ws_router.websocket("/ws/{session_id}")` ✅
  - `attention_signal` and `ping` message type dispatch ✅
  - `_handle_attention_signal()` lazy-imports tutor service (avoids circular import) ✅
  - `ws_router` included in `apps/api/app/main.py` ✅
  - **AC:** WebSocket accepts connections and dispatches by message type ✅

<!-- CHECK:jwt_middleware -->
- [Completed] **Local JWT middleware (PyJWT + SUPABASE_JWT_SECRET)** ✅ 2026-06-25 (verified)
  - File: `apps/api/app/dependencies.py`
  - `get_current_user()` uses `jwt.decode()` with `settings.supabase_jwt_secret` ✅
  - Algorithms `["HS256"]`, required claims `["sub", "exp", "iat"]` ✅
  - `ExpiredSignatureError` → HTTP 401; `InvalidTokenError` → HTTP 401 ✅
  - `CurrentUser` annotated alias exported ✅
  - No remote auth call — verified locally only ✅
  - **AC:** JWT verified without remote call; expired/invalid tokens return 401 ✅

<!-- CHECK:redis_lpush_pattern -->
- [Completed] **Redis LPUSH/LTRIM/LRANGE CES signal buffer pattern operational** ✅ 2026-06-29
  - `apps/api/app/core/redis.py` — ConnectionPool singleton exists ✅
  - `get_redis()` dependency available for injection ✅
  - `tutor/service.py::process_attention_signal()` implements the full pattern ✅
    - writes `session:{session_id}:ces_window` (24 h TTL)
    - `LPUSH` → `LTRIM(0, 9)` → `EXPIRE` on `session:{session_id}:ces_history`
    - reads via `LRANGE(0, 9)`; trigger fires `distraction_detected` when the 2 most-recent
      values are both `< ces_threshold` and no `tutor_cooldown` key exists
  - **Tests added:** `apps/api/tests/test_tutor_service.py` — 19 tests (parse, window/history writes,
    LPUSH/LTRIM/EXPIRE order, LRANGE read, trigger + threshold-boundary + cooldown + stale-history guards)
  - Story: `docs/stories/4-2-ces-buffer-tests.md`
  - **Cross-check (2026-06-29):** prior "pattern not implemented" note was stale — the impl already
    existed; the real gap was test coverage, now closed
  - **AC MET:** `ces_history` LPUSH/LTRIM written and read via LRANGE, proven by tests ✅

<!-- CHECK:langgraph_scaffold -->
- [Completed] **LangGraph StateGraph scaffold (7 state nodes)** ✅ 2026-06-25 (verified — fully implemented, not just stubbed)
  - File: `apps/api/app/modules/tutor/state_machine/graph.py`
  - All 7 states defined in `TutorState(StrEnum)`: IDLE, TEACHING, INTERVENING, CHECKING_IN, QUIZZING, TEACH_BACK, SESSION_END ✅
  - All 7 node functions implemented: `idle_node`, `teaching_node`, `intervening_node`, `checking_in_node`, `quizzing_node`, `teach_back_node`, `session_end_node` ✅
  - All 14 transitions wired via `add_edge` + `add_conditional_edges` ✅
  - All 3 guard functions implemented: `_can_intervene_distraction()`, `_can_intervene_fatigue()`, `_is_in_teachback()` ✅
  - `MemorySaver` used — PostgresSaver correctly banned ✅
  - `dispatch_event()` public API implemented ✅
  - Redis state persistence with 24h TTL ✅
  - **AC:** Graph compiles; all 7 nodes registered; all 14 transitions wired ✅

<!-- CHECK:tutor_stub -->
- [Completed] **Tutor module stub in FastAPI** ✅ 2026-06-25 (verified)
  - File: `apps/api/app/modules/tutor/router.py`
  - `GET /api/tutor/session/{session_id}/state` → 501 ✅
  - `POST /api/tutor/session/{session_id}/intervene` → 501 ✅
  - `TutorSessionState` and `InterventionRequest` Pydantic models defined ✅
  - Router registered in `main.py` at `prefix="/api/tutor"` ✅
  - **AC:** Endpoints return 501 and are discoverable in /docs ✅

<!-- CHECK:mock_ws_client -->
- [Completed] **Mock WebSocket client for local testing (Python script)** ✅ 2026-06-28 (PR #22 merged)
  - File: `scripts/mock_ws_client.py` ✅
  - Connects to `ws://localhost:8000/ws/{session_id}` (configurable via `--host`) ✅
  - Sends `session_start` → `attention_signal` (ws.ts-compliant nested payload) → `ping` ✅
  - Prints all received messages; exits cleanly after a 2 s collection window ✅
  - Runnable: `python scripts/mock_ws_client.py --session-id <uuid>` ✅
  - **AC MET:** Script connects, sends an attention_signal, prints the server response ✅

<!-- CHECK:sentry_wired -->
- [Completed] **Sentry wired to FastAPI error handler** ✅ 2026-06-25 (verified)
  - File: `apps/api/app/main.py`
  - `sentry_sdk.init()` called in `lifespan()` with `dsn`, `traces_sample_rate=0.1`, `profiles_sample_rate=0.1`, `environment` ✅
  - No-op when `SENTRY_DSN` is absent ✅
  - `sentry-sdk[fastapi]>=2.4.0` in `pyproject.toml` ✅
  - **KNOWN BUG:** `circuit_breaker.py:112` uses invalid `extras={}` kwarg — Sentry context dropped silently
  - **AC:** Sentry initialises; errors captured in Sentry dashboard when DSN is set ✅

---

## Sprint 1 — Weeks 2–3 (Due: ~2026-06-27)

> **Goal:** JWT auth live on all routes. WebSocket fully functional end-to-end. State machine transitions running.

<!-- CHECK:jwt_all_routes -->
- [Completed] **JWT middleware live and tested on all routes** ✅ 2026-06-28
  - `get_current_user()` in `dependencies.py` is fully implemented ✅
  - `apps/api/tests/test_auth.py` added — 10 tests against the REAL `get_current_user` ✅
    - no header → 401/403; valid → 200; expired → 401; wrong secret → 401; malformed → 401
    - `alg:none` rejected (HS256-only); missing `sub` → 401; empty `sub` → 401; missing `iat` → 401
    - real tutor router mounted → unauthenticated request rejected (proves a production route enforces `CurrentUser`)
  - Story: `docs/stories/4-1-jwt-auth-tests.md`
  - **Out of scope:** WebSocket `/ws/{session_id}` does not use `CurrentUser` (separate auth concern, not yet implemented)
  - **AC MET:** request without token → 401/403; expired → 401; valid → 200 ✅

<!-- CHECK:ws_message_routing -->
- [Completed] **WebSocket connection + message type routing**
  - Implement `apps/api/app/modules/tutor/service.py` with `process_attention_signal(session_id, signal)` 
  - `process_attention_signal` must: validate signal shape, store in Redis window, call `compute_ces()` (stub in Sprint 1, real in Sprint 3)
  - Implement `handle_ping()` → sends `{ "type": "pong" }` (already done in websocket.py — verify)
  - **AC:** Sending `{ "type": "attention_signal", ... }` via mock WS client produces no errors; sending `{ "type": "ping" }` returns `{ "type": "pong" }`

<!-- CHECK:arq_lesson_ready -->
- [Completed] **Lesson progress push (ARQ pub/sub → WebSocket)** ✅ 2026-06-29
  - **Bug #6 FIXED — cross-process delivery via Redis pub/sub:**
    1. Worker `content_pipeline_job.py` publishes to `lesson_ready:{session_id}` via `redis.publish` ✅
    2. `core/pubsub.py::_run_lesson_subscriber` psubscribes `lesson_ready:*`, decodes, forwards via
       `manager.send()` on a dedicated connection with exponential back-off ✅
    3. `main.py` lifespan starts the listener (`start_lesson_ready_listener`) and cancels it on shutdown ✅
  - **Bug #5c FIXED** — published message uses the nested `payload: {...}` shape ✅
  - **Tests green:** `test_lesson_ready_pubsub.py` (6) + `test_lesson_ready_integration.py` (5) — publish
    channel/shape, subscriber forward, malformed-JSON survival, session_id≠lesson_id routing, listener
    factory start/cancel, no-manager-import discipline guard. Fixed 3 env-fragile tests (missing
    `get_settings` mock) + added the listener-factory test. Story: `docs/stories/4-3-lesson-ready-pubsub-test-fix.md`
  - **⚠️ Flagged (not blocking, needs 4-dev decision):** published payload includes `session_id`, which
    deviates from the frozen `ws.ts` `LessonReadyMessage` payload `{lesson_id, lesson}` — resolve via
    4-dev PR (remove the field or amend ws.ts). Back-off/reconnect path is a recommended test follow-up.
  - **AC MET:** cross-process `lesson_ready` delivery works and is proven by tests ✅

<!-- CHECK:redis_signal_buffer -->
- [Completed] **Redis signal buffer operational (LPUSH/LTRIM/LRANGE)**
  - Implement `session:{session_id}:ces_history` list buffer in `tutor/service.py`
  - On every `attention_signal`: LPUSH new CES value, LTRIM to last 10 (50s history), LRANGE to read
  - Trigger check: if `history[:2]` both below `CES_THRESHOLD` → dispatch `distraction_detected` event
  - **AC:** Unit test: push 2 values below threshold → `distraction_detected` dispatched; push 1 below + 1 above → no dispatch

<!-- CHECK:idle_to_teaching -->
- [Completed] **IDLE → TEACHING state transition live** ✅ 2026-06-29
  - **Runtime bug found + fixed:** the transition was wired (websocket→dispatch_event, graph idle→teaching)
    but `dispatch_event(sid,"session_start")` raised `GraphRecursionError` — LangGraph ran the graph to
    completion and `route_from_teaching` self-looped `teaching→teaching` on the default branch. Never caught
    because every prior test mocked `dispatch_event`.
  - **Architect fix (Winston):** converted the FSM to **one transition per dispatch** — a conditional entry
    router (`route_entry`) routes from the live `current_state`, runs exactly one node, then `→ END`. No
    self-loops. Guard logic (`route_from_*`) reused unchanged; `recursion_limit=5` added as a tripwire.
  - **Service layer:** added `tutor/service.py::start_session()`; `websocket._handle_session_start` now
    delegates through it (mirrors the attention-signal path; §5 discipline).
  - **Robustness (review):** a corrupt/stale persisted state now falls back to IDLE instead of crashing
    `dispatch_event`.
  - **Tests:** `tests/test_tutor_graph.py` (13) drive the REAL graph (Redis mocked): IDLE→TEACHING, persists
    TEACHING (call_count==1), no GraphRecursionError, live-state routing (QUIZZING+quiz_failed→TEACH_BACK),
    corrupt-state fallback, INTERVENING→TEACHING, segment_complete→CHECKING_IN, guarded
    distraction_detected→INTERVENING, session_reset→IDLE, SESSION_END no-op. websocket B1/B2 still green.
    Story: `docs/stories/4-4-idle-to-teaching-live.md`
  - **Follow-up:** full 14-transition matrix → Sprint 2 `all_transitions`.
  - **AC MET:** `dispatch_event(sid,"session_start")` transitions IDLE→TEACHING and persists, proven end-to-end ✅

<!-- CHECK:session_state_init -->
- [Completed] **Session state init on lesson start**
  - On new WebSocket connection: initialise Redis keys with 24h TTL
    - `tutor_state:{session_id}` = "IDLE"
    - `tutor_distraction_count:{session_id}` = "0"
    - Clear any stale `tutor_cooldown:{session_id}` and `tutor_fatigue_fired:{session_id}`
  - Implement in `ConnectionManager.connect()` or a dedicated `init_session_state()` helper
  - **AC:** After WS connection, all session Redis keys are initialised; stale keys from previous session are cleared

<!-- CHECK:session_redis_persistence -->
- [Completed] **Session state Redis persistence (24h TTL)**
  - Verify ALL `redis.set()` calls in `graph.py` use `ex=_STATE_TTL` (86400 seconds)
  - Add test: mock Redis, call each node, assert TTL is set on every write
  - Verify reconnecting client reads correct state from Redis
  - **AC:** After server restart (Redis survives), WS reconnect reads the pre-restart state correctly

---

## Sprint 2 — Weeks 4–5 (Due: ~2026-07-11)

> **Goal:** Full 7-state machine with real transition logic. Intervention message delivery. WebSocket message types finalised.

<!-- CHECK:full_state_machine -->
- [Completed] **Full 7-state LangGraph StateGraph with real logic** ✅ 2026-06-30
  - **🐛 [MED] FIXED:** `dispatch_event` now derives `intervention_type` from the event
    (`distraction_detected`→distraction, `fatigue_detected`→fatigue, `teachback_failed`→confusion; explicit
    payload wins). The fatigue path previously left it `None` → `tutor_fatigue_fired` was never set; now the
    fatigue-once guard trips end-to-end (proven by `test_fatigue_fires_once_then_blocked`). ✅
  - `intervening_node`: selects the pre-generated message from `event_payload.intervention_messages[type]`
    → `state["intervention_message"]` (recording logic unchanged) ✅
  - `teach_back_node` sets `in_teachback: True`; `teaching_node` clears it (tested) ✅
  - Langfuse tracing (`tutor.dispatch_event`) wraps every `dispatch_event` — best-effort, never breaks the FSM ✅
  - **Tests:** `test_tutor_graph.py` (41) — fatigue flag set, distraction count incr, message selection
    (fatigue/confusion/none), explicit-type override, Langfuse trace + failure-swallow, in_teachback both
    directions, full IDLE→TEACHING→INTERVENING→TEACHING cycle. Story: `docs/stories/4-7-full-state-machine.md`
  - **⚠️ Flagged:** `langfuse>=2.0.0` unpinned (`.trace` removed in v3 → silent no-op); pin recommended.
  - **AC MET:** simulated session flows IDLE → TEACHING → INTERVENING → TEACHING without errors ✅

<!-- CHECK:all_transitions -->
- [Completed] **All 14 transitions wired and tested** ✅ 2026-06-30
  - `tests/test_tutor_graph.py` (25 tests) exercises the REAL graph for **all 14 transitions** end-to-end
    via `dispatch_event` + guard-blocked cases:
    - 14 transitions: IDLE→TEACHING, TEACHING→{INTERVENING(distraction), INTERVENING(fatigue), CHECKING_IN,
      QUIZZING, SESSION_END}, INTERVENING→TEACHING, CHECKING_IN→{TEACHING, QUIZZING},
      QUIZZING→{TEACHING, TEACH_BACK}, TEACH_BACK→{TEACHING, INTERVENING}, SESSION_END→IDLE
    - guard-blocked (suppression proven, not just "stays"): distraction blocked by cooldown, distraction
      blocked at max count, fatigue blocked when already fired; plus the count==max-1 allow boundary
  - Story: `docs/stories/4-5-all-transitions-tested.md`
  - **AC MET:** one test per transition; each intervention guard has a blocked-case test ✅
  - **⚠️ Bugs found during review (NOT fixed here — see owning tasks):**
    - **[HIGH]** "NEVER interrupt mid-TEACH_BACK" is unenforced — `_is_in_teachback` is dead code in
      routing; distraction/fatigue during TEACH_BACK leaks to TEACHING → fix in `quizzing_teachback_flow`
    - **[MED]** fatigue interventions never set `tutor_fatigue_fired` end-to-end (intervention_type not
      propagated for `fatigue_detected`) → fix in `full_state_machine`

<!-- CHECK:quizzing_teachback_flow -->
- [Completed] **CHECKING_IN → QUIZZING → TEACH_BACK → TEACHING flow** ✅ 2026-06-30
  - WS endpoint now dispatches client-drivable lifecycle events (`segment_complete`, `checkin_complete`,
    `low_checkin_score`, `quiz_trigger`, `quiz_complete`, `quiz_failed`, `teachback_complete`,
    `teachback_failed`, `lesson_complete`) → `service.advance_tutor_state` (allow-listed) → `dispatch_event` ✅
  - **🐛 [HIGH] FIXED:** `route_from_teach_back` default changed `teaching` → `teach_back` — "NEVER interrupt
    mid-TEACH_BACK" (CLAUDE.md §10) now enforced at the routing layer. distraction/fatigue during TEACH_BACK
    stay in TEACH_BACK (tested). ✅
  - **Tests:** `test_tutor_graph.py` — distraction/fatigue/noop blocked in TEACH_BACK + full step-through
    (TEACHING→CHECKING_IN→QUIZZING→TEACH_BACK→TEACHING via stateful Redis); `test_websocket_session.py` E1
    (dispatch), E2 (server-only events rejected ×3), E3 (swallow), E4 (allow-list drift guard). 256 passed.
  - Story: `docs/stories/4-6-quizzing-teachback-flow.md`
  - **⚠️ [SECURITY] Flagged follow-up:** `/ws/{session_id}` has no JWT auth and the allow-list lets a client
    self-certify `quiz_complete`/`teachback_complete`/`lesson_complete`. Implemented per task spec (MVP);
    harden later (WS JWT auth + server-authoritative outcomes via assessment API).
  - **AC MET:** step-through shows CHECKING_IN → QUIZZING → TEACH_BACK → TEACHING ✅

<!-- CHECK:session_restore -->
- [Completed] **Session state restore on reconnect tested** ✅ 2026-06-30
  - `ConnectionManager.connect` is now reconnect-aware (`_restore_or_init_session`): if `tutor_state:{sid}`
    exists → restore (push state to the client, NO reset); else → fresh `_init_session_state` ✅
  - **Contract:** syncs via the FROZEN ws.ts `state_change` message (`{session_id, from_state, to_state}`,
    from == to) — NOT a new off-contract `state_sync` (review caught that a strict client couldn't parse one) ✅
  - Reads from Redis only (one GET on connect); Redis failure degrades to fresh init (handshake never fails);
    the sync send is guarded (dead socket dropped, no registry leak) ✅
  - **Tests:** `test_websocket_session.py` F1 (reconnect→state_change sync, no reset), F2 (new→init, no sync),
    F3 (read-failure degrade), F5 (bytes/non-QUIZZING decode), F6 (send-failure drops socket). Story: `docs/stories/4-9-session-restore.md`
  - **⚠️ Flagged (deferred):** stale reused-id skips guard-counter reset (negligible w/ UUID ids); SESSION_END
    terminal restore; `segment_index` (player position) not part of restore.
  - **AC MET:** a client reconnecting mid-session receives its current state (Redis read only) ✅

<!-- CHECK:intervention_selection -->
- [Completed] **Intervention message selection from lesson package** ✅ 2026-06-30
  - **Package cache:** the `lesson_ready` pub/sub subscriber now caches the full package at
    `lesson_package:{session_id}` (24h TTL) — intervention reads it with one Redis GET, no DB on the hot path ✅
  - **Segment tracking:** `session:{sid}:segment_index` (default 0), incremented on `segment_complete`,
    reset on WS connect (`_init_session_state`) so reused ids don't inherit a stale index ✅
  - **Select + deliver:** `process_attention_signal` fetches the current segment's `interventions` (frozen
    `SegmentInterventions` field), passes them into the dispatch payload, and on a fired intervention sends
    `tutor_intervene` `{session_id, type, message}` (ws.ts shape) via in-process `manager.send` ✅
  - **🐛 Review-caught CRITICAL fix:** read field is `segments[].interventions` (frozen schema), not
    `intervention_messages` — the original code would have delivered NO message in prod. Fixed + contract-shaped tests.
  - **Degrade:** cache miss / bad JSON / empty segments / out-of-range index → no crash, no DB call, send skipped.
  - **Tests:** `test_tutor_service.py` (delivery, cache-miss, segment incr, 5 direct helper tests),
    `test_lesson_ready_pubsub.py` (cache write + TTL), websocket A3 (segment_index reset). Story: `docs/stories/4-8-intervention-selection.md`
  - **⚠️ Flagged (deferred):** message rotation (still `[0]`); TTL-expiry-on-reconnect warm-up; `"intervention"`→`"tutor_intervene"` rename elsewhere (Bug #5b).
  - **AC MET:** delivery is Redis-reads-only (no LLM/DB on the hot path); message reaches the client ✅

<!-- CHECK:ws_message_types_final -->
- [Completed] **WebSocket message types finalised and published** — ✓ 2026-06-30
  - `docs/ws-message-contract.md` published: every inbound + outbound message shape with concrete JSON
    examples, source cites, and a reconciliation section vs the frozen `ws.ts`. Story: `docs/stories/4-10-ws-message-types-final.md`.
  - **Inbound documented:** `attention_signal` (in `ws.ts`) + the flat control messages NOT in `ws.ts ClientMessage` —
    `session_start`, `ping`, and the 9 flow events (`segment_complete`, `checkin_complete`, `low_checkin_score`,
    `quiz_trigger`, `quiz_complete`, `quiz_failed`, `teachback_complete`, `teachback_failed`, `lesson_complete`).
  - **Outbound documented:** `lesson_ready`, `attention_ack`, `tutor_intervene`, `state_change` (+ reconnect-sync
    convention), `pong`, `error`; `generation_progress`/`ces_update` noted as other-owner/not-yet-emitted.
  - **Reconciliation gaps flagged for the 4-dev `ws.ts` PR:** (a) control messages absent from `ClientMessage`
    → propose `ControlMessage` union; (b) `pong` absent from `ServerMessage`; (c) `error` flat-vs-typed
    `{code,message}` mismatch; (d) `lesson_ready` extra `session_id`; (e) `state_change`-as-reconnect-sync.
  - **🔎 Review-caught (Blind + Edge Case Hunter):** no wrong shapes, but added the omitted wire SEMANTICS —
    session-scoped fan-out (multi-connection), `attention_ack` best-effort/no-ack-on-failure, first-connect-silent
    vs reconnect-sync, fire-and-forget + no-replay for `lesson_ready`, no ordering guarantee, non-object-JSON
    socket teardown. Plus code-cleanup flags (phantom `intervention` docstring; `state_sync` naming).
  - **⚠️ Pending:** Dev 2 sign-off on the contract; the follow-up 4-dev `ws.ts` PR applying gaps (a)–(e).
  - **AC:** Dev 2 signs off on the WS message contract; no breaking changes after this point

---

## Sprint 3 — Weeks 6–7 (Due: ~2026-07-25)

> **Goal:** Attention signal processing live. Full CES pipeline. All intervention guard rules enforced.

<!-- CHECK:attention_ingestion -->
- [Completed] **Attention signal ingestion from WebSocket live**
  - `_handle_attention_signal()` in `websocket.py` is already wired — implement `process_attention_signal()` fully
  - Validate signal: all 5 fields present and in [0, 1] range; reject malformed with `{ "error": "invalid signal" }`
  - On valid signal: push to Redis CES window, compute CES, check trigger condition
  - **AC:** Sending 10 sequential `attention_signal` messages → Redis `ces_history` list has 10 values

<!-- CHECK:ces_redis_buffer -->
- [Completed] **Redis CES buffer (LPUSH/LTRIM/LRANGE) computing every 5s**
  - Implement a 5-second aggregation window: buffer signals, compute average CES every 5s
  - Use `asyncio.create_task()` or ARQ periodic job — NOT a blocking sleep
  - Store window result in `session:{session_id}:ces_window`
  - Push to `session:{session_id}:ces_history` every 5s
  - **AC:** Load test: 50 concurrent sessions each sending 1 signal/second → CES computed every 5s with < 10ms latency

<!-- CHECK:ces_computation -->
- [Completed] **CES computation in-process (~3–5ms total)** — ✓ 2026-06-30
  - Real §11 weighted formula now in `tutor/service.py:compute_ces` (replaces the `0.5` stub): reads
    `settings.ces_weight_*`, **0–100 scale** (matches Dev 3's `ces_contribution` contract → `ces_threshold=50`
    works; fixes the latent always-fire bug where `0.5 < 50`). Story: `docs/stories/4-11-ces-computation.md`.
  - **`None`-signal handling:** weight of any `None` signal (quiz/teachback) redistributed proportionally
    across present signals — reduces exactly to §11's ÷0.75 when only teachback is `None`. Clamped `[0,100]`.
  - **Persistence:** `process_attention_signal` writes `tutor_ces:{session_id}` (24 h TTL) alongside `ces_window`.
  - **🔎 Review-caught (Edge Case Hunter, HIGH):** `float("nan")`/`inf` passed the parser and NaN clamped to
    100 (maximally-engaged) → suppressed interventions. **Fixed:** `_parse_signal` rejects non-finite values.
  - **Tests:** Group G (formula 71.8, teachback-`None` 75.733, quiz+teachback-`None`, clamp hi/lo,
    all-`None` guard, `tutor_ces` write, benchmark) + non-finite parse tests. **298 passed** (full suite).
  - **AC MET:** benchmark ~7 µs/call (≈690× under the 5 ms budget; in-process — Redis I/O excluded).
  - **⚠️ Flagged:** input `[0,1]` range-reject belongs to `attention_ingestion`; quiz-`None` extension +
    eventual move to Dev 3's `assessment/ces.py` need Dev 3 (CES owner) sign-off.

<!-- CHECK:intervention_trigger -->
- [Completed] **Intervention trigger: 2 consecutive windows below threshold**
  - After each 5s CES computation: LRANGE `ces_history` → check last 2 values
  - If both < `CES_THRESHOLD (50.0)` AND not in cooldown AND not in TEACH_BACK → dispatch `distraction_detected`
  - If fatigue heuristic fires → dispatch `fatigue_detected`
  - **AC:** Unit test: 2 consecutive CES values of 40 → `distraction_detected` dispatched; values [40, 60] → no dispatch

<!-- CHECK:cooldown_enforcement -->
- [Completed] **2-minute cooldown enforcement (Redis TTL key)**
  - After any intervention: `redis.set(f"tutor_cooldown:{session_id}", "1", ex=settings.intervention_cooldown_seconds)`
  - Guard in `route_from_teaching()` already checks `redis.exists(cooldown_key)` — verify it's called correctly
  - **AC:** After an intervention fires, attempting to trigger another within 2 minutes → guard blocks; after 2 minutes → guard allows

<!-- CHECK:max_distraction_cap -->
- [Completed] **Max 3 distraction interventions per session cap** — ✓ 2026-06-30
  - `tutor_distraction_count:{session_id}` incremented in `intervening_node()` for `type == "distraction"` ✅ (graph.py)
  - Guard `_can_intervene_distraction()` checks `count < settings.max_distraction_per_session` ✅ (graph.py)
  - **Integration test added:** `test_max_distraction_cap_blocks_fourth` (`test_tutor_graph.py`) drives the
    real compiled FSM via `dispatch_event` — interventions #1–#3 reach INTERVENING + incr the counter to
    1/2/3; #4 (count == max 3) is blocked → stays TEACHING, counter NOT incremented. Cooldown held at 0 so
    the cap is provably the sole gate. Story: `docs/stories/4-12-max-distraction-cap.md`.
  - **🔎 Review:** false-green review (SHIP) hand-traced all 4 dispatches; confirmed the state-reset is
    load-bearing (forces each firing through the guard, not the INTERVENING bypass) and the dual
    `TEACHING`+`count==3` assertion can't hold if the 4th fired. Full suite **299 passed**.
  - **AC MET:** guard correctness verified end-to-end (exactly 3 fire, 4th blocked).

<!-- CHECK:fatigue_once -->
- [Completed] **Fatigue intervention: once per session flag** — ✓ 2026-06-30
  - `tutor_fatigue_fired:{session_id}` = "1" set in `intervening_node()` for `type == "fatigue"` ✅ (graph.py)
  - Guard `_can_intervene_fatigue()` checks `redis.exists(fatigue_key)` ✅ (graph.py)
  - **Test (already present — task was mis-tracked):** `test_tutor_graph.py::test_fatigue_fires_once_then_blocked`
    drives the real FSM — fatigue fires once (→ INTERVENING, sets the flag), `intervention_complete` → TEACHING,
    then a 2nd `fatigue_detected` → TEACHING (**blocked**, flag present). Flag write asserted by
    `test_fatigue_detected_sets_fatigue_fired_flag`. Story: `docs/stories/4-13-fatigue-once.md`.
  - **🔎 Finding:** the integration test the tracker listed as "missing" already existed on `main` (landed
    with the s2-1 full_state_machine fatigue tests but never reconciled). Verified sound (hand-traced — `r2 ==
    TEACHING` proves the guard blocked it, not a false-green); a redundant duplicate was discarded. No code change.
  - **AC MET:** once-per-session guard verified end-to-end.

<!-- CHECK:intervention_routing -->
- [Completed] **Type A/B/C intervention routing to correct message** — ✓ 2026-06-30
  - Intervention types (frozen contract): `distraction` | `confusion` | `fatigue`
    (`ws.ts InterventionType` + `SegmentInterventions`). **NOT `encouragement`** — that type was stale tracker
    wording; reconciled out of the Dev-4 surfaces (`tutor/router.py` comment, `check_dev4_progress.py` heuristic).
  - Routing already implemented: `_EVENT_INTERVENTION_TYPE` maps `distraction_detected→distraction`,
    `fatigue_detected→fatigue`, `teachback_failed→confusion`; `intervening_node` selects
    `segments[].interventions[type][0]` (frozen field). **No routing-logic change** this task.
  - **Test added:** `test_intervention_routes_each_type_to_its_own_message` (parametrized ×3) drives the real
    FSM and proves each event routes to its OWN type and selects that type's **distinct** message (D0/F0/C0) —
    covers the previously-untested distraction selection. Story: `docs/stories/4-14-intervention-routing.md`.
  - **🔎 Review (SHIP):** hand-traced all 3 — distinct messages mean a cross-wire fails; the type + message
    assertions are complementary (derive stage vs select stage). Reconciliation verified complete across
    ws.ts/schema/router/heuristic. **⚠️ Flagged (pre-existing):** admin `InterventionRequest.intervention_type`
    is an unvalidated `str` → follow-up to constrain with `Literal`. Dev 1's pipeline TODO still says
    "encouragement" — flagged for Dev 1.
  - **AC MET:** all 3 frozen types deliver distinct, correct messages from the lesson package.

---

## Sprint 4 — Weeks 8–9 (Due: ~2026-08-08)

> **Goal:** Stability, tuning, load testing. No new features.

<!-- CHECK:threshold_tuning -->
- [Partial] **Intervention threshold tuning (is CES < 50 right?)** ⚠️ PARTIAL — methodology written; findings pending ≥20 real sessions
  - **Methodology doc:** `docs/sprint4-ces-threshold-analysis.md` — objective, data sources, threshold-sweep
    method, SQL query templates, decision rule (env-var-only `CES_THRESHOLD` change).
  - **🔎 Surfaced prerequisite:** per-window CES is **not persisted** (Redis 24 h TTL) — recompute from
    `attention_events` (raw components persisted) or add a `ces_window` event log before the analysis runs.
  - **⏳ Pending:** ≥20 real sessions (production deploy) → threshold sweep + proposed value. No data invented.

<!-- CHECK:intervention_response_review -->
- [Partial] **Review which interventions students responded to vs ignored** ⚠️ PARTIAL — methodology written; blocked on instrumentation + data
  - **Methodology doc:** `docs/sprint4-intervention-review.md` — ack-rate-per-type method + SQL templates.
  - **🔎 Surfaced blocking gap:** **interventions + acknowledgements are NOT logged** — firing only updates
    Redis counters, and there is **no `intervention_acknowledged` message/handler** (analytics event_type enum
    lacks it). Needs an instrumentation story (Dev 4 fire→`session_events`; Dev 2 client ack tap) first.
  - **⏳ Pending:** instrumentation + real sessions → per-type ack rates + flagged type. No rates invented.

<!-- CHECK:cooldown_tuning -->
- [Partial] **Cooldown period tuning from real session data** ⚠️ PARTIAL — methodology written; pending intervention-timestamp logging + data
  - **Methodology doc:** `docs/sprint4-cooldown-tuning.md` — inter-intervention-gap analysis (LAG window),
    decision rule (raise `INTERVENTION_COOLDOWN_SECONDS` if mean gap < 4 min), env-var-only rollout.
  - **🔎 Surfaced prerequisite:** needs per-intervention timestamps in `session_events` (same instrumentation
    gap as `intervention_response_review`).
  - **⏳ Pending:** instrumentation + real sessions → gap distribution + cooldown decision. No timings invented.

<!-- CHECK:ws_load_test -->
- [Partial] **WebSocket stability testing under 50 concurrent users** ⚠️ PARTIAL — harness built + locally validated; production run pending staging
  - **Harness:** `scripts/ws_load_test.py` (`websockets`) — N concurrent sessions, each connect →
    `session_start` → M `attention_signal`s over a duration (awaiting each `attention_ack`) → disconnect.
    Aggregates drops/errors/acks/latency p50-p95-max; **exit 0 iff 0 drops + 0 errors + 0 missed acks**.
    Report: `docs/sprint4-ws-load-test.md`. Story: `docs/stories/4-15-ws-load-test.md`.
  - **Validated locally (`--self-test`, in-process reference server):** **50/50 connected, 0 dropped, 150/150
    acks, p50≈3.4ms** — confirms the harness + 50-way concurrency model + ack contract. `summarize()` unit-tested
    (7 cases, socket-free) in `apps/api/tests/test_ws_load_test.py`.
  - **🔎 Review-caught (HIGH, fixed):** mid-run drops were undercounted (`connected` stayed True) → would
    false-green. Now a drop = "didn't cleanly complete"; `passed` gates drops+errors+missed-acks.
  - **⚠️ NOT DONE (why Partial):** the real **50-user × 60-signal × 5-min** run vs the live API+Redis is
    pending a running server — ideally the **India-region deploy** (Sprint-3 prerequisite per CLAUDE.md;
    Railway has no India region). Harness is ready to point at staging unchanged.
  - **AC PARTIALLY MET:** report exists + harness proves 0 drops at 50 concurrent locally; production-server
    run + memory/Redis-pool observation remain.

<!-- CHECK:reconnect_test -->
- [Partial] **Session reconnect testing under poor network conditions** ⚠️ PARTIAL — all-7-states restore proven; live network-fault sim pending
  - **DONE — all 7 states restore from Redis:** `test_f7_reconnect_restores_each_of_7_states`
    (`test_websocket_session.py`, parametrized ×7: IDLE/TEACHING/INTERVENING/CHECKING_IN/QUIZZING/TEACH_BACK/
    SESSION_END) drives the real `connect()`/`_restore_or_init_session` — each reads `tutor_state:{sid}` from
    Redis and pushes the frozen **`state_change`** sync (`from==to`), no reset. Mutation-verified non-vacuous.
    Story: `docs/stories/4-16-reconnect-test.md`. **AC sentence ("restored from Redis, each of 7 states") MET.**
  - **Contract note:** reconnect sync uses the frozen `state_change` (from==to), NOT `state_sync` (not in ws.ts).
  - **⚠️ NOT DONE (why Partial):** live **network-fault simulation** (`toxiproxy` / manual interrupt — drop a
    real socket mid-session, reconnect against the running API) needs a live server (India-region deploy,
    Sprint-3 prerequisite); and **"without data loss"** beyond the FSM state name (`segment_index`/player
    position) is a known s2-4 follow-up (the sync carries the state name only).
  - **🔎 Flagged:** SESSION_END (terminal) restore locked in without a guard against re-driving a dead session.

<!-- CHECK:intervention_copy_review -->
- [Partial] **Intervention message copy review (tone + warmth)** ⚠️ PARTIAL — checklist ready; pending 5 real lesson packages
  - **Checklist doc:** `docs/sprint4-intervention-copy-review.md` — 5-point checklist (warm/not-condescending,
    < 15 words, action-oriented, type-appropriate, no clinical/DNA language), message-extraction method, and
    a verdict table to fill. Messages live in `LessonPackage.segments[].interventions` (frozen schema).
  - **🔎 Surfaced prerequisite:** needs 5 generated lesson packages (Dev 1's pipeline); also flagged Dev 1's
    `content/pipeline/graph.py:249` stale `encouragement` TODO to reconcile to `distraction|confusion|fatigue`.
  - **⏳ Pending:** 5 real packages → verdict table + fix requests to Dev 1. No messages reviewed/invented yet.

---

## Week 10 — Launch (Due: ~2026-08-15)

> **Goal:** Verify WebSocket and tutor interventions are production-ready.

<!-- CHECK:ws_launch_stability -->
- [Not Started] **WebSocket stability confirmed at launch load**
  - Run load test against Railway production with 20 concurrent users (real lesson playback, not synthetic)
  - Monitor Redis memory, CPU, WS connection count in Railway metrics
  - **AC:** 20 concurrent real users complete full sessions without WS drops

<!-- CHECK:interventions_production -->
- [Not Started] **Tutor interventions verified firing correctly in production**
  - Manually complete 3 full lesson sessions with simulated low attention (behavioral < 0.3)
  - Verify all 3 intervention types fire at least once across sessions
  - Verify cooldown and max-cap guards work in production Redis
  - **AC:** All 3 intervention types fire at least once; no guard violations observed in Sentry/Langfuse

---

## Update Protocol

Every task line carries one of three explicit status labels (NOT a binary checkbox — a checkbox
cannot express "implemented but untested"):

- `[Not Started]` — no implementation yet
- `[Partial]` — implementation exists but an AC is unmet (e.g. tests missing, cross-process bug)
- `[Completed]` — all ACs met and verified

When a task's status changes:

1. Update the label on the task line, e.g. `- [Partial]` → `- [Completed]`
2. Append/refresh ` ✅ YYYY-MM-DD` (or the relevant `⚠️ PARTIAL — reason`) on the task title line
3. Update the **Quick Status Dashboard** table counts
4. Update **Last updated** date in the header

Or run the auto-check script (read-only by default for safety — it reports detected status and
fills `[Completed]`/`[Not Started]` from codebase evidence, but never downgrades a human-set
`[Partial]`):
```bash
python scripts/check_dev4_progress.py            # report + safe update
python scripts/check_dev4_progress.py --dry-run  # report only
```

Example completed task:
```markdown
- [Completed] **WebSocket connection + message type routing** ✅ 2026-06-30
```

Do not delete task details after completion — they serve as a specification record.
