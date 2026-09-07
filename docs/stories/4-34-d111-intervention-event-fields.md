# Story 4-34 — D111: thread real `window_index` / `ces_at_trigger` into intervention events

**Owner:** Dev 4 (dispatch plumbing) — closes the Dev-4-owned half of D111 (Dev 3 owns the
analytics/calibration consumption side, unaffected by this story).
**Status:** done
**Registered defect:** `docs/DEFECT-REGISTER.md` **D111**
**Origin:** Surfaced opportunistically while scoping Sprint 4's `threshold_tuning` /
`cooldown_tuning` tasks (`docs/dev4-tracker.md`) — both require real, correct
`session_events.ces_at_trigger` values once real sessions exist; D111 means every row
recorded so far has `ces_at_trigger=0.0`, which would silently poison that analysis the
moment it runs. This is one of the pending-item's blockers that does **not** require real
students — pure dispatch-plumbing code, fixable and testable today.

---

## Background

`intervening_node` (`apps/api/app/modules/tutor/state_machine/graph.py`) already reads
`state.get("window_index")` / `state.get("last_ces")` and forwards them to
`write_intervention_event(...)`, which persists them into `session_events.payload` under
the `intervention_triggered` event type (landed under S3-36/D12). But `dispatch_event`'s
`input_state` construction never sets either top-level key, and neither of the two real
call sites (`tutor/service.py::process_attention_signal`, for `distraction_detected` and
`fatigue_detected`) passes them through `payload`. Every intervention event ever recorded
therefore has `window_index=0` and `ces_at_trigger=0.0`, regardless of the real values that
were in scope at the moment of dispatch.

## Acceptance Criteria

- **AC1.** `dispatch_event(session_id, event, payload=...)` copies `payload["window_index"]`
  and `payload["last_ces"]` into the top-level `input_state` it builds (defaulting to `0`
  and `0.0` respectively when the caller's payload omits them — preserves current behavior
  for every other event type, e.g. `segment_complete`, that never sets these).
- **AC2.** The `distraction_detected` dispatch call in `process_attention_signal` includes
  the real, already-in-scope `window_index` (from the `ces_update` counter) and the real,
  already-in-scope current-window CES value (the `ces` local, not the possibly-unset `v0`
  history entry — see Scale & Load Q5) in its `payload`.
- **AC3.** The `fatigue_detected` dispatch call in `process_attention_signal` includes the
  same two fields, using the same `ces`/`window_index` locals (fatigue has no CES-history
  dependency of its own, so this is the only value available and is exactly "the CES score
  in effect when the fatigue intervention fired").
- **AC4.** An end-to-end test drives the real FSM (`dispatch_event`) for both
  `distraction_detected` and `fatigue_detected` with non-zero `window_index`/`last_ces` in
  the payload and asserts `write_intervention_event` is invoked with those same non-zero
  values — proving the full path, not just `intervening_node` in isolation (which already
  had passing tests for the case where someone *does* populate these keys — AC4 in
  `test_intervention_event_persistence.py`; the gap was strictly the caller side).
- **AC5.** Existing tests for events that don't carry these fields (e.g.
  `test_intervention_event_persistence.py::test_db_write_failure_does_not_raise_from_intervening_node`,
  which omits `window_index`/`last_ces` from its `state` fixture entirely) continue to pass
  unchanged — the default-to-zero fallback is preserved, not removed.
- **AC6.** `docs/DEFECT-REGISTER.md` D111 updated to `FIXED` (Dev-4 half) with the guard test
  named, not left as a bare `TODO`/`FIXME` per binding rule 5.
- **AC7.** No LangGraph node returns `{**state, ...}` (existing repo-wide ban) — this story
  only adds keys to a dict literal, `intervening_node`'s return shape is untouched.

## Scale & Load

1. **Unit of work & range.** One dispatch call, one small dict merge (2 extra keys, both
   already-computed local `int`/`float` scalars) — O(1), no new I/O, no new Redis/DB round
   trip. Range is identical before and after: exactly the calls that already happen today.
2. **Fixed budgets vs variable input.** None introduced. No new loop, no new fan-out.
3. **Scope of limits.** N/A — no new limit; this only corrects the values written into an
   existing per-session-event field.
4. **Unbounded reads/writes.** None. `write_intervention_event`'s single-row insert into
   `session_events` is unchanged in shape and cardinality (still fire-and-forget via
   `asyncio.create_task`, still one row per intervention).
5. **Inherited caps re-derived?** N/A. The one design choice worth writing down: fatigue
   dispatch has no CES-history value of its own (fatigue triggers off blink/head-pose, not
   CES) — reusing the current window's freshly-computed `ces` local (always in scope
   whenever `state_raw == "TEACHING"`, which both dispatch call sites already require) is
   correct and avoids referencing the history-derived `v0`, which is only assigned inside
   `if len(history_raw) >= 2:` and would raise `UnboundLocalError` for a fatigue dispatch
   reached via the exhaustion-fallback path with a short/empty history.
6. **Concurrent-request safety.** No check-then-act sequence is added — this is a pure
   value-threading fix into an existing fire-and-forget write path with no shared mutable
   state.

## Out of scope

- Dev 3's consumption side (any CES-calibration query already reading
  `session_events.ces_at_trigger` needs no change — it will simply start seeing real values
  going forward; historical rows recorded before this fix remain `0.0`/`0`, which is a data
  quality note for whoever runs `threshold_tuning`'s analysis, not a code defect).
- Any change to `write_intervention_event` itself, the `session_events` schema, or
  `KNOWN_EVENT_TYPES` — all already correct (S3-36/D12).
- The separate, still-open half of D111 (none — this story closes it entirely on review;
  see Defect Register update).
