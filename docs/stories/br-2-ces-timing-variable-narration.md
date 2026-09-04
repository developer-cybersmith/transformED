---
baseline_commit: "28c73ca073cca72ebe448b49c7520afadaa45270"
---

# Story BR-2: Verify + Regression-Lock CES/Intervention Timing Against Variable Narration Length

**Status:** review
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

**Test coverage scope note (review finding, Edge Case Hunter):** regression-lock tests were added for
CES computation + the D4 gap-check, the fatigue floor, and the quiz/Q&A deadline (Tasks 2.1-2.4) — the
mechanisms with actual computation (a timestamp comparison, a duration floor, a tier-based offset)
where a future change could plausibly introduce a segment-length dependency. Intervention timeout
(D63) and the distraction cooldown/cap were included in the audit table above but deliberately did NOT
get an equivalent dedicated test: both are pure `time.time() + constant` / Redis-TTL mechanisms whose
real functions (`_intervention_deadline_expired`, `_can_intervene_distraction`) take no
session-narration-length-shaped argument at all — by function signature, not just by current
behavior — so an "inject a value, prove no effect" test here would repeat AC1's original mistake
(a test that can't fail because there's nothing for it to vary). Confirmed by direct source read of
both functions' signatures before deciding not to add tests, not assumed.

**Correction (review finding, Story Quality):** this story originally cited `AudioTimeline.tsx`'s
"0:00 — quiz fires instantly" symptom as a live, unaddressed adjacent risk. Verified directly against
`docs/dev2-sprint-tracker.md` before this correction: it was already fixed over a month earlier —
**Story 2-33** (`docs/stories/2-33-virtual-playback-clock.md`, merged to `main` via PR #106,
2026-07-29) shipped a `setInterval`-driven virtual playback clock in `AudioTimeline.tsx` that closes
this exact symptom for real. It's worth naming as historical confirmation that the general concern
behind this task (a component silently assuming a fixed/known duration) was real somewhere in the
system at one point — just not on Dev 4's side, and not still open on Dev 2's side either.

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

- [x] 2.1 Add `test_ces_computation_identical_regardless_of_segment_length` to `test_tutor_service.py`,
      using the existing `_setup()`/`_settings_mock()` fixtures. Proves `compute_ces`/
      `process_attention_signal` take no segment-length input at all.
- [x] 2.2 Add `test_fatigue_floor_depends_on_wallclock_not_segment_count` (parametrized ×2:
      few-long-segments vs many-short-segments framing) to `test_s3_45_fatigue_trigger.py` — extended
      `_make_fatigue_redis()` with an optional `segment_index` param to prove the fatigue branch never
      reads it.
- [x] 2.3 Add `test_quizzing_node_deadline_unaffected_by_preceding_segment_count` (parametrized ×2) to
      `test_tutor_graph.py`, alongside the existing `test_quizzing_node_writes_quiz_deadline_at` group —
      extended `_deadline_redis()` with an optional `segment_index` param.
- [x] 2.4 Add `test_segment_complete_advances_index_regardless_of_elapsed_time` (parametrized ×3) to
      `test_tutor_service.py`, alongside the existing `test_segment_complete_increments_segment_index`.
- [x] 2.5 Regression run: `test_tutor_service.py` + `test_tutor_graph.py` + `test_s3_45_fatigue_trigger.py`
      + `test_websocket_session.py` — 212 passed, 8/8 new test cases green. 3 pre-existing failures found
      (`test_fatigue_blocked_when_already_fired_stays_teaching`,
      `test_fatigue_detected_sets_fatigue_fired_flag`, `test_fatigue_fires_once_then_blocked`) — confirmed
      via `git stash` to be byte-identical with zero BR-2 changes applied; registered as **D143**
      (same root cause as D136, a second call site), not fixed here (out of scope).
- [x] 2.6 Updated `docs/dev4-tracker.md` BR-2 entry to `[Completed]` with the audit table + new test
      names as evidence; fixed `scripts/check_dev4_progress.py`'s `br2_ces_timing_variable_narration`
      heuristic (was checking for a placeholder `"variable_length"`/`"narration"` string pair that never
      appears in the real test names) to detect the actual 3 new test functions.

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

- **Frontend `AudioTimeline.tsx` playback-clock issue** — Dev 2's file. Already resolved (Story 2-33,
  PR #106, 2026-07-29) — see the Context section's correction above. No action needed.

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

## Dev Agent Record

### Implementation Plan

1. Investigated (Explore subagent) every timing mechanism Dev 4 owns against "does this assume segment/
   narration duration?" before writing any test — found all 8 mechanisms wall-clock- or event-driven,
   zero char-count→duration conversions anywhere in `apps/api/app/modules/tutor/` or `core/websocket.py`.
2. Surveyed existing test fixtures (`_setup`/`_settings_mock` in `test_tutor_service.py`,
   `_make_fatigue_redis`/`_fatigue_patches` in `test_s3_45_fatigue_trigger.py`, `_deadline_redis` in
   `test_tutor_graph.py`) to reuse rather than reinvent.
3. Wrote 4 new tests (8 test cases total with parametrization) directly proving the audit's claims —
   each test extends an existing key-aware Redis mock with an optional `segment_index` parameter to
   prove the relevant code path never reads it, rather than inventing a synthetic duration input that
   doesn't exist in the real function signatures.
4. Ran the new tests standalone (all passed on first write — no RED phase in the traditional sense,
   since this is a verification story proving an already-correct property, not implementing new
   behavior) then the full 4-file regression.
5. Found 3 pre-existing test failures unrelated to this story (`test_tutor_graph.py`'s fatigue tests) —
   confirmed via `git stash` they fail identically with zero BR-2 changes applied. Registered as D143
   (the same D136 import-order-binding defect, reached via a second call site:
   `graph.py`'s own direct `get_supabase()` calls, not just `pubsub.py::_sessions_awaiting`).
6. `ruff check --fix` + `ruff format` on all 3 touched test files — clean.
7. Updated `docs/dev4-tracker.md` and fixed `scripts/check_dev4_progress.py`'s heuristic.

### Completion Notes

- All 5 ACs met. This is a verification story: the audit found no timing bug on Dev 4's side, so no
  production code changed — the story's value is the 8 new regression-lock test cases, which will fail
  if a future change ever makes CES/intervention/quiz timing depend on segment or narration length.
- Found and registered **D143** while adding these tests — pre-existing, out of scope, same root cause
  as D136 but a different call site, cross-referenced in both directions.
- Confirmed, not assumed: zero production code files changed by this story (`git diff --stat` against
  `dev4/master-bug-resolution` shows only the 3 test files + tracker + defect register + check script).

### File List

| File | Change |
|------|--------|
| `apps/api/tests/test_tutor_service.py` | 2 new tests (AC1, AC4) |
| `apps/api/tests/test_s3_45_fatigue_trigger.py` | `_make_fatigue_redis()` extended with optional `segment_index` param; 1 new parametrized test (AC2) |
| `apps/api/tests/test_tutor_graph.py` | `_deadline_redis()` extended with optional `segment_index` param; 1 new parametrized test (AC3) |
| `docs/dev4-tracker.md` | BR-2 entry → `[Completed]`; dashboard counts updated |
| `docs/DEFECT-REGISTER.md` | D143 registered (found while adding these tests) |
| `scripts/check_dev4_progress.py` | Fixed `br2_ces_timing_variable_narration` heuristic to check for the real new test names |

### Change Log

- 2026-08-31: Story implemented end-to-end (audit → regression-lock tests → verified → tracker
  updated). No production code changed — verification-only story, audit found the architecture
  already correct. Status: in-progress → review.

---

## Review findings

**8-layer BMAD adversarial review, 2026-08-31, PR #163** (Blind Hunter, Edge Case Hunter, Acceptance
Auditor, Scale & Load Hunter, plus Story Quality, Test Coverage, AC Completeness, Process Integrity).

**Fixed in this PR (confirmed by 5-6 independent layers each, including empirical mutation-testing
proof from Test Coverage):**

- **AC1's test was tautological and structurally never reached the code it claimed to test**
  (6 layers: AC Completeness, Story Quality, Edge Case Hunter, Blind Hunter, Acceptance Auditor, Test
  Coverage). The original called `process_attention_signal` twice with byte-identical setup — Test
  Coverage proved by direct mutation (injecting a fake segment-index dependency into the real trigger
  branch) that the test still passed unchanged. It also supplied only 1 history entry, so the
  trigger-decision branch (`if len(history_raw) >= 2`) was never even reached. **Rewritten**: now
  injects a `segment_index` value via `_setup()`'s extended mock (matching the already-proven-sound
  AC2/AC3 pattern) and reaches the real trigger branch with 2 history entries. Re-verified by the same
  mutation technique: the rewritten test now correctly FAILS when the same regression is injected, then
  passes again once reverted.
- **The CES history gap-check (`gap_ok = abs(t0-t1) <= 2*cadence`) had zero test coverage** (Edge Case
  Hunter) — the one CES mechanism that genuinely computes against real timestamps, and every existing
  test used the legacy bare-float format that trivially sets `t=0` for both entries, never exercising
  this branch. Added `test_gap_check_depends_on_real_timestamps_not_segment_framing` using the real
  JSON `{"v","t"}` format with a short vs. long real gap, proving the mechanism reacts to actual
  elapsed time (fires within cadence tolerance, correctly suppresses when stale).
- **AC4's test didn't test elapsed time at all** (6 layers, same set as AC1). It parametrized a mocked
  `redis.incr` return value the code never reads, never mocking or varying `time.time()` as the story's
  own Dev Notes prescribed. **Rewritten**: two sequential real calls to `advance_tutor_state` with a
  mocked (non-blocking) `asyncio.sleep` gap between them — 0.05s vs. 900s — proving both produce exactly
  one increment + one dispatch regardless of the gap.
- **`check_dev4_progress.py`'s heuristic only checked 3 of 4 new test names** (Acceptance Auditor) —
  the AC4 test wasn't in the guard, so deleting it would still report BR-2 `[Completed]`. Fixed to
  check all new test names (now 3 in `test_tutor_service.py` alone, after the gap-check test was added).
- **Dashboard/script count mismatch** (Acceptance Auditor) — investigated, not blindly "fixed": the
  script's own 32/43 undercounts because its `CHECKS` dict has no entries for 4 already-`[Completed]`
  tasks tracked only in prose. Ran the script for real (not dry-run) and confirmed it made zero changes
  — every task it CAN check was already correct. Documented the gap in the tracker header rather than
  mechanically matching the narrower, wrong number.
- **Stale `AudioTimeline.tsx` citation** (Story Quality) — the story cited a frontend symptom as live,
  unaddressed risk; it was actually fixed over a month earlier (Story 2-33, PR #106, 2026-07-29),
  verified directly against `docs/dev2-sprint-tracker.md`. Corrected in both the story and the tracker.

**Registered as defects, not fixed here (out of this story's verification-only scope):**

- **D144** (Scale & Load Hunter) — the tutor FSM's `MemorySaver` checkpointer is never evicted per
  session, unlike the content pipeline's own established eviction pattern for the identical,
  CLAUDE.md-documented risk. Unbounded per-process growth; a resource-lifecycle defect, unrelated to
  narration duration.
- **D143** (found by me while adding tests, not by the review layers) — already registered before this
  review round; independently re-confirmed by 3 of the 8 layers (Process Integrity, Acceptance Auditor,
  Story Quality) via direct reproduction.

**Deliberately not added (explained, not a gap):**

- Intervention timeout (D63) and distraction-cooldown duration-independence tests (Edge Case Hunter
  flagged these as "audited but untested"). Both mechanisms' real functions take no
  session/narration-length-shaped parameter at all by signature (`_intervention_deadline_expired(session_id,
  redis)`, `_can_intervene_distraction(session_id, redis, settings)`, confirmed by direct source read) —
  adding an "inject a value, prove no effect" test here would repeat AC1's exact original mistake.
  Documented in the story's Context section instead of padding the test count.

**Confirmed clean by the review, no action needed:** AC2 and AC3's original tests were independently
mutation-tested by Test Coverage and shown to genuinely fail when the corresponding code is regressed
— no changes needed there beyond a scope-clarifying docstring addition to AC2. Process Integrity found
zero rule violations (LangGraph/provider/banned-import/Celery/PostgresSaver/unbounded-query checks all
clean; branch-stacking correctly not flagged as a violation, per the pre-approved sprint deviation).
