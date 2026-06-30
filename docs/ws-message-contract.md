# WebSocket Message Contract

**Status:** Proposed for Dev 2 sign-off · **Owner:** Dev 4 · **Last updated:** 2026-06-30

This document is the authoritative record of the **live WebSocket wire protocol** for HIE — every
message the backend actually sends and accepts on `/ws/{session_id}`, with concrete examples.

## Source of truth

There are two layers, and they are **not yet identical**:

| Layer | Artifact | Role |
|-------|----------|------|
| **Type contract** | [`packages/shared/types/ws.ts`](../packages/shared/types/ws.ts) — **frozen** (§16) | The TypeScript discriminated union. Changing it requires a **4-dev-reviewed PR**. |
| **Wire protocol** | *this document* | What the running backend emits/accepts **today**, including messages and shapes not yet in `ws.ts`. |

Where the two diverge, this doc records the divergence in [Contract reconciliation](#contract-reconciliation--gaps-vs-frozen-wsts)
and proposes the resolution. **This doc does not edit `ws.ts`** — it is the input to the future contract PR.

> **Envelope convention.** The typed messages use a nested envelope: `{ "type": <T>, "payload": <P> }`.
> Several live control messages are **flat** (`{ "type": <T> }` with no payload, or a bare `{ "error": ... }`).
> Flatness is called out explicitly below — it is a documented gap, not a typo.

---

## Inbound (client → server)

Routed in [`apps/api/app/core/websocket.py`](../apps/api/app/core/websocket.py) → `websocket_endpoint`.

| `type` | Shape | In `ws.ts`? | Source |
|--------|-------|-------------|--------|
| `attention_signal` | nested `{type, payload:{session_id, quiz_accuracy, teachback_score, behavioral_score, head_pose_score, blink_rate}}` | ✅ `AttentionSignalMessage` (the only `ClientMessage`) | `websocket.py:150` → `_handle_attention_signal` |
| `session_start` | **flat** `{type:"session_start"}` | ❌ not in `ClientMessage` | `websocket.py:153` → `_handle_session_start` |
| `ping` | **flat** `{type:"ping"}` | ❌ not in `ClientMessage` | `websocket.py:159` |
| 9 flow events (see below) | **flat** `{type:"<event>"}` | ❌ none in `ClientMessage` | `websocket.py:156` → `_handle_tutor_event` |

The **9 flow events** (`_TUTOR_CLIENT_EVENTS`) are tutor-FSM lifecycle triggers the client may drive:
`segment_complete`, `checkin_complete`, `low_checkin_score`, `quiz_trigger`, `quiz_complete`,
`quiz_failed`, `teachback_complete`, `teachback_failed`, `lesson_complete`.
(Server/engine-only events — `distraction_detected`, `fatigue_detected`, `session_reset` — are **not**
client-drivable and are rejected by the service layer.)

### Examples

**`attention_signal`** — batched engagement signals (every N seconds). `quiz_accuracy` / `teachback_score`
may be `null` when not available this window.
```json
{
  "type": "attention_signal",
  "payload": {
    "session_id": "f1c2…uuid",
    "quiz_accuracy": 0.82,
    "teachback_score": null,
    "behavioral_score": 0.7,
    "head_pose_score": 0.9,
    "blink_rate": 0.3
  }
}
```
> The backend parser also tolerates a flat (un-enveloped) signal, but the **nested envelope above is the
> contract** — clients should always send the `payload`-wrapped form.

**`session_start`** — begin the session (drives IDLE → TEACHING).
```json
{ "type": "session_start" }
```

**`ping`** — keepalive; server replies with `pong`.
```json
{ "type": "ping" }
```

**Flow event** (representative — all 9 share this flat shape):
```json
{ "type": "quiz_complete" }
```

---

## Outbound (server → client)

| `type` | Shape | In `ws.ts`? | Source |
|--------|-------|-------------|--------|
| `lesson_ready` | `{type, payload:{session_id, lesson_id, lesson}}` | ⚠️ typed payload is `{lesson_id, lesson}` — runtime adds `session_id` | published at `workers/jobs/content_pipeline.py:94`; relayed to the socket by the subscriber at `core/pubsub.py:81` → `manager.send` |
| `attention_ack` | `{type, payload:{session_id, ces}}` | ✅ exact match | `websocket.py:276` |
| `tutor_intervene` | `{type, payload:{session_id, type, message}}` | ✅ matches (`action?` optional, currently omitted) | `service.py:252` |
| `state_change` | `{type, payload:{session_id, from_state, to_state}}` | ✅ type matches | `websocket.py:77` |
| `pong` | **flat** `{type:"pong"}` (no payload) | ❌ not in `ServerMessage` | `websocket.py:160` |
| `error` | **flat** `{"error":"<msg>"}` (no `type`) | ⚠️ typed as `{type:"error", payload:{code, message}}` — runtime is flat | `websocket.py:145`, `:164` |

**Defined in `ws.ts` but not emitted by Dev-4 paths** (reserved for other owners):
`generation_progress` (Dev 1 — pipeline node progress) and `ces_update` (Dev 3 — periodic CES push).
They are members of the frozen `ServerMessage` union, so a discriminated-union `switch` must handle them
for exhaustiveness, **but no path emits them on the wire as of this writing** — Dev 2 should handle them
defensively (no-op) and must not depend on receiving them. Payload details are owned by those devs.

### Examples

**`lesson_ready`** — lesson generation finished; full package delivered. Runtime payload carries
`session_id` **in addition to** the typed `lesson_id` + `lesson`.
```json
{
  "type": "lesson_ready",
  "payload": {
    "session_id": "f1c2…uuid",
    "lesson_id": "lsn_…",
    "lesson": { "…": "full LessonPackage (see lesson_package.schema.json)" }
  }
}
```

**`attention_ack`** — server acknowledges an `attention_signal` and returns the computed CES.
```json
{ "type": "attention_ack", "payload": { "session_id": "f1c2…uuid", "ces": 0.64 } }
```

**`tutor_intervene`** — a triggered intervention delivers the pre-generated message. `type` is one of
`distraction | confusion | fatigue`. **Today only `distraction` is emitted** — the only intervention
trigger currently wired is `distraction_detected` (`service.py:237`), which defaults `type` to
`"distraction"` (`service.py:255`); `confusion` / `fatigue` are valid per the type but not yet produced
by any path. The optional `action` field is **not currently emitted**.
```json
{
  "type": "tutor_intervene",
  "payload": {
    "session_id": "f1c2…uuid",
    "type": "distraction",
    "message": "Let's refocus — look back at the diagram on this slide."
  }
}
```

**`state_change`** — FSM state transition. **As of this writing the only emitter on a Dev-4 path is the
reconnect sync** (`websocket.py:77`): on a WebSocket reconnect the server resends the *current* state
with `from_state == to_state` — a sync, not a transition. Real `from != to` transition frames are **not
yet pushed over WS** by any reviewed path; clients should treat `from == to` as "you are here". A
brand-new (first-ever) connection receives **no** `state_change` — see
[Connection lifecycle](#connection-lifecycle--first-connect-vs-reconnect).
```json
{
  "type": "state_change",
  "payload": { "session_id": "f1c2…uuid", "from_state": "QUIZZING", "to_state": "QUIZZING" }
}
```

**`pong`** — keepalive reply (flat, no payload).
```json
{ "type": "pong" }
```

**`error`** — emitted on invalid JSON or an unknown message `type`. **Flat shape — no `type`, no
`payload`.** This is the real wire form today:
```json
{ "error": "invalid JSON" }
```
```json
{ "error": "unknown message type 'foo'" }
```
A message with a **missing or empty** `type` is not special-cased: `type` defaults to `""`
(`websocket.py:148`) and falls through to the unknown-type branch, so the client sees
`{ "error": "unknown message type ''" }` (empty quotes). There is no dedicated "missing type" error.

> **Not every bad input yields an `error` frame** — see [Failure paths](#failure-paths--acknowledgement).
> A top-level JSON value that parses but is **not an object** (e.g. `42`, `true`, `[1,2]`) raises
> internally and **tears the connection down with no error frame**. Only a `JSONDecodeError` (malformed
> JSON) produces `{"error":"invalid JSON"}`.

---

## Delivery semantics

Behaviors that aren't visible from the message shapes but that Dev 2's client **must** handle.

### Session-scoped fan-out (multiple connections per session)
A `session_id` may have **multiple live connections** (e.g. desktop + mobile — `websocket.py:8`).
`manager.send` (`websocket.py:99`) delivers to **every** connection on that `session_id`. So
`attention_ack`, `tutor_intervene`, `lesson_ready`, and the reconnect `state_change` are **session
broadcasts, not replies to the sender**. If desktop sends an `attention_signal`, the resulting
`attention_ack` (and any `tutor_intervene`) also arrives on the mobile socket. **Dev 2 must tolerate
receiving frames it did not solicit and dedupe interventions across tabs/devices.**

### Fire-and-forget — no delivery guarantee, no replay
`manager.send` no-ops when a session has zero live connections (`websocket.py:101`). In particular, if
lesson generation finishes while the client is disconnected, the `lesson_ready` pub/sub frame is consumed
and **lost** — there is no replay on reconnect (reconnect restores `tutor_state` only, not `lesson_ready`).
The package is cached at `lesson_package:{session_id}` (`pubsub.py`), but that cache is **not** pushed to a
late-joining client. **A client that may have missed `lesson_ready` must fetch the lesson via the REST
API rather than wait for the push.**

### No ordering guarantee
`lesson_ready` arrives cross-process via Redis pub/sub (`pubsub.py:81`), while `attention_ack` /
`state_change` are emitted in-process. There is **no sequencing** between the two channels — `lesson_ready`
may arrive before or after any FSM/ack frame. Do not assume a global message order.

## Failure paths & acknowledgement

**`attention_ack` is best-effort, not guaranteed per signal.** An `attention_signal` produces an ack
**only** on the success path (`websocket.py:274`). It produces **no response of any kind** when:
- the signal is invalid — `_parse_signal` raises `ValueError` on a missing `session_id`, a missing
  required float, or a non-numeric value (`service.py:48–86`) → caught and swallowed (`websocket.py:281`);
- the tutor service is unavailable → `ImportError` → signal dropped (`websocket.py:278`);
- any other processing exception → caught and logged (`websocket.py:281`).

In all three cases the socket stays open but the client gets **silence** — no `attention_ack`, no `error`.
**Dev 2 must not block awaiting an ack after every signal.** (Note: scores are type-checked but **not**
range-validated — any finite float is accepted; there is no out-of-range rejection.)

## Connection lifecycle — first connect vs reconnect

- **First connection** (no `tutor_state` in Redis): the server initialises a fresh session and sends
  **nothing** — no `state_change`. The client should assume the session starts in `IDLE`.
- **Reconnect** (a live `tutor_state` exists): the server sends the `state_change` sync (`from == to`)
  carrying the restored state, and does **not** reset the session.
- **Degrade:** if the Redis read fails during connect (`websocket.py:193`), a real reconnect is treated as
  a fresh session — no sync is sent and the live state may be re-initialised to `IDLE`. Dev 2 sees a
  reconnect with no sync; this is a known Redis-blip limitation, not a normal path.

---

## Contract reconciliation — gaps vs frozen `ws.ts`

These are the divergences between the live wire protocol (above) and the frozen type contract. Each
needs the **4-dev `ws.ts` PR** to resolve — that PR is gated on the sign-off below.

### (a) Inbound control messages absent from `ClientMessage`
`session_start`, `ping`, and the 9 flow events are accepted by the server but `ClientMessage` only
contains `AttentionSignalMessage`. A strict TS client cannot construct them.
**Proposed resolution:** add a `ControlMessage` union (`session_start`, `ping`, the 9 flow events as flat
`{type}` messages) and fold it into `ClientMessage`.

### (b) Outbound `pong` absent from `ServerMessage`
The server replies to `ping` with `{type:"pong"}`, but `pong` is not in `ServerMessage`.
**Proposed resolution:** add `PongMessage` (flat `{type:"pong"}`) to the control union / `ServerMessage`.

### (c) `error` shape mismatch (flat vs typed)
Runtime emits flat `{"error":"<msg>"}`; `ErrorMessage` is typed `{type:"error", payload:{code, message}}`.
A client narrowing on `type` will never match the real error frame.
**Proposed resolution (pick one in the contract PR):** either **align the runtime** to emit
`{type:"error", payload:{code, message}}` (a small `websocket.py` change), **or** relax `ErrorMessage`
to the flat `{error}` form. Aligning the runtime is preferred (keeps the discriminated union clean).

### (d) `lesson_ready` carries an extra `session_id`
Runtime payload is `{session_id, lesson_id, lesson}`; the typed payload is `{lesson_id, lesson}`.
**Proposed resolution:** add `session_id` to `LessonReadyMessage`'s payload (additive, non-breaking for
clients that ignore it).

### (e) `state_change` reused as a reconnect sync
On reconnect the server sends `state_change` with `from_state == to_state`. The type is correct; the
*usage* is a convention worth pinning so Dev 2's client doesn't treat it as a real transition.
**Proposed resolution:** document the `from == to` convention in the `ws.ts` doc comment (no shape change).

### Code-cleanup flags (not contract changes — separate Dev-4 PRs)
- `apps/api/app/core/websocket.py` module docstring (lines ~18, ~134) advertises an outbound
  **`intervention`** type that does not exist — the real type is `tutor_intervene`. A reviewer reading the
  source header would integrate against a phantom type. Correct the docstring.
- The reconnect-sync code comments / `_restore_or_init_session` docstring refer to a **`state_sync`** name
  that is not a wire type (the frame sent is `state_change`). Rename for clarity to avoid confusion.

---

## Sign-off

| Role | Name | Status |
|------|------|--------|
| Author | Dev 4 | ✅ submitted |
| Frontend WS client | **Dev 2** | ⏳ pending sign-off |

Per PRD §16, the WebSocket contract is frozen: **no breaking WS changes land after Dev 2 sign-off.**
The reconciliation items above are the agreed delta to be applied in a single follow-up 4-dev `ws.ts` PR;
anything beyond them requires a fresh contract review.
