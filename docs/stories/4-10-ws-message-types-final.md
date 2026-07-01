---
baseline_commit: "7f44239"
---

# Story 4-10: WebSocket Message Contract Finalised & Published

**Status:** done

---

## Story

As Dev 4,
I want a single authoritative `docs/ws-message-contract.md` documenting every inbound and outbound
WebSocket message shape actually in use — with example payloads — and a clear reconciliation of where
the live wire protocol has drifted from the frozen `packages/shared/types/ws.ts`,
so that Dev 2 (frontend WS client) can sign off on the contract and the `ws_message_types_final`
Sprint 2 task is closed with no breaking changes after this point.

---

## Context

`ws.ts` (frozen Week 1, §16) is the *type* contract, but the running backend now emits and accepts
several messages that are **not** in the `ClientMessage` / `ServerMessage` unions, plus a couple whose
runtime shape differs from the typed one. This story does NOT edit the frozen `ws.ts` (that needs a
4-dev PR). It documents reality, names every gap, and proposes the reconciliation for Dev 2 sign-off.

### Verified inventory (read from source — cite these, do not invent shapes)

**Inbound (client → server)** — routed in `apps/api/app/core/websocket.py` `websocket_endpoint`:
| `type` | Shape (runtime) | In `ws.ts`? |
|--------|-----------------|-------------|
| `attention_signal` | `{type, payload:{session_id, quiz_accuracy, teachback_score, behavioral_score, head_pose_score, blink_rate}}` | ✅ `AttentionSignalMessage` (only ClientMessage member) |
| `session_start` | flat: `{type:"session_start"}` (handler reads only `type`) | ❌ not in `ClientMessage` |
| `ping` | flat: `{type:"ping"}` | ❌ not in `ClientMessage` |
| 9 flow events (`_TUTOR_CLIENT_EVENTS`): `segment_complete`, `checkin_complete`, `low_checkin_score`, `quiz_trigger`, `quiz_complete`, `quiz_failed`, `teachback_complete`, `teachback_failed`, `lesson_complete` | flat: `{type:"<event>"}` (only `type` read) | ❌ none in `ClientMessage` |

**Outbound (server → client):**
| `type` | Shape (runtime) | Source | In `ws.ts`? |
|--------|-----------------|--------|-------------|
| `lesson_ready` | `{type, payload:{session_id, lesson_id, lesson}}` | `workers/jobs/content_pipeline.py:94` via pub/sub | ⚠️ typed payload is `{lesson_id, lesson}` — runtime adds `session_id` |
| `attention_ack` | `{type, payload:{session_id, ces}}` | `websocket.py:276` | ✅ exact match |
| `tutor_intervene` | `{type, payload:{session_id, type, message}}` (no `action`) | `service.py:252` | ✅ matches (`action?` optional, omitted) |
| `state_change` | `{type, payload:{session_id, from_state, to_state}}` | `websocket.py:77` (reconnect sync uses `from==to`) | ✅ type matches; **reconnect-sync usage** (from==to) is a documented convention, not a transition |
| `pong` | flat: `{type:"pong"}` (no payload) | `websocket.py:160` | ❌ not in `ServerMessage` |
| error (bad JSON) | flat: `{"error":"invalid JSON"}` | `websocket.py:145` | ⚠️ `ErrorMessage` typed as `{type:"error", payload:{code, message}}` — runtime is flat `{error}` |
| error (unknown type) | flat: `{"error":"unknown message type '<x>'"}` | `websocket.py:164` | ⚠️ same mismatch as above |

**Typed but NOT emitted by Dev-4 paths (document as reserved / other-owner):**
`generation_progress`, `ces_update` (Dev 1 / Dev 3 may emit; note as defined-in-contract, not Dev-4-owned).

---

## Acceptance Criteria

- **AC 1:** `docs/ws-message-contract.md` exists and documents EVERY message in the verified inventory
  above — inbound and outbound — each with: `type`, direction, exact JSON shape, a concrete example
  payload, owner/source file, and trigger/semantics.
- **AC 2:** A dedicated **"Contract reconciliation — gaps vs frozen `ws.ts`"** section lists every
  divergence: (a) inbound control messages absent from `ClientMessage` (`session_start`, `ping`, 9 flow
  events); (b) outbound absent from `ServerMessage` (`pong`); (c) shape mismatches (`error` flat vs
  typed `{code,message}`; `lesson_ready` extra `session_id`); (d) the `state_change`-as-reconnect-sync
  convention. Each gap states the proposed resolution and that it requires the 4-dev `ws.ts` PR.
- **AC 3:** Document does NOT edit `packages/shared/types/ws.ts` (frozen — change requires a separate
  4-dev-reviewed PR). The doc is the proposal that precedes that PR.
- **AC 4:** Every shape and example matches the actual source (no invented fields). The `lesson_ready`
  payload shows the runtime `session_id` + `lesson_id` + `lesson`; `tutor_intervene` shows `type`/
  `message` with `action` noted optional-and-currently-omitted; `error` shows the real flat form AND the
  typed target form.
- **AC 5:** A short "Sign-off" section names Dev 2 as approver and records that no breaking WS changes
  land after sign-off (the §16 freeze intent).
- **AC 6:** The Quick Status Dashboard + the `ws_message_types_final` task block in
  `docs/dev4-websocket-tutor-tracker.md` are updated to Completed per the Sprint Tracker Auto-Update Rule.

---

## Tasks / Subtasks

- [ ] 1.1 Author `docs/ws-message-contract.md`: header (purpose, source-of-truth note, frozen-ws.ts link),
  Inbound table+examples, Outbound table+examples, Reconciliation section, Sign-off section.
- [ ] 1.2 Cross-check every shape against the cited source files (no drift).
- [ ] 1.3 Update tracker (`ws_message_types_final` → Completed; dashboard; header date) — orchestrator may
  do this at merge per the auto-update rule.

---

## Dev Notes

- This is documentation only — **no production code change, no new tests**. "Verification" = the
  adversarial review confirming each documented shape matches the cited source line.
- Markdown tables + fenced ```json example blocks. Keep it skimmable for Dev 2.
- Do not soften the mismatches — the `error` flat-vs-typed and `lesson_ready` extra-field gaps are the
  whole point; they tell Dev 2 exactly what the client must tolerate today and what the ws.ts PR will fix.
- Flag (do not fix here): the eventual `ws.ts` PR should add a `ControlMessage` union (ping/pong/
  session_start/flow events) and either align the runtime `error` to `{code,message}` or relax the type.

---

## Out of scope / flagged

- Editing `ws.ts` (separate 4-dev PR — this doc is its input).
- Aligning the runtime `error` emitter to the typed `{code,message}` shape (code change; propose, defer).
- `generation_progress` / `ces_update` payload details owned by Dev 1 / Dev 3.

---

## Review outcome (adversarial — Blind Hunter + Edge Case Hunter, 2026-06-30)

Both reviewers returned **FIX-FIRST** with the SAME headline: **no wrong shapes/types/fields** — every
payload Dev 2 codes against (`attention_signal`, `attention_ack`, `tutor_intervene`, `state_change`,
`lesson_ready`, flat `pong`/`error`) and all source line-cites are accurate. The gaps were **behavioral
semantics the doc omitted**, which Dev 2 must handle. All applied to the doc (documentation-only — no code
change):

**Applied:**
- **Session-scoped fan-out** — `manager.send` delivers to ALL connections for a `session_id`; acks /
  interventions are session broadcasts, not replies to the sender (multi-device dedupe burden on Dev 2).
- **`attention_ack` is best-effort** — invalid signal (`_parse_signal` ValueError), `ImportError`, or any
  exception → **silence** (no ack, no error). Client must not block on an ack. (Also: scores are not
  range-validated.)
- **First-connect is silent vs reconnect-sync** — a brand-new connection gets NO `state_change`; only a
  reconnect with a live `tutor_state` gets the `from==to` sync. Added a Connection-lifecycle section
  incl. the Redis-blip degrade-to-fresh-init path.
- **`state_change` framing** — clarified the only emitter on a Dev-4 path today is the reconnect sync;
  real `from!=to` transitions are not yet pushed over WS.
- **Fire-and-forget + no replay** — `lesson_ready` to a session with no live socket is dropped; cache is
  not pushed to a late joiner → fetch via REST. **No ordering guarantee** between pub/sub `lesson_ready`
  and in-process frames.
- **Non-object JSON** (`42`/`true`/`[…]`) tears the socket down with NO error frame; missing/empty `type`
  → `{"error":"unknown message type ''"}`.
- **`tutor_intervene` is distraction-only today**; `lesson_ready` relay cite corrected to `pubsub.py:81`.
- **Code-cleanup flags** added to reconciliation (separate Dev-4 PRs): stale `websocket.py` docstring
  advertising a phantom `intervention` type; `state_sync` naming in comments for a frame that is
  `state_change`.

**Flagged — NOT changed (out of scope):** the actual `ws.ts` edit (4-dev PR), aligning the runtime
`error` emitter to `{code,message}` (code change), and the two source-docstring fixes (separate PRs).
