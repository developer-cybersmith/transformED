---
baseline_commit: "1884f2b"
---

# Story 4-24: INTERVENING recovery — event path + timeout safety net

**Status:** done

---

## Story

As Dev 4,
I want the `INTERVENING` state to leave via a real client-driven `intervention_complete` event
**and** via an independent timeout safety net,
so that the first attention-driven intervention (arriving with L6/MediaPipe) cannot permanently
and silently disable CES monitoring for the rest of a student's lesson.

Registered as **D63** in `docs/DEFECT-REGISTER.md` (found in Dev 3's 2026-08-05 lesson-delivery
handoff, reverified live in code 2026-08-11 — unchanged). Discharges `docs/LESSON-DELIVERY-TRACKER.md`
L7's first exit criterion and its explicit ordering rule: **must land before Dev 2 ships L6.**

---

## Context (verified 2026-08-11, before writing this story)

- `route_from_intervening` (`graph.py:337-339`) leaves `INTERVENING` **only** on event
  `intervention_complete`. That event does not appear in `_CLIENT_DRIVABLE_EVENTS`
  (`service.py:197-209`), `_TUTOR_CLIENT_EVENTS` (`websocket.py:43-55`), or
  `apps/web/src/lib/ws/wireTypes.ts`'s `FlowEvent` union — and no code path dispatches it.
  There is no timeout anywhere in the file.
- CES monitoring is gated to `state_raw == "TEACHING"` (`service.py:328`), so a session stuck in
  `INTERVENING` never fires another intervention and the tutor goes silently inert for the rest of
  the lesson. Nothing logs this as a failure.
- **Established idiom already in this file for exactly this shape of problem** — a time-bounded
  state that must not depend solely on a client event arriving: the `QUIZZING` Q&A phase deadline.
  `quizzing_node` (`graph.py:220-238`) writes `session:{session_id}:quiz_deadline_at`;
  `_quiz_deadline_expired` (`service.py:165-180`) reads it; both `process_attention_signal`
  (`service.py:373-380`) and `advance_tutor_state` (`service.py:229-235`) check it and
  self-dispatch `quiz_complete` with a delete-before-dispatch double-fire guard. This story
  reproduces that exact pattern for `INTERVENING` rather than inventing new infrastructure
  (Redis keyspace notifications, a background sweeper, etc.) — binding rule 6 cuts both ways:
  copying an *already-reviewed, already-safe* pattern into a second site is not the same failure
  as copying an *unreviewed* one into eighteen.
- Attention frames keep arriving from the client during `INTERVENING` — nothing on the client
  stops MediaPipe or the WS heartbeat when an overlay is shown — so `process_attention_signal`
  is a live, recurring hook to evaluate the timeout against. The ultimate backstop if the client
  disconnects entirely and never reconnects is the existing 24h Redis TTL on `tutor_state:*`
  (`_STATE_TTL`, unchanged) — the same degradation every other session key already has, not a new
  gap introduced by this story.
- While in `intervening_node`/`teaching_node`/etc. for this change, also fixing: all 7 FSM node
  functions currently `return {**state, ...}` — the pattern CLAUDE.md bans repo-wide (found
  harmless today only because `TutorMachineState` declares no `operator.add` channel) — and
  `tests/unit/test_node_return_shape.py` scans only `app/modules/content/pipeline`, so this file
  is `FIXED-UNGUARDED` today. Two-line widen, per the handoff's own note; doing it now because this
  story already touches every node in the file.

---

## Acceptance Criteria

- **AC 1:** `intervention_complete` is a recognized client-drivable event end to end:
  `_CLIENT_DRIVABLE_EVENTS` (service.py), `_TUTOR_CLIENT_EVENTS` (websocket.py), and
  `wireTypes.ts`'s `FlowEvent` union all include it. A test dispatches it from `INTERVENING` and
  asserts the FSM returns to `TEACHING`.
- **AC 2:** `intervening_node` writes an `intervention_deadline_at` Redis key (TTL matching
  `_STATE_TTL`) using a new `settings.intervention_timeout_seconds` (default 45s, tunable per the
  existing `intervention_cooldown_seconds` pattern).
- **AC 3:** A new `_intervention_deadline_expired(session_id, redis)` helper (mirrors
  `_quiz_deadline_expired` exactly: fail-safe → `False` on any error) is checked in both
  `process_attention_signal` and `advance_tutor_state`, with the same delete-before-dispatch
  double-fire guard as the QUIZZING path, self-dispatching `intervention_complete` when expired.
  A test proves: session stuck in `INTERVENING` past the deadline + a signal arrives → FSM returns
  to `TEACHING` with **no client event required**.
- **AC 4:** A test proves the deadline does **not** fire early — a session still within the
  timeout window stays in `INTERVENING` on a subsequent signal.
- **AC 5:** Concurrent double-fire is guarded — two simultaneous expired-deadline checks for the
  same session dispatch `intervention_complete` at most once (mirrors the existing QUIZZING
  `redis.delete()` return-value guard; test simulates both call sites racing on the same key).
- **AC 6:** All 7 FSM node functions (`idle_node`, `teaching_node`, `intervening_node`,
  `checking_in_node`, `quizzing_node`, `teach_back_node`, `session_end_node`) return only the keys
  they own — no `{**state, ...}` spread, no equivalent evasion.
- **AC 7:** `tests/unit/test_node_return_shape.py`'s scan is widened to also cover
  `app/modules/tutor/state_machine` (not just `app/modules/content/pipeline`), and a test proves
  the widened guard actually scans files in the tutor path (not just that it exists).
- **AC 8:** D63 in `docs/DEFECT-REGISTER.md` is updated from OPEN to CLOSED, naming the real
  enforcement tests (not left as `*(to add)*`).
- **AC 9:** Full existing FSM/service/websocket test suites stay green — no regression to the 14
  transitions, 5 guard rules, or CES trigger logic.

**Explicitly out of scope:** the actual dismiss-button UI (Dev 2's `apps/web` — this story only
makes the event *reachable*, matching the D60 pattern of "Dev 4 builds the endpoint, Dev 2 wires
the frontend"). Flagged as an ask to Dev 2 in Dev Notes, not built here.

---

## Scale & Load

1. **Unit of work:** one `INTERVENING` overlay per triggered intervention, at most 3 distraction +
   1 fatigue + N confusion (teach-back-failure-driven, unbounded by count today — pre-existing,
   not introduced here) per session. Timeout default 45s is a placeholder pending Dev 2 UX
   confirmation of actual overlay dismiss time; tunable via env var, not hardcoded.
2. **Fixed budget vs variable input:** `intervention_timeout_seconds` is fixed; the variable is how
   long a client takes to dismiss. Past the timeout: explicit, surfaced self-heal (logged INFO,
   FSM transitions, CES monitoring resumes) — never a silent hang. This is the entire point of the
   story.
3. **Scope:** per session — `session:{session_id}:intervention_deadline_at` matches every other
   Redis key in this file (session-scoped, not per-instance, not per-deployment).
4. **Unbounded:** none introduced. The deadline key has the same 24h TTL as its siblings; no new
   list/history grows.
5. **Inherited caps:** N/A — no existing cap is being reused or resized here; `intervention_timeout_seconds`
   is a new, independently-tunable value, deliberately not reusing `intervention_cooldown_seconds`
   (cooldown governs time *between* interventions; timeout governs time *within* one).
6. **Concurrency:** two attention-signal windows (or one signal + one client event) racing on the
   same expired deadline must not double-dispatch `intervention_complete` — AC 5's
   delete-before-dispatch guard, identical in shape to the QUIZZING path already carrying this
   property in production. Two tabs on one `session_id` is a pre-existing, out-of-scope condition
   (flagged in the Dev 4 handoff, not solved by this story).

---

## Tasks / Subtasks

- [x] 1.1 `config.py`: add `intervention_timeout_seconds` (default 45, same style as
      `intervention_cooldown_seconds`).
- [x] 1.2 `service.py`: add `intervention_complete` to `_CLIENT_DRIVABLE_EVENTS`.
- [x] 1.3 `websocket.py`: add `intervention_complete` to `_TUTOR_CLIENT_EVENTS`.
- [x] 1.4 `wireTypes.ts`: add `'intervention_complete'` to the `FlowEvent` union.
- [x] 1.5 `graph.py` `intervening_node`: write `intervention_deadline_at`; drop `{**state, ...}`.
- [x] 1.6 `graph.py`: drop `{**state, ...}` from the remaining 6 nodes (return owned keys only).
- [x] 1.7 `service.py`: add `_intervention_deadline_expired` (mirrors `_quiz_deadline_expired`).
- [x] 1.8 `service.py` `process_attention_signal`: check + self-dispatch, delete-before-dispatch guard.
- [x] 1.9 `service.py` `advance_tutor_state`: same check before processing the client's own event.
- [x] 1.10 `tests/unit/test_node_return_shape.py`: widen scan to `tutor/state_machine`; add a test
      that the widened scan actually walks files there.
- [x] 1.11 `test_tutor_graph.py` / `test_tutor_service.py`: AC 1, 3, 4, 5 tests.
- [x] 1.12 Update D63 in `docs/DEFECT-REGISTER.md` to CLOSED with real test names.
- [x] 1.13 Update `docs/dev4-tracker.md` dashboard + add the task entry.
- [x] 1.14 Full regression run — 176/176 green in affected suites; only pre-existing,
      unrelated environment gaps (`python-multipart`, `fpdf`) fail elsewhere.

---

## Dev Notes

### What we owe Dev 2 (flagged, not built here)

The dismiss button / overlay UI must send `{"type": "intervention_complete"}` when the student
dismisses an intervention. Until that lands, every real intervention will rely on the timeout path
(AC 3) rather than the event path (AC 1) — which is exactly why both exist; the story does not
gate on Dev 2's frontend work.

### Why the timeout lives in `process_attention_signal`, not in `route_from_intervening`

`route_from_intervening` only runs when `dispatch_event` is called for that session — and nothing
calls `dispatch_event` on a timer. The QUIZZING deadline uses the same shape for the same reason:
the check has to live in whatever *does* fire regularly (attention signals, ~5s cadence per the
Scale Contract) or on any other client event that happens to arrive, not in the router itself.
