# Epic 4: Tutor Agent + CES + Realtime

| Field | Value |
|---|---|
| Epic ID | E-04 |
| Status | Planned |
| Owner | Dev 4 |
| Target Sprints | Sprint 1–3 (Weeks 2–7) |
| Priority | P1 — WebSocket server required by Epics 2 and 3 from Sprint 1 |

---

## Problem Statement

TransformED's engagement model depends on the platform *reacting* to a student in real time — firing an intervention when attention drops, checking in when confusion signals accumulate, and never interrupting a teach-back. Without a WebSocket layer, a stateful tutor machine, and a continuously computed CES score, the lesson is just a podcast. This epic builds the real-time nervous system of the platform.

---

## Goal / Success Metric

> **In a live test session, the tutor fires the correct intervention type within 5 seconds of a qualifying signal, CES recomputes every 5 seconds, and tutor state survives a full page refresh.**

Secondary metrics:
- JWT validation adds < 5ms latency to WebSocket handshake
- CES computation completes in < 5ms (in-process, no DB call)
- Redis write for attention signal is non-blocking (fire-and-forget from player)

---

## User Stories

- As a **student**, if I look away from the screen for too long, the lesson gently prompts me to re-engage — the lesson does not pause on its own.
- As a **student**, if I'm working through a teach-back, the tutor never interrupts me.
- As a **student**, if the browser tab is refreshed mid-lesson, my lesson state and tutor state are restored exactly where I left off.
- As a **developer**, I can tune the CES formula weights without a code deploy.
- As a **developer**, I can observe the tutor state and CES value for any active session from the admin panel.
- As a **platform operator**, no GPT call is made at intervention time — all messages are pre-baked at lesson build time.

---

## WebSocket Infrastructure

### Endpoint
`/ws/{session_id}` — accepts connection after JWT validation in handshake headers.

### JWT Middleware
- Decode via `PyJWT` locally using `SUPABASE_JWT_SECRET` env var
- NEVER make a remote call to Supabase Auth during WebSocket handshake
- Reject connection with `4001` close code on invalid/expired token
- Attach `user_id` and `session_id` to connection context

### ConnectionManager (`backend/ws/connection_manager.py`)
- Maintains `Dict[str, WebSocket]` of active connections keyed by `session_id`
- `broadcast(session_id, message)` — sends JSON message to connected client
- `disconnect(session_id)` — removes from map, cleans up Redis cooldown keys
- Thread-safe via `asyncio.Lock`

### Message Types (server → client)

| Type | Payload | Trigger |
|---|---|---|
| `intervention` | `{ type: "A"|"B"|"C", message: str, segment_id: str }` | Guard rule fires |
| `ces_update` | `{ ces: float, timestamp: ms }` | Every 5s during TEACHING |
| `state_change` | `{ new_state: TutorState }` | Any FSM transition |
| `session_end` | `{ report_url: str }` | TEACH_BACK → SESSION_END |

### Message Types (client → server)

| Type | Payload | Description |
|---|---|---|
| `attention_signal` | `{ head_pose: float, blink_rate: float, timestamp: ms }` | From MediaPipe, every 5s |
| `quiz_complete` | `{ segment_id: str, accuracy: float }` | From QuizModal on submit |
| `teachback_start` | `{ segment_id: str }` | TeachBackModal opens |
| `teachback_end` | `{ segment_id: str, score: float }` | TeachBackModal submits |
| `lesson_end` | `{}` | AudioTimeline reaches end |

---

## Tutor State Machine

7 states, 14 transitions.

```
IDLE ──────────────────────────────────────────────────────►  (on lesson_start)
  └─► TEACHING ──────────────────────────────────────────────►  (nominal state)
        ├─► INTERVENING    (on distraction signal + guard rules)
        │     └─► TEACHING (on intervention_acknowledged OR timeout 30s)
        ├─► CHECKING_IN    (on confusion signal + guard rules)
        │     └─► TEACHING (on check_in_dismissed)
        ├─► QUIZZING       (on segment_boundary event)
        │     └─► TEACH_BACK (on quiz_complete)
        │           └─► TEACHING (on teachback_end, if not last segment)
        │           └─► SESSION_END (on teachback_end, if last segment)
        └─► SESSION_END    (on lesson_end without pending quiz)
```

### Guard Rules (all must pass for intervention to fire)

| # | Rule | Detail |
|---|---|---|
| G1 | CES only computed in TEACHING | No CES update emitted in any other state |
| G2 | 2-minute cooldown between interventions | Redis key `cooldown:{session_id}` TTL 120s |
| G3 | Max 3 distraction interventions per session | Redis key `distraction_count:{session_id}` |
| G4 | Fatigue intervention fires at most once per session | Redis key `fatigue_fired:{session_id}` |
| G5 | NEVER interrupt TEACH_BACK state | Hard block regardless of signals |

### Intervention Types

| Type | Trigger Condition | Pre-generated Message Source |
|---|---|---|
| A — Distraction | `head_pose_score < 0.4` for 2 consecutive windows | `intervention_messages` node (Epic 1) |
| B — Confusion | CES drops > 0.15 in one 30s window | `intervention_messages` node (Epic 1) |
| C — Fatigue | Session duration > 40 min AND blink_rate elevated | `intervention_messages` node (Epic 1) |

**Critical:** Intervention message strings are selected from the pre-generated pool stored in `lesson_package.json`. No GPT call is made at intervention time.

---

## CES Computation

### Signal Buffer (Redis)
```
Redis key:  session:{id}:signals
Structure:  LPUSH + LTRIM to keep last 6 entries (= 30-second window at 5s cadence)
TTL:        24 hours (session may pause and resume)
```

Each entry: `{ head_pose: float, blink_rate: float, timestamp: ms }`

### Computation
- Runs in-process in the WebSocket message handler (no separate worker)
- Reads last 6 signals from Redis (`LRANGE session:{id}:signals 0 5`)
- Applies CES formula (weights from env vars, formula defined in Epic 3)
- Target latency: < 5ms
- Result emitted as `ces_update` message to client and written to `session_events` table (async, non-blocking)

---

## Redis Key Map

| Key | TTL | Purpose |
|---|---|---|
| `session:{id}:signals` | 24h | Rolling attention signal buffer |
| `tutor_state:{id}` | 24h | Current FSM state (enables page refresh restore) |
| `cooldown:{id}` | 120s (self-expiring) | Intervention cooldown gate |
| `distraction_count:{id}` | 24h | Running count of Type A interventions |
| `fatigue_fired:{id}` | 24h | Boolean flag for fatigue gate |

---

## Technical Scope

| Layer | Files / Modules |
|---|---|
| WebSocket endpoint | `backend/ws/router.py` |
| ConnectionManager | `backend/ws/connection_manager.py` |
| JWT middleware | `backend/ws/auth.py` |
| Tutor FSM | `backend/tutor/state_machine.py` |
| Guard rules | `backend/tutor/guards.py` |
| CES computation | `backend/tutor/ces_compute.py` |
| Redis signal buffer | `backend/tutor/signal_buffer.py` |
| Message routing | `backend/ws/message_router.py` |
| DB writes | `backend/tutor/session_events.py` (async, non-blocking) |
| DB migrations | `supabase/migrations/` — `session_events`, `tutor_state_log` |
| WS client | `lib/ws/lessonSocket.ts` (Epic 2 frontend) |

---

## Out of Scope (Phase 2)

- RAG tutor Q&A (student can ask questions; retrieval chain over lesson embeddings)
- Multi-student session coordination
- Adaptive pacing (slow down lesson narration based on CES)
- Voice-based interventions
- PostgreSQL-backed tutor state persistence (Redis is sufficient for Phase 1)

---

## Dependencies

| Dependency | Status |
|---|---|
| Sprint 0 infra (Redis, Railway) | Done |
| Supabase JWT secret provisioned as env var | Done |
| Epic 1: `intervention_messages` node produces pre-generated strings | Required before full tutor integration |
| Epic 2: WebSocket client + AttentionMonitor sending signals | Parallel — interface contract agreed Sprint 1 |
| Epic 3: CES formula weights and `teachback_score` signal | Interface contract agreed Sprint 1 |

---

## Definition of Done

- [ ] `/ws/{session_id}` accepts authenticated connections; rejects invalid JWT with code 4001
- [ ] JWT decoded locally with PyJWT — no remote call (verified by unit test with no network)
- [ ] All 7 tutor states and 14 transitions implemented and unit-tested
- [ ] All 5 guard rules enforced (test: fire intervention, verify cooldown blocks second within 2min)
- [ ] Intervention type A, B, C each fire in a scripted test scenario
- [ ] Intervention is NEVER fired while in TEACH_BACK state (dedicated test case)
- [ ] CES computes in < 5ms with 6-entry Redis buffer (benchmarked)
- [ ] `tutor_state:{id}` in Redis persists through simulated page refresh (integration test)
- [ ] CES formula weights changed via env var without redeploy (smoke test)
- [ ] Redis writes are non-blocking — WebSocket handler does not await signal buffer write
- [ ] `ces_update` messages emitted to client at 5-second intervals during TEACHING
- [ ] All intervention messages sourced from `lesson_package.json` — no inline strings, no GPT calls

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Railway WebSocket connection drops under load | Medium | High | Reconnect logic in `lessonSocket.ts`; sticky sessions on Railway |
| Redis eviction clears tutor state mid-session | Low | High | `maxmemory-policy noeviction` for session keys namespace |
| Guard rule G5 (no TEACH_BACK interrupt) has edge case on rapid state changes | Medium | Medium | Explicit state check at top of `fire_intervention()` function |
| CES Redis read adds latency under high concurrency | Low | Medium | Pipeline LRANGE inside async handler; benchmark at 50 concurrent sessions |
| Pre-generated messages feel repetitive across sessions | Medium | Low | Generate 3 variants per type per lesson; rotate via index |
