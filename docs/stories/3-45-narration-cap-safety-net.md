# Story 3-45 — Narration cap must be a cost safety net, not a duration target (D78)

**Branch:** `sprint3/s3-45-narration-cap-safety-net` (from `main`, immediately after Story 3-44 merged).
**Owner:** Dev 1.
**Trigger:** Phase 4 of Story 3-43's own plan — the first real, successful end-to-end
generation of a demo lesson under D75+D76+D77, inspected in full per Phase 5 of the same plan.

## Process note — order of work

As with Stories 3-40/3-42/3-44, the implementation was written and RED-GREEN verified before
this story file — found live, mid-verification of a real generated lesson, not planned in
advance. Committed alone, before the implementation commit, so the two stay separately
reviewable.

## Context

D76 (Story 3-43) raised `max_narration_chars_per_lesson` from 10,000 to 17,000, explicitly
sized to fit "a real 15-minute lesson" — the demo's stated illustrative example, not a real
product requirement. The user explicitly corrected this framing: the system must not be
bounded by any fixed duration target; lesson length must be driven by the chapter's real
content, bounded only by real cost.

Concrete evidence that the 17,000 value was actively harmful, not just mis-framed: the first
real successful generation under D75-D77 (lesson `abe4e438-052f-48d9-818f-590e3a42b2bb`, chapter
"Introduction", tier T3) produced **43,793 real narration characters** across 15 segments — a
completely ordinary chapter, well within `max_chapter_pages=200` and `structure_max_sections=15`.
The 17,000-char cap zeroed the narration script for segments 6-14 (9 of 15) once the running
total crossed the cap. Zeroed scripts have nothing to synthesize, so `tts_node` degraded all 9
straight to the `browser` fallback provider (no server-synthesized audio at all) — not a
truncation of the audio, a **complete loss of real TTS audio for 60% of the lesson**.
`package_builder`'s D32/D33 defensive recovery correctly restored the readable *text* for those
segments from `narration_scripts` (so the package didn't crash or ship blank slides — working
exactly as designed), but the *audio* experience for the majority of a demo lesson silently
degraded to whichever speech synthesis the viewer's own browser happens to have.

Real recorded cost for this same lesson never came close to justifying that degradation: 43,793
chars is ~$0.88 of Sarvam TTS spend (`COST_PER_CHAR=0.00002`) — **29% of the $3.00/lesson
ceiling**, nowhere near binding. The char cap cut in more than 3x more conservatively than the
real, already-enforced dollar ceiling (`app/core/cost_tracker.py`'s `check_ceiling`, checked
per-segment before every paid TTS call) ever would have.

## The fix

`max_narration_chars_per_lesson` default raised `17,000` -> **120,000** — sized against the
real, already-referenced cost math (decisionupdate.md §8's own "TTS is 67-73% of total lesson
cost" claim), not any duration: 120,000 chars = ~$2.40 of TTS spend at Sarvam's real
`COST_PER_CHAR` = 80% of the $3.00 ceiling, leaving the remaining 20% for LLM + image spend
already tracked by the same ceiling. This keeps the cap's original, correctly-motivated job —
"bound the dominant cost driver before it's incurred" (Story 3-37 / decisionupdate.md §8) — but
sizes it as a genuine safety net against a pathological outlier, not a number aimed at producing
any particular runtime. A chapter's real length now drives lesson length; only real cost (this
cap as a pre-emptive backstop, and `check_ceiling`'s per-segment dynamic check as the true,
dollar-accurate bound) can shorten it, and both degrade explicitly (a persisted
`narration_cap_applied` / cost-downshift record) rather than silently.

## What this does NOT do

- Does not remove the narration char cap mechanism itself (`_apply_narration_char_cap` in
  `graph.py`, unchanged) — Story 3-37's decision to have a pre-emptive character-based backstop
  ahead of the dollar-accurate `check_ceiling` stands; only the *value* was wrong, sized against
  a demo illustration instead of real cost headroom.
- Does not touch `check_ceiling` / `cost_tracker.py` — the real, dynamic, per-segment dollar
  ceiling was already correct and is the actual governing bound; this story raises the
  character pre-check to stop being *more* restrictive than it.
- Does not touch `package_builder`'s D32/D33 blank-script recovery — that defensive fix is
  correct and orthogonal; it protects against zeroed scripts from *any* cause, not just this cap.
- Does not re-run `test_tts_node.py`'s existing narration-cap boundary tests' fixture math —
  they already pin their own test-local cap via `_mock_settings_with_narration_cap` (D76), so
  they're unaffected by any production default change by construction.

## Scale & Load

1. **Unit of work & range.** One lesson's combined narration character count. Range: a few
   hundred chars (trivial chapter) to whatever `max_chapter_pages=200` /
   `structure_max_sections=15` can produce raw before coalescing — empirically ~44k chars for a
   29-page, 15-section chapter (this story's own evidence); a maximal 200-page chapter would be
   materially larger, at which point the real dollar `check_ceiling` (not this char cap) becomes
   the binding, dynamically-enforced constraint — exactly the intended division of labor.
2. **Fixed budgets vs variable input.** `max_narration_chars_per_lesson=120,000` remains a fixed
   budget; exceeding it still truncates the crossing segment and zeroes the rest, with an
   explicit, persisted `narration_cap_applied` record — behavior unchanged, only the threshold
   moved. Real dollar spend beyond this cap's own headroom is caught by the separate, already-
   enforced `check_ceiling` per segment, which also persists an explicit downshift record.
3. **Scope of the limit.** Per-lesson — unchanged.
4. **Unbounded reads/writes.** None introduced; no new reads/writes at all, one `Field(default=)`
   value changed.
5. **Inherited caps re-derived.** This IS the re-derivation — D76 sized this value against a
   demo illustration (15 minutes); this story re-sizes it against the real, load-bearing
   constraint (the $3.00/lesson cost ceiling), per Scale Contract Q5.
6. **Concurrency.** No change — this cap's enforcement was already single-lesson-scoped and
   sequential within `tts_node`; unaffected.

## Verification

- RED-GREEN verified via the Edit tool: confirmed the new regression test (below) fails against
  the pre-fix default (17,000) with the exact predicted truncation, then passes after the
  config change.
- New test `test_production_default_does_not_truncate_a_real_world_sized_lesson` — uses the
  REAL `get_settings()` (not a mocked cap, mirroring D75's
  `test_planner_batches_at_structure_max_sections_boundary` pattern) with a 43,793-char
  narration set (the exact real total from lesson `abe4e438`'s production run) split across 15
  segments matching the real per-segment lengths, and asserts every segment's script reaches
  Sarvam unmodified — proving the *production default itself*, not just the mechanism, no longer
  degrades an ordinary real chapter.
- Existing `test_lesson_wide_narration_cap_truncates_and_zeroes_over_budget_segments` and
  `test_lesson_wide_narration_under_cap_is_completely_unaffected` and the other narration-cap
  boundary tests: unaffected, still pin their own test-local cap value — confirmed still 100%
  passing, unchanged assertions.
- Full repo-wide regression: run and diffed against the established baseline (54 pre-existing
  failures, unrelated) before merge — see commit for the exact count.
