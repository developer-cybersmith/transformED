---
baseline_commit: "28c73ca073cca72ebe448b49c7520afadaa45270"
---

# Story BR-1: `generation_progress` Redis Pub/Sub → WebSocket Forwarding

**Status:** in-progress
**Sprint:** Bug Resolution — Feature Sprint 2 (`docs/dev4-tracker.md`)
**Branch:** `dev4/master-bug-resolution-br-1-caption-cue-delivery` (off `dev4/master-bug-resolution`)

---

## Story

As Dev 1 (pipeline owner, future consumer of this transport),
I want a Redis pub/sub → WebSocket forwarding path for `generation_progress` messages, mirroring the
already-hardened `lesson_ready:{lesson_id}` pattern Dev 4 built in `core/pubsub.py`,
so that any pipeline node can publish incremental progress and have it delivered live to a connected
client — instead of `GenerationProgressMessage` sitting declared-but-dead in the frozen `ws.ts` union
(W-D13), with zero path anywhere in `apps/api` ever emitting it.

---

## Context — how this story's scope was decided (2026-08-29)

The originating tracker task ("WebSocket: progressive caption-cue delivery for live narration
playback") does not describe anything that exists in this codebase:

- Captions (`CaptionOverlay.tsx`, closed as **D90**, `docs/LESSON-DELIVERY-TRACKER.md`) are **100%
  client-side**, computed from the local `<audio>` element's `audioPositionMs`/`audioDurationMs` via a
  character-proportional line-timing estimate. There is no WebSocket involvement in caption delivery
  anywhere in the code, and none is needed — the client already has playback position with zero latency.
- "Human-recorded narration" (the BR-2 task's wording) does not correspond to anything in the TTS
  pipeline either — the locked stack (`CLAUDE.md`) is Sarvam Bulbul v2 → Azure TTS → Browser Speech,
  synthesis only. Confirmed with the user (2026-08-29): this phrase means real *synthesized* narration
  audio with genuinely variable per-segment duration (already true today — segments run 1,351–4,069
  chars, per Story 3-42/3-45), not an undocumented pivot to actual human voice recording.

What the codebase DOES already document as a real, still-open gap: `GenerationProgressMessage`
(`{lesson_id, node, progress, message}`) has existed in the frozen `packages/shared/types/ws.ts` union
since Sprint 0, is explicitly called out as Dev-1-owned in four places (`docs/ws-message-contract.md`,
`docs/stories/4-10-ws-message-types-final.md`, `docs/stories/1-8-upload-real-api.md`,
`docs/reports/frontend-wiring-audit-2026-07-30.md`'s **W-D13**), and **no pipeline node has ever
published to it**. The frontend (`useLessonSocket.ts`) already handles it defensively as a no-op,
waiting for a real emitter.

Confirmed with the user (2026-08-29): BR-1's real, ownership-respecting scope is the **transport half**
of closing W-D13 — the Redis pub/sub → WebSocket forwarding layer, which is Dev 4's `core/pubsub.py`
domain — not Dev 1's pipeline-node instrumentation (a separate, future story, out of scope here). Since
`GenerationProgressMessage` already exists in `ws.ts`, **no 4-dev PR is needed** for this story.

---

## Acceptance Criteria

- **AC1:** A `generation_progress:*` Redis pub/sub subscriber runs as a background `asyncio.Task`,
  started at FastAPI lifespan startup (`start_generation_progress_listener`) and cancelled cleanly at
  shutdown — mirrors `start_lesson_ready_listener`'s existing lifecycle exactly.
- **AC2:** On a published `pmessage` on channel `generation_progress:{lesson_id}`, the subscriber
  resolves every session currently waiting on that lesson (reusing `_sessions_awaiting()` unchanged —
  no second, divergent implementation) and forwards the decoded JSON **verbatim** to each via
  `manager.send(session_id, message)`. No new caching side effect (unlike `lesson_ready`, this message
  type does not need a package cache).
- **AC3:** Malformed JSON on the channel is logged and skipped — the listener never crashes and never
  calls `manager.send`.
- **AC4:** Zero waiting sessions is logged as informational (matches `lesson_ready`'s
  "0 sessions waiting — nothing to push" framing), never as an error.
- **AC5:** A subscriber crash triggers the identical exponential back-off reconnect
  (`wait = min(2**attempt, 30)`); `asyncio.CancelledError` propagates cleanly on shutdown with no
  restart attempt.
- **AC6:** The listener opens its **own** dedicated `Redis.from_url()` connection, independent of both
  the shared pool and the `lesson_ready` subscriber's own connection (DECISION 1's stated reason still
  applies: pub/sub blocks the connection it's issued on).
- **AC7:** No edit to `packages/shared/types/ws.ts` — `GenerationProgressMessage` already exists in the
  frozen union; this story only wires a path that emits onto it.
- **AC8:** `docs/dev4-tracker.md`'s BR-1 entry and `scripts/check_dev4_progress.py`'s
  `br1_caption_cue_delivery` check reflect the real, shipped scope (transport only).

---

## Tasks / Subtasks

- [ ] 1.1 Extract a generic `_run_pubsub_forwarder(manager, channel_prefix, log_label, on_message=None)`
      helper in `core/pubsub.py` from `_run_lesson_subscriber`'s existing loop body — **byte-identical
      behavior for the `lesson_ready` path**, `on_message` is the hook `lesson_ready` uses for its
      package-cache side effect. (Decision: extract rather than duplicate ~80 lines of hardened,
      defect-scarred reconnect/decode logic — see Dev Notes.)
- [ ] 1.2 `_run_lesson_subscriber` becomes a thin wrapper calling the generic helper with
      `channel_prefix="lesson_ready"` and the existing package-cache `on_message` hook.
- [ ] 1.3 Add `_run_generation_progress_subscriber(manager)` = the generic helper with
      `channel_prefix="generation_progress"`, no hook.
- [ ] 1.4 Add `start_generation_progress_listener(manager)`, mirroring
      `start_lesson_ready_listener` exactly (named task `generation_progress_subscriber`).
- [ ] 1.5 Wire `main.py` lifespan: start the new listener alongside the existing one, cancel both on
      shutdown.
- [ ] 1.6 New test file `test_generation_progress_pubsub.py`, mirroring
      `test_lesson_ready_pubsub.py`'s subscriber tests (forwards pmessage, malformed JSON, zero-sessions
      log, own dedicated connection) — **mocks `app.core.db.get_supabase` (or `_sessions_awaiting`)
      directly**, not just `get_settings`, specifically to not inherit the import-order fragility
      registered as **D136** in this same pass.
- [ ] 1.7 Regression run: full existing `test_lesson_ready_pubsub.py` +
      `test_lesson_ready_integration.py` green, unchanged behavior, after the extraction in 1.1.
- [ ] 1.8 Update `docs/dev4-tracker.md` BR-1 entry to `[Completed]` and re-run
      `scripts/check_dev4_progress.py`.

---

## Dev Notes

### Why extract, not duplicate

`_run_lesson_subscriber` is a defect-scarred, hardened function (D23, D34 both trace through it) with
its own passing (in full-suite context) test coverage. Two options were considered:

1. **Duplicate** the ~80-line subscribe/decode/resolve/forward/backoff loop as a second, independent
   function for `generation_progress`. Lower risk of touching working code, but repeats a nontrivial
   amount of hardened logic — exactly the kind of copy this repo's binding rule 6 warns drifts silently
   (a fix to one loop's edge case, e.g. a decode guard, would not automatically apply to the other).
2. **Extract** a shared `_run_pubsub_forwarder` helper, parameterized by channel prefix and an optional
   post-forward hook for `lesson_ready`'s package-cache side effect. Chosen: the two loops are
   identical except for (a) the channel prefix and (b) whether a caching hook runs after forwarding.
   The extraction preserves `_run_lesson_subscriber`'s exact behavior (same log lines, same backoff, same
   `_sessions_awaiting` call, same exception handling) — verified by re-running its full existing test
   suite unmodified after the refactor (AC/Task 1.7).

### Channel key: lesson, not session (same reasoning as `lesson_ready`, D23)

`generation_progress`'s payload already carries `lesson_id` (per `ws.ts`), and the pipeline node that
will eventually publish it knows the lesson, not any particular viewing session — same reasoning D23
already established for `lesson_ready`. Channel: `generation_progress:{lesson_id}`.

### Files to change

| File | Change |
|------|--------|
| `apps/api/app/core/pubsub.py` | Extract `_run_pubsub_forwarder`; add `_run_generation_progress_subscriber`, `start_generation_progress_listener` |
| `apps/api/app/main.py` | Start/cancel the new listener in `lifespan()` |
| `apps/api/tests/test_generation_progress_pubsub.py` | New — subscriber behavior tests |
| `docs/dev4-tracker.md` | BR-1 entry → `[Completed]` |

### Out of scope (flagged, not built here)

- **Dev 1's actual publish side** — no pipeline node calls `redis.publish("generation_progress:...", ...)`
  yet. This story only builds the receiving/forwarding half; a future Dev-1 story wires the emit side
  once a node is chosen to report progress from.
- **D136** (`docs/DEFECT-REGISTER.md`) — the pre-existing `lesson_ready` subscriber test import-order
  fragility found while prototyping this story. Not this story's bug to fix; this story's own new tests
  are written to not inherit it (see Task 1.6).

---

## Scale & Load (`docs/SCALE-CONTRACT.md`'s six questions)

1. **Unit of work and its range.** One `generation_progress` message forwarded to N sessions currently
   waiting on that lesson. `N`: min 0 (nobody waiting — a normal outcome, AC4), typical 1 (one student
   watching their own lesson generate), max = however many concurrent sessions happen to be open against
   the same `lesson_id` — naturally small (one student generates their own lesson; this is not a
   fan-out-to-many-viewers product), not artificially capped, same shape `lesson_ready` already accepts
   unchanged.
2. **Fixed budgets vs. variable input.** None introduced. Malformed JSON is explicitly rejected (AC3),
   never silently truncated — same explicit-reject behavior `lesson_ready` already has. No new message
   size cap is added or needed; the publisher's payload shape is fixed by `ws.ts`'s
   `GenerationProgressMessage` (`{lesson_id, node, progress, message}`), a small, bounded record.
3. **Scope of limits.** Per-process: the listener task lives once per FastAPI worker process. Under
   multiple API replicas (per the India-region migration, `ADR-001`), Redis pub/sub fans the same
   message out to every replica's subscriber, but `manager.send()` only has an effect for a session
   connected to *that* replica's in-memory `ConnectionManager` — a session is only ever connected to one
   replica, so the practical per-session delivery count is still 1, not N. This is an inherited property
   of the exact same `lesson_ready` pattern being mirrored, not a new risk BR-1 introduces.
4. **Unbounded reads/writes.** None new. `_sessions_awaiting()` is reused unchanged — already indexed
   (`sessions.lesson_id`, per its own docstring) and already the subject of D34's fix.
5. **Inherited caps re-derived.** N/A — new component, no inherited cap carried forward.
6. **Check-then-act under concurrency.** The `_sessions_awaiting()` → `manager.send()` sequence has the
   same benign race `lesson_ready` already has and already handles: a session can disconnect between the
   Supabase read and the send; `manager.send()`'s own contract already tolerates a missing/dead
   connection without raising. No new concurrency risk introduced by adding a second channel prefix to
   the same forwarding mechanism.

---

## Review findings

*(filled in after the 6-layer review, before merge)*
