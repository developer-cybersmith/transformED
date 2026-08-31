---
baseline_commit: "28c73ca073cca72ebe448b49c7520afadaa45270"
---

# Story BR-2: Verify + Regression-Lock CES/Intervention Timing Against Variable Narration Length

**Status:** in-progress
**Sprint:** Bug Resolution — Feature Sprint 2 (`docs/dev4-tracker.md`)
**Branch:** `dev4/master-bug-resolution-br-2-ces-timing-narration` (off `dev4/master-bug-resolution`)

---

## Story

As Dev 4 (tutor/CES/WS owner),
I want direct evidence — not just architectural confidence — that CES windowing, cooldown/distraction-
cap/fatigue-once guards, the intervention timeout, and the Learner-Mode quiz/Q&A deadline all produce
correct, unchanged behavior regardless of how long a segment's narration actually runs,
so that "variable-length narration" (real TTS segments measured at 1,351–4,069 chars, ~1.2–3.7 min per
segment — Story 3-42/3-45) can never silently break tutor timing the way a fixed-duration assumption
would, and so a future change can't reintroduce that assumption without a test catching it.

---

## Context — audit performed before writing this story (2026-08-31)

Per the earlier scope correction (confirmed with the user, 2026-08-29): "variable-length human-recorded
narration" means real, already-variable TTS-synthesized narration duration, not a literal
human-voice-recording pipeline change.

Before writing any code, audited every timing mechanism Dev 4 owns against the concrete question
"does this assume how long a segment's narration takes to play?":

| Mechanism | File:function | Verdict |
|---|---|---|
| CES window/history write | `service.py::process_attention_signal` | **Event-driven** — fires per inbound `attention_signal`, no timer, no segment-length input |
| `ces_cadence_seconds` staleness gap-check | `service.py` (`gap_ok = abs(t0-t1) <= 2*cadence`) | **Wall-clock**, compares signal-embedded timestamps, not segment length |
| `ces_history` ring buffer | `service.py` (`_CES_HISTORY_MAX = 10`) | **Count-bounded**, not duration-bounded |
| Distraction cooldown/cap | `graph.py::_can_intervene_distraction` (Lua) | **Redis TTL/counter**, `intervention_cooldown_seconds` is real seconds |
| Fatigue-once | `graph.py::_can_intervene_fatigue`, `service.py` (`ces_fatigue_min_session_seconds`) | **Wall-clock session duration** (`time.time() - session_start_ts`), not segment count |
| Intervention timeout (D63) | `graph.py::intervening_node`, `service.py` deadline checks | **Wall-clock deadline** (`time.time() + intervention_timeout_seconds`) |
| Quiz/Q&A deadline + tier `qa_phase_seconds` | `graph.py::quizzing_node`, `service.py` | **Wall-clock deadline** sized by tier (T1/T2/T3), set once at QUIZZING entry — does not read or adjust for preceding narration length |
| `segment_complete` → `segment_index` advance | `websocket.py` → `service.py::advance_tutor_state` | **Purely client-event-driven** — no server timer, no assumed elapsed time |

**Result: no timing bug found.** Every mechanism Dev 4 owns is wall-clock- or event-driven, already
safe against variable narration length. Repo-wide grep for any char-count→duration conversion
(`words_per_minute`, `expected_duration`, etc.) inside `apps/api/app/modules/tutor/` or
`apps/api/app/core/websocket.py`: **zero hits** — every such conversion that exists lives exclusively
in the content-generation pipeline (`content/pipeline/graph.py`, Dev 1's lesson-planning/slide-budget
code), never read by the tutor FSM or the WS layer at runtime.

**Worth naming, not fixing here:** a sibling *frontend* component historically had exactly this class
of bug — `docs/dev1-tracker.md`'s handoff notes reference `AudioTimeline.tsx`'s "0:00 — quiz fires
instantly" symptom needing "a virtual playback clock," i.e., the frontend narration-playback timeline
assumed a duration that didn't match reality. That is Dev 2's file, out of this story's scope, but it
confirms the concern behind this task was real somewhere in the system — just not on Dev 4's side.

**Given the audit found the architecture already correct, this story's value is closing the
verification gap, not a code fix:** none of the mechanisms above has a test that explicitly varies
segment/narration length and proves the outcome is unchanged. Without such a test, "duration-agnostic"
is an architectural property nobody would notice regressing. This story adds that regression lock.

---

## Acceptance Criteria

- **AC1:** A parametrized test proves `process_attention_signal`'s CES window/history write and the
  distraction-trigger decision are byte-identical whether the signals arrive during what a short
  (~800-char, ~45s) or long (~4,069-char, ~3.7min) real-measured segment would be — i.e., CES
  computation depends only on signal content/cadence, never on an elapsed-since-segment-start value.
- **AC2:** A test proves the fatigue-once floor (`ces_fatigue_min_session_seconds`) fires/blocks based
  purely on real elapsed session wall-clock time, giving the identical result whether that wall-clock
  time was reached via few long segments or many short ones (segment *count* must not matter, only
  real elapsed time).
- **AC3:** A test proves the quiz/Q&A deadline (`quiz_deadline_at`, tier `qa_phase_seconds`) set at
  QUIZZING entry is always `now + qa_secs` regardless of how long the preceding segment's narration
  ran — i.e., no code path reads segment narration length when computing this deadline.
- **AC4:** A test proves `segment_complete` → `segment_index` advancement fires exactly once per
  client event regardless of the real elapsed time between the previous event and this one (a
  very-short and a very-long gap both advance the index by exactly 1, no more, no less, no assumed
  "enough time must have passed" gate).
- **AC5:** The tracker (`docs/dev4-tracker.md`) records this as a verification closure — audit table +
  regression tests — not as a bug fix, since none was needed.

---

## Tasks / Subtasks

- [ ] 2.1 Add `test_ces_computation_identical_regardless_of_segment_length` (parametrized short/long) to
      `test_tutor_service.py`, using the existing `_setup()`/`_settings_mock()` fixtures.
- [ ] 2.2 Add `test_fatigue_floor_depends_on_wallclock_not_segment_count` — drive the real fatigue guard
      with the session-start timestamp fixed and prove the verdict is identical whether reached via a
      simulated few-long-segments vs many-short-segments timeline (same elapsed real time either way).
- [ ] 2.3 Add `test_quiz_deadline_unaffected_by_preceding_segment_duration` to `test_tutor_service.py`,
      alongside the existing `test_quiz_deadline_expired_*` group.
- [ ] 2.4 Add `test_segment_complete_advances_index_regardless_of_elapsed_time` alongside the existing
      `test_segment_complete_increments_segment_index`.
- [ ] 2.5 Regression run: full existing `test_tutor_service.py` + `test_tutor_graph.py` +
      `test_s3_45_fatigue_trigger.py` + `test_websocket_session.py` green, unchanged.
- [ ] 2.6 Update `docs/dev4-tracker.md` BR-2 entry to `[Completed]` with the audit table + new test
      names as evidence; update `scripts/check_dev4_progress.py`'s `br2_ces_timing_variable_narration`
      heuristic to detect the new test module content instead of the placeholder string match.

---

## Dev Notes

### Existing fixtures to reuse (do not reinvent)

`test_tutor_service.py` already has `_setup(mocker, *, lrange_vals, exists, threshold, can_dispatch)`
and `_settings_mock(threshold)` — patches `app.core.redis.get_redis`, `app.config.get_settings`,
`app.modules.tutor.state_machine.graph._can_intervene_distraction` (Lua guard), and
`app.modules.tutor.state_machine.graph.dispatch_event`. New tests should build on these, not duplicate
the patch wiring.

### AC1 approach

`compute_ces(_parse_signal(payload))` is a pure function — it takes no segment/duration input at all.
The test should assert this directly (same payload → same CES value, called from two different
"simulated segment position" contexts) rather than inventing a segment-length parameter that doesn't
exist in the function signature — the point of the test is to prove the ABSENCE of such a parameter is
correct, not to add one.

### AC2 approach

Look at `test_s3_45_fatigue_trigger.py::test_exhaustion_fallback_not_dispatched_before_duration_floor`
for the existing fatigue-floor test pattern (session_start_ts-based). Extend with a parametrized case
comparing "session_start_ts is X seconds ago, reached via N segments" vs "same X seconds ago, reached
via M segments" (N != M) — the guard must not read segment/index count at all, only
`ces_fatigue_min_session_seconds` vs. real elapsed time.

### AC3 approach

`quizzing_node` (`graph.py`) writes `quiz_deadline_at = time.time() + qa_secs`. Test: call with the
segment having just transitioned from a simulated short vs. long narration (no difference in how
`quizzing_node` itself is invoked — it receives no narration-duration argument), assert the deadline
formula is identical in both.

### AC4 approach

`test_segment_complete_increments_segment_index` (existing, line ~505) is the direct template — extend
with a parametrized real-elapsed-time gap (simulate via mocked `time.time()` sequencing) to prove the
index always advances by exactly 1 on the event, never gated by elapsed time.

### Files to change

| File | Change |
|------|--------|
| `apps/api/tests/test_tutor_service.py` | 4 new tests (AC1-AC4) |
| `docs/dev4-tracker.md` | BR-2 entry → `[Completed]`, audit table + evidence |
| `scripts/check_dev4_progress.py` | Fix `br2_ces_timing_variable_narration` heuristic to detect real evidence |

### Out of scope (flagged, not built here)

- **Frontend `AudioTimeline.tsx` playback-clock issue** — Dev 2's file, referenced in Dev 1's tracker
  handoff notes as a historical symptom of exactly this class of bug on the frontend side. Not touched
  by this story; flagged for Dev 2 awareness only if not already resolved.

---

## Scale & Load (`docs/SCALE-CONTRACT.md`'s six questions)

1. **Unit of work and its range.** N/A — this story adds test coverage only, no new runtime code path,
   no new unit of work. (Reason for N/A, not a bare answer.)
2. **Fixed budgets vs. variable input.** N/A — no new fixed budget introduced; the audit's whole point
   is confirming NO budget in this domain is duration-derived. No change to any existing budget.
3. **Scope of limits.** N/A — no new limit introduced.
4. **Unbounded reads/writes.** N/A — no new query introduced; new tests exercise existing, already-
   audited code paths (`_sessions_awaiting` etc. not touched by this story at all).
5. **Inherited caps re-derived.** N/A — no cap is being re-derived; the audit confirms none of the
   existing wall-clock/count-based caps (fatigue floor, cooldown seconds, qa_phase_seconds) were ever
   sized against segment/narration length in the first place, so there is nothing to re-derive.
6. **Check-then-act under concurrency.** N/A — no new check-then-act sequence; existing guards
   (Lua-backed distraction cap, atomic intervention-deadline delete) are unchanged.

---

## Review findings

*(filled in after the 6-layer review, before merge)*
