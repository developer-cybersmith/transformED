# Story 3-43 — Demo-readiness fixes: lesson_planner batch reliability + narration cap (D75, D76)

**Branch:** `sprint3/s3-43-demo-readiness-fixes` (from `main`).
**Owner:** Dev 1.
**Trigger:** stakeholder-demo goal — "generate one real lesson of at least 15 minutes." A
4-agent investigation plus direct code verification found exactly two real, root-caused
blockers standing between the current codebase and that goal, both in Dev 1's domain, both
small. This story fixes only those two things, with the minimum change that actually solves
each.

## Process note — order of work

D75's implementation (config change + test fixes) was written and verified GREEN before this
story file, for the same reason as Story 3-40/3-42: this was root-caused through direct,
hands-on investigation (reading the real code, hand-verifying that the obvious fix — `<=` to
`<` — would have been a no-op given the current defaults), not planned in advance. This file is
written to accurately describe what was found and fixed, and is committed alone, before D75's
implementation commit and before D76's implementation begins, so all three stay separately
reviewable. D76 (the narration cap raise) has not been implemented yet as of this commit — it
follows in its own commit once this story lands, matching the plan's phase-by-phase structure.

## D75 — `lesson_planner` batch reliability

**Defect.** `lesson_planner_batch_size` (Story 2-16) defaults to 15, **equal to**
`structure_max_sections` (also 15). Story 2-16's own comment
(`graph.py:1450-1453`) assumed a chapter coalesced to exactly the max would still "fit a single
planner call" safely — the batching it built (to prevent a single LLM completion from
"collapsing" a large segment-id echo list, its own documented 44-in/10-out example) never
actually triggers at the default config, because the condition is `len(segment_summaries) <=
batch_size` and the two values are equal.

That assumption is now disproven by direct observation: two real L1 acceptance-run attempts on
the same real chapter (15 coalesced segments) returned 5 and 12 segments respectively —
`lesson_planner segment count mismatch — expected 15, got 5` / `got 12`.

**The obvious fix doesn't work.** Changing `graph.py:1420` from `<=` to `<` is a **no-op** for
the current defaults: a 15-item list split into batches of size 15 (`_batched`-equivalent slicing
at `graph.py:1425-1428`) still produces exactly one batch containing all 15 items — identical
to the single-call path. Verified this by hand (`range(0, 15, 15)` yields one slice) before
writing any code, so the actual fix addresses the real mechanism, not the symptom.

**The real fix.** Lower `lesson_planner_batch_size`'s default strictly below
`structure_max_sections` (15 → **10**). No documented "safe" threshold exists for LLM
segment-id-echo reliability — 10 is a reasoned, conservative margin below the observed-unreliable
value of 15, not a proven number. Easy to re-tune via env var if a different value proves better
in practice.

**Changed:**
- `apps/api/app/config.py` — `lesson_planner_batch_size` default `15` → `10`
- `apps/api/tests/unit/test_coalesce_sections.py::test_config_defaults_and_planner_batch_invariant`
  — flipped from asserting `structure_max_sections <= lesson_planner_batch_size` (the
  now-disproven assumption) to `lesson_planner_batch_size < structure_max_sections` (the new
  deliberate relationship: the maximal chapter must always genuinely batch)
- `apps/api/tests/unit/test_lesson_planner_node.py::test_planner_batch_boundaries` — its
  parametrize table hardcoded expected call counts against the old batch_size=15 boundary;
  updated to the new batch_size=10 boundary, and added the `n=15` case explicitly (the real
  `structure_max_sections` value — this codebase's actual real-world maximum) since that's the
  literal scenario that failed in production
- New test `test_planner_batches_at_structure_max_sections_boundary` — exactly
  `settings.structure_max_sections` (not a hardcoded 15, so it stays correct if that default is
  ever re-tuned) segment summaries, asserts `complete_structured` is called more than once under
  the real default config

**Not changed:** the split/reassemble/guard logic itself (`graph.py:1420-1489`) — it was already
correct, it just needed to actually be reachable.

## D76 — Narration cap too low for a 15-minute lesson (not yet implemented as of this commit)

**Defect.** `max_narration_chars_per_lesson` (Story 3-37) defaults to 10,000, sized against a
stale speed assumption in `docs/decisionupdate.md` §8 (~1,600 chars/min). Real measured Sarvam
rate (live test, this session): **18.44 chars/sec = 1,106.6 chars/min**. At the real rate, 10,000
chars ≈ 9 minutes, not 15. 15 real minutes needs ≈16,600 characters.

**Cost is not the real constraint.** At `COST_PER_CHAR = 0.00002`, even 17,000 narration chars
costs ≈$0.33 in TTS, ≈$0.40 total lesson cost (TTS+LLM+image, derived from `decisionupdate.md`'s
own "TTS is 67–73% of total" claim) — about 13% of the $3.00 ceiling. The cap was never bound by
cost; it was bound by a wrong speed assumption.

**Planned fix (this story's Phase 2, separate commit):** raise `max_narration_chars_per_lesson`
default `10,000` → `17,000` (16,600 + margin), and update the `test_tts_node.py` tests that
construct fixtures against the literal 10,000-char boundary so they pin an explicit test-local
cap instead of relying on the ambient production default (more correct — decouples the tests
from whatever the production value happens to be, not just a magic-number rewrite).

**Deliberately not touched:** the disagreeing word-count-based time ESTIMATE
(`narration_words_per_minute = 150`, used only for early/cosmetic duration estimates — the real,
final duration is already measured from actual audio via Story 3-38's `tinytag` integration, not
this estimate). A real, separate inconsistency, not required to hit the demo goal — deferred, not
fixed here, to keep this story's change minimal.

## Scale & Load

1. **Unit of work & range.** D75: one `lesson_planner` LLM call becomes 1–2 batched calls
   depending on segment count (unchanged for chapters under 10 segments; genuinely batches
   between 10 and `structure_max_sections`=15). D76: one lesson's total narration budget,
   10,000 → 17,000 chars.
2. **Fixed budgets vs variable input.** Both changes are budget re-tunings, not new budgets —
   neither introduces an unbounded read/write. D76's new cap is still a hard, enforced ceiling
   (Story 3-37's existing truncate-and-surface logic, unchanged).
3. **Scope of the limit.** Both remain per-lesson, per-deployment config values — unchanged
   scope, only the numbers move.
4. **Unbounded reads/writes.** None introduced.
5. **Inherited caps re-derived.** This IS the re-derivation for both: D75 re-derives Story
   2-16's "single call is safe at the max" assumption (disproven); D76 re-derives Story 3-37's
   cap against a real measured TTS rate instead of `decisionupdate.md`'s stale estimate.
6. **Concurrency.** No new check-then-act sequences in either change.

## Verification

- D75: RED-verified by reverting `lesson_planner_batch_size` to 15 and confirming both the new
  regression test and the flipped invariant test fail with the exact predicted assertion
  messages; restored and confirmed GREEN. Full `test_coalesce_sections.py` +
  `test_lesson_planner_node.py`: 50/50 passing. `ruff check`/`format` clean. `mypy`: +1 error,
  confirmed pre-existing pattern (32 on `main` vs 33 here, same systemic `dict[str, Any]` vs
  `PipelineState` typing gap present at every one of this file's ~30 existing test call sites,
  not a new issue class).
- D76: verification to follow in its own commit (Phase 2).
