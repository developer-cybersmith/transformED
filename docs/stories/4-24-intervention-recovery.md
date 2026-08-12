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

### Review Findings

6-layer adversarial review (`/bmad-code-review`) run 2026-08-11 against PR #129: Blind Hunter,
Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter (mandatory, returned substantive
findings — scale gate satisfied), Story Quality, Test Coverage, AC Completeness, Process
Integrity. All 8 layers completed; no failed layers. Every finding below was cross-checked
against the actual code/tests before being kept — one candidate finding (`intervention_type`
allegedly dropped from `intervening_node`'s return) was verified FALSE by direct empirical test
of LangGraph's channel semantics and dismissed; the "full regression, only two gaps" claim in
task 1.14 above was independently re-run and confirmed to understate scope (see Patch #6).

**Decision-needed (2) — must be resolved before patches are applied:**

- [ ] [Review][Decision] Cross-generation race on the delete-before-dispatch guard —
      `redis.delete()` in both `advance_tutor_state` and `process_attention_signal` deletes
      `intervention_deadline_at` by key name only, with no value/version check. Two concurrent
      WebSocket connections on the same `session_id` (an explicitly supported topology per
      `websocket.py`'s own docstring) can let a stale expiry-check's delete terminate a
      freshly-started intervention episode within milliseconds of it starting — the delete
      doesn't know which "generation" of the key it's deleting. Options: (a) compare-and-delete
      via a Lua script or WATCH/MULTI checking the value before deleting; (b) store a
      generation/episode id alongside the deadline and check it matches before dispatching;
      (c) accept as a bounded, pre-existing-shape risk (the story's own Scale & Load §6 already
      scopes "two tabs on one session" as out-of-scope) and register it with a `D-nn`, owner,
      and trigger rather than leaving it as undocumented prose. [scale+edge]
- [ ] [Review][Decision] When the INTERVENING deadline has expired AND the client's real event
      is something other than `intervention_complete` (e.g. `segment_complete`),
      `advance_tutor_state` fires the synthetic self-heal and returns unconditionally — the
      client's real event, and its side effects (`segment_complete`'s `redis.incr(segment_index)`
      never runs), are silently dropped rather than replayed after the transition to TEACHING.
      Options: (a) replay the original event through `dispatch_event` after the self-heal
      completes, now that state is TEACHING; (b) accept the drop — `segment_index` drift is
      bounded and self-corrects on the next real `segment_complete`. [blind+edge]

**Patch (9) — unambiguous fixes:**

- [ ] [Review][Patch] **CRITICAL — reopens the exact trap D63 exists to close.**
      `advance_tutor_state`'s INTERVENING guard only handles the *expired* case; any other
      client-drivable event arriving while INTERVENING and NOT yet expired falls through to
      `dispatch_event(session_id, event)`. `route_from_intervening` routes anything but
      `intervention_complete` back to `"intervening"`, re-running `intervening_node`, which
      unconditionally rewrites `intervention_deadline_at` into the future again. A client that
      sends any of the other 8 `_CLIENT_DRIVABLE_EVENTS` at least once per
      `intervention_timeout_seconds` (default 45s) while an intervention is showing — entirely
      plausible, since the player keeps sending lifecycle events regardless of the overlay —
      perpetually re-arms the timeout. Verified directly by tracing the code (not taken on the
      reviewing agent's word). Fix: no-op (return) when `state_raw == "INTERVENING"`, not yet
      expired, and `event != "intervention_complete"`.
      [`apps/api/app/modules/tutor/service.py:advance_tutor_state`] [scale — independently verified]
- [ ] [Review][Patch] `intervention_timeout_seconds` has no bounds validation. A value ≥
      `_STATE_TTL` (86400s) causes the Redis key to expire before the stored deadline is reached,
      permanently defeating the safety net (same one-way-trap shape, different route). A value
      ≤ 0 causes immediate self-heal, defeating the intervention feature entirely (the overlay
      never has a chance to display). Fix: add `ge=`/`le=` `Field` bounds in `config.py`, matching
      the sibling `qa_secs` runtime-clamp pattern already used in this file.
      [`apps/api/app/config.py`] [blind+edge+scale — 3 independent sources]
- [ ] [Review][Patch] `test_guard_scans_the_tutor_state_machine_directory_for_real` only proves
      files exist under `_TUTOR_GRAPH_DIR` — it never asserts that constant is actually a member
      of `_SCAN_DIRS` (the variable the real scan iterates). A revert to `_SCAN_DIRS =
      (_PIPELINE_DIR,)` — exactly the D63 regression this task exists to guard against — would
      pass every test in the file undetected. Fix: add `assert _TUTOR_GRAPH_DIR in _SCAN_DIRS`.
      [`apps/api/tests/unit/test_node_return_shape.py`] [test_coverage — independently verified]
- [ ] [Review][Patch] `test_advance_tutor_state_intervening_not_expired_dispatches_original_event`
      is a false-confidence test: both the "guard correctly skipped" and "guard incorrectly
      fired the self-heal" paths dispatch the identical `"intervention_complete"` string in this
      test's scenario, so it cannot distinguish them. Its QUIZZING sibling
      (`test_advance_tutor_state_not_expired_deadline_normal_flow`) includes
      `redis.delete.assert_not_called()` specifically to make that distinction; this test omitted
      it. Fix: add the same assertion. While in this test, also add: a cheap boundary test for
      `time.time() == deadline` (currently untested on both the INTERVENING and QUIZZING sides),
      and a cheap test that `intervention_complete` sent from a non-INTERVENING state is a safe
      no-op (very likely already true by construction, but unpinned).
      [`apps/api/tests/test_tutor_service.py`] [test_coverage — independently verified]
- [ ] [Review][Patch] `_intervention_deadline_expired`'s Redis-error fallback has zero logging on
      the exception path — inherited verbatim from `_quiz_deadline_expired`, but CLAUDE.md
      explicitly names "timeout" as a covered budget type requiring an explicit, surfaced
      degradation, and binding rule 6 rejects "matches an existing accepted pattern" as
      justification even when the pattern is inherited. Fix: add a `logger.warning`/`logger.error`
      call inside the `except Exception:` block with session context. (The `_quiz_deadline_expired`
      sibling has the same gap; out of this diff's scope to fix, but worth a follow-up note.)
      [`apps/api/app/modules/tutor/service.py:_intervention_deadline_expired`] [process_integrity+edge]
- [ ] [Review][Patch] Task 1.14 above and the D63 register entry both claim "full regression run
      confirmed the only failures anywhere are two pre-existing missing-dependency environment
      gaps" — independently re-run (`pytest tests -q`, full suite, not scoped to the 4
      directly-affected files) and this overstates verification scope: **174 failed, 1592 passed,
      113 skipped, 45 errors**, from at least 4 distinct causes (missing `python-multipart`;
      missing `fpdf`; `test_dna_growth.py`'s pre-existing cross-test pollution, already registered
      as **D40**; and a live-network-dependent LLM smoke test). This is exactly the failure shape
      binding rule 1 exists to catch ("verification scope = CI scope"). Fix: correct both
      `docs/DEFECT-REGISTER.md` and `docs/dev4-tracker.md` to state precisely what was verified —
      176/176 in the 4 directly-affected files, full-suite failures pre-existing and enumerated by
      cause, none touching this diff's files.
      [`docs/DEFECT-REGISTER.md`, `docs/dev4-tracker.md`] [acceptance_auditor — independently verified]
- [ ] [Review][Patch] `wireTypes.ts`'s `FlowEvent` union addition has zero test coverage — the
      Python-side allow-lists are cross-checked against each other
      (`test_e4_client_event_allowlists_match`), but nothing checks `wireTypes.ts` stays in sync
      with either. FIXED-UNGUARDED per binding rule 7. Fix: add a small TS-side test (or a
      literal-membership check) asserting `'intervention_complete'` is in `FlowEvent`.
      [`apps/web/src/lib/ws/wireTypes.ts`] [acceptance_auditor+test_coverage+ac_completeness — 3 sources]
- [ ] [Review][Patch] `intervention_timeout_seconds` is only ever exercised via hand-built
      `MagicMock` settings — no test instantiates the real `Settings` class to confirm the field
      is correctly named, defaulted, or env-bound (contrast with the sibling
      `test_intervention_cooldown_default_is_two_minutes`, which does exactly this for
      `intervention_cooldown_seconds`). Fix: add the equivalent real-`Settings` test.
      [`apps/api/tests/test_config_settings.py`] [test_coverage]
- [ ] [Review][Patch] D63's register row is textually marked CLOSED but sits under the
      "OPEN — found by Dev 3's 2026-08-05 lesson-delivery-dev4 handoff" section heading rather
      than "Closed — fixed AND guarded" — a reader scanning section headers only would count it
      as still open. Fix: move the row to the Closed section, matching how other same-day-closed
      defects (e.g. D30) are organized.
      [`docs/DEFECT-REGISTER.md`] [blind+story_quality — 2 sources]

**Deferred (1):**

- [x] [Review][Defer] Confusion-type interventions (fired via `teachback_failed`) have no cap at
      all — no counter, no once-only flag, unlike distraction (capped) and fatigue (once-only).
      Pre-existing, not introduced by this diff, but named only in this story's own Scale & Load
      prose ("unbounded by count today") with no `D-nn` ID — exactly the shape binding rule 5
      forbids ("a comment without an ID is a defect wearing a decision's clothes"). Deferred with
      **D64** registered in `docs/DEFECT-REGISTER.md` (owner: Dev 4, trigger: the first session
      with repeated teach-back failures, or Sprint 4 hardening).
      [`apps/api/app/modules/tutor/state_machine/graph.py:intervening_node`] [acceptance_auditor]

**Dismissed (4) — recorded, not actioned:**

- `intervention_type` allegedly dropped from `intervening_node`'s return when the `{**state,...}`
  spread was removed — **verified FALSE by direct empirical test**: `dispatch_event("s", "fatigue_detected")`
  was run against the real compiled graph and `result.get("intervention_type")` returned
  `"fatigue"` as expected. LangGraph's default last-value channel semantics retain
  `input_state`'s value for any key a node doesn't explicitly return — the entire premise of
  "return only the keys you own" is that omission is safe. [edge — false positive]
- The story's Context section cites `docs/handoffs/lesson-delivery-dev4.md` and
  `docs/LESSON-DELIVERY-TRACKER.md`, absent from this branch (added to `main` after this branch's
  `baseline_commit`). A branch-timing artifact, not a code defect — resolves naturally once this
  branch merges alongside `main`'s later history. [acceptance_auditor]
- The implementation commit (`13f4852`) also touched the story file — but only `Status` and
  checkbox flips, zero AC/Context/Scale & Load text changed (diffed directly against the
  story-first commit `139e7a3` to confirm). A process-hygiene nit on an already-pushed commit,
  not worth rewriting history for. [story_quality]
- New tests using mock-only assertions without a `# MOCK-CONTRACT:` tag — self-flagged by the
  auditor as low-confidence: this mirrors the already-reviewed QUIZZING precedent exactly
  (binding rule 6's carve-out for genuine pattern reuse, not the "wrong at site 19" ratchet).
  [acceptance_auditor]

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
