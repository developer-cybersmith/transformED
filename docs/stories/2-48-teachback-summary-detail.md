---
baseline_commit: c3b7b52
---

# Story 2.48: Session Report — Teach-Back Summary Detail (S3-06)

Status: ready-for-dev

## Story

As a student reviewing my session report,
I want to see what I got right and what I missed in my teach-back explanations,
so that I know what to review, not just a single vague label for the whole session.

**Source:** `docs/dev2-sprint-tracker.md` §S3-06 ("Reports Page" — "Add: ... teach-back summary
detail"). The other half of S3-06 (attention timeline chart) already shipped as Story 2-46/S3-05
and is out of scope here. §S3-06 also names "quiz accuracy by segment" as explicitly **not
buildable** without a Dev 3 backend extension — that item stays out of scope; this story only
covers the teach-back half.

**Finding from pre-implementation analysis (verified against real code, not the tracker's
one-line description):** `GET /api/assessment/session/{id}/report`
(`apps/api/app/modules/assessment/service.py:913-933`, `router.py:44-81`) already queries
`teachback_attempts` for this session — but only `.select("score")`, collapsed into a single
session-wide average (`teachback_score: float | None`). The richer, already-persisted columns
(`feedback_praise`, `feedback_correction`, `concepts_hit`, `concepts_missed`, `segment_id`) sit in
the same table, written by `score_and_persist_teachback` (`service.py:671-685`) every time a
student submits a teach-back, and are simply never selected or returned by the report endpoint.
This is the same "S3-05 pattern" as Story 2-46: extend the existing bounded query inside this
same story rather than deferring the whole story or adding a new endpoint, per direct precedent
and per that story's Dev Notes ("Do NOT add a second ... read — extend the existing ... read").

**Cross-team note (flag to Dev 3):** this story's backend task touches
`apps/api/app/modules/assessment/service.py` and `router.py`, which CLAUDE.md's team-ownership
table assigns to Dev 3 ("Quiz API, teachback scorer, CES formula, Learner DNA, session reports,
analytics"). Done here as a small, additive, read-only extension (new response fields only — no
change to the CES formula, no change to `teachback_score`, no change to any existing field),
following the exact precedent and justification already accepted for Story 2-46. Dev 3 should
review this story's Task 1 diff specifically.

**Product constraint carried over from `apps/web/src/lib/utils.ts`'s `formatTeachbackLabel`
comment:** "Teach-back score is never shown as a raw number to students (PRD: no rubric score
shown in Phase 1)." The existing session-level `teachback_score` is sent to the frontend as a raw
number over the wire and only ever rendered through `formatTeachbackLabel` — never printed
directly. This story's new per-attempt data follows the identical pattern: the raw per-attempt
`score` is included in the API payload (so the frontend can bucket it through the same
`formatTeachbackLabel` helper, avoiding a second scoring-label implementation) but the rendered
UI must never print a raw number for it, exactly like the existing Focus/Teach-Back tiles.

## Acceptance Criteria

1. **AC-1 (backend)** — `SessionReport` (`apps/api/app/modules/assessment/router.py`) gains one
   new, additive, nullable field: `teachback_details: list[TeachbackDetail] | None`, where
   `TeachbackDetail` is a new Pydantic model with fields `segment_id: str`, `score: int`,
   `feedback_praise: str | None`, `feedback_correction: str | None`,
   `concepts_hit: list[str]`, `concepts_missed: list[str]`, `attempt_number: int` — matching
   `teachback_attempts`'s real columns verbatim
   (`supabase/migrations/20260611000000_initial_schema.sql:205-217`), per Defect Register binding
   rule 4. `None` (not `[]`) when the student did no teach-back this session (mirrors the existing
   `teachback_score: None` / `ces_timeline: None` "no data" convention already used in this same
   model) — never conflate "no teach-back happened" with "teach-back happened with zero detail."
2. **AC-2 (backend)** — `get_session_report`'s Step 3 (`service.py:916-923`) extends its existing
   `teachback_attempts` query's `.select("score")` to
   `.select("segment_id, score, feedback_praise, feedback_correction, concepts_hit,
   concepts_missed, attempt_number")` and adds `.order("created_at")` (chronological — the table
   has no other ordering column usable for display sequence, and the existing BOUNDED comment
   already establishes at most one attempt per segment, so `created_at` order reflects the order
   segments were taught in). No second round trip — this is the *same* query the aggregate
   `teachback_score` is already computed from; do not add a new query. The existing `.limit(50)`
   safety ceiling and its BOUNDED comment are unchanged (comment updated to also cover the new
   columns).
3. **AC-3 (backend)** — Neither the new field nor the extended `.select()` changes the value of
   `teachback_score`, `formula_applied`, or `signal_coverage` — all three keep being computed from
   the same `tb_rows` exactly as today. Existing tests in `test_session_report_endpoint.py`
   asserting `teachback_score` must still pass unmodified.
4. **AC-4 (backend)** — A malformed or partially-null row (e.g. `feedback_praise`/
   `feedback_correction` both `None`, `concepts_hit`/`concepts_missed` empty arrays — a real,
   reachable shape per the migration's `DEFAULT '{}'` and nullable text columns) is not surfaced as
   an error; it is passed through as-is (both feedback fields `None`, both concept lists `[]`) so
   the frontend can render whichever pieces exist. This does not need synthetic fallback text —
   the frontend's own conditional rendering (AC-7) is the degradation path.
5. **AC-5 (backend)** — `apps/web/src/types/assessment.ts`'s `SessionReport` interface gains a
   matching `TeachbackDetail` interface and `teachback_details: TeachbackDetail[] | null` field,
   verified field-for-field against the real (just-changed) Python model, not the tracker prose —
   per Story 2-41's own precedent, repeated in Story 2-46.
6. **AC-6 (frontend)** — New `TeachbackDetailList` rendering (inline in `SessionReport.tsx` or a
   small extracted component, developer's choice — matching the existing file's own mix of inline
   sections and extracted `DnaSnapshotSection`) replaces nothing in the existing Teach-Back tile;
   it renders **below** the existing 4-stat grid, in the same position/ordering slot as
   `AttentionChart` and `DnaSnapshotSection` (after the grid, before `DnaSnapshotSection` — mirror
   Story 2-46's AC-8 ordering exactly: stat grid → AttentionChart → **teach-back detail** →
   DnaSnapshotSection). Rendered conditionally — omitted entirely (not an empty card) when
   `report.teachback_details` is `null` or `[]`, matching how `DnaSnapshotSection` and
   `AttentionChart` are already conditionally rendered.
7. **AC-7 (frontend)** — Each entry renders: a segment label (`Segment {index + 1}` using the
   array's already-chronological order from AC-2 — never the raw `segment_id`, which is an
   internal identifier like `seg_003`, not a display string), the bucketed label from
   `formatTeachbackLabel(entry.score)` (reused, not reimplemented — same helper the aggregate tile
   already uses, so the two never disagree about bucket boundaries), `feedback_praise` and
   `feedback_correction` as plain text when present (each independently omitted, not replaced by
   empty text, when `null`), and `concepts_hit`/`concepts_missed` as two small labeled chip lists
   (only rendered when their array is non-empty). The raw numeric `score` is never printed
   anywhere in the rendered output — same "never show the raw score" convention as
   `formatTeachbackLabel`'s own doc comment and Story 2-46's AC-4, verified with a text-content
   regex test (`/\b\d{1,3}\b/` near the teach-back section, or equivalent), not just a
   label-presence check, per that story's own testing-standards precedent.
8. **AC-8 (frontend)** — Responsive: the detail list uses the same `max-w-2xl` single-column flow
   already used by the rest of `SessionReport.tsx` — no new breakpoint logic needed (unlike Story
   2-46's chart, this is text content, not a chart requiring a mobile-collapse variant).
9. **AC-9** — Tests: backend (`teachback_details` computed correctly from a real-shaped
   `teachback_attempts` fixture with 2+ rows in a known `created_at` order, `null` when zero rows
   — reusing the existing zero-rows-→-`teachback_score=None` fixture to prove the new field
   degrades the same way, partially-null row shape from AC-4 passed through unchanged, existing
   `teachback_score`/`formula_applied`/`signal_coverage` assertions unchanged), frontend (list
   renders in order with correct labels, praise/correction independently omitted when `null`,
   concept chips omitted when empty, raw-score-absence regex check, conditional mount/omission in
   `SessionReport.tsx` matching `AttentionChart`'s existing mount test pattern). Full `apps/api`
   and `apps/web` suites green (net new failures = 0 against each suite's pre-existing baseline,
   verified via the disposable-worktree-comparison pattern established in Story 2-46), `tsc
   --noEmit` clean, `eslint` clean on every touched file.

## Scale & Load

Answering `docs/SCALE-CONTRACT.md`'s six questions.

1. **Unit of work and its range.** One unit = one session report render's teach-back detail list.
   Min: 0 entries (student skipped every teach-back — already the common `teachback_score=None`
   case). Typical: 1-15 entries (one per segment taught, since a lesson's segment count is itself
   capped elsewhere in the pipeline — `structure_max_sections` and this codebase's own T1/T2/T3
   segment-count tiers). Largest actually possible: the existing `.limit(50)` safety ceiling on
   the same query this field is drawn from — a hard cap already in production, not newly
   introduced. No entry beyond it is silently dropped without the existing ceiling already being
   the answer; this story does not change that ceiling.
2. **Fixed budgets vs. variable input.** No new budget is introduced — this story rides the
   existing `.limit(50)` on the `teachback_attempts` query (Step 3), which already sits far above
   the natural bound (at most one attempt per segment, no retry). If a future change ever allowed
   teach-back retries, the natural bound would grow and `.limit(50)` would need re-deriving —
   noted here so a future change to retry behavior does not silently inherit this cap without
   reconsidering it (same spirit as Story 2-46's D109 finding, though no defect is registered here
   since the cap is not currently reachable).
3. **Scope of every limit.** `.limit(50)` is per-request (one `get_session_report` call for one
   session) — no shared-bucket or per-instance risk, identical scope to the existing quiz/teachback
   queries in the same function.
4. **Unbounded reads/writes.** None introduced. The `.select()` column list grows on the exact
   same already-bounded query; no new query, no new write path.
5. **Inherited caps re-derived?** `.limit(50)`'s sizing rationale (max 15 segments × 1 attempt,
   safety ceiling well above that) was written for the aggregate-score use case and holds
   identically for the per-attempt detail use case — the unit of work (one attempt per segment)
   has not changed, so no re-derivation is needed, unlike Story 2-46's `_CES_HISTORY_MAX` case
   where the unit of work genuinely changed (window-for-triggering vs. window-for-display).
6. **Concurrent check-then-act safety.** No check-then-act sequence is introduced — this is a
   read-only extension of an existing GET endpoint's response fields, identical in shape to Story
   2-46's own answer to this question.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1, 2, 3, 4 — backend): Add `TeachbackDetail` model, extend `SessionReport` with
  `teachback_details`, extend the existing `teachback_attempts` query's `.select()`/`.order()`,
  build the list in `get_session_report`.
  - [ ] 1.1 RED: test that a `teachback_attempts` fixture with 2 rows (known `created_at` order,
    one row with both feedback fields populated and non-empty concept arrays, one row with both
    feedback fields `None` and empty concept arrays) produces `teachback_details` in the same
    chronological order with fields passed through unchanged; a zero-row fixture produces `None`;
    existing `teachback_score`/`formula_applied`/`signal_coverage` assertions in
    `test_session_report_endpoint.py` still pass unmodified with no fixture changes to those
    specific assertions.
  - [ ] 1.2 GREEN: implement. Verify actual call-count/position impact on
    `test_session_report_endpoint.py`'s mock builder (Story 2-46 hit exactly this — inserting a
    changed `.select()` on an *existing* call should not shift call-position indices the way a
    *new* call did, but confirm empirically rather than assuming).
- [ ] Task 2 (AC: 5): Add `TeachbackDetail` interface and `teachback_details` field to
  `apps/web/src/types/assessment.ts`'s `SessionReport`, verified field-for-field against the real
  (just-changed) Python model.
  - [ ] 2.1 RED: `tsc --noEmit` confirmed error before adding the fields (pure type addition — no
    runtime RED signal, per Story 2-46's own finding about esbuild's type-stripping transform).
    Add a runtime pass-through test too, for the non-type-checked regression net.
  - [ ] 2.2 GREEN: implement. Check for pre-existing `SessionReport` object literals elsewhere in
    the test suite (`__tests__/types/assessment.test.ts` had 2 in Story 2-46) that may need the new
    field added once it's required-but-nullable.
- [ ] Task 3 (AC: 6, 7, 8): Render teach-back detail in `SessionReport.tsx` — segment label,
  `formatTeachbackLabel(entry.score)`, conditional praise/correction, conditional concept chips,
  positioned after `AttentionChart` and before `DnaSnapshotSection`.
  - [ ] 3.1 RED: tests for each of AC-6 through AC-8 — list renders in order with correct segment
    labels, `formatTeachbackLabel` bucket text present, praise/correction independently absent
    when `null`, concept chips absent when their array is empty, raw-score-absence regex check
    (per Story 2-46's exact testing-standards precedent — assert on rendered DOM text, not on the
    mock), conditional mount/omission when `teachback_details` is `null`/`[]`.
  - [ ] 3.2 GREEN: implement.
- [ ] Task 4 (AC: 9): Full `apps/api` and `apps/web` suites green (verify net-new failures = 0
  against each suite's current pre-existing baseline via disposable worktree comparison, per Story
  2-46's established pattern); `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT add a second query for teach-back detail — extend the existing Step 3
  `teachback_attempts` `.select()` in `get_session_report`, matching the "process once" principle
  and Story 2-46's own explicit precedent ("Do NOT add a second Redis read... extend the
  existing... read").
- Do NOT print the raw per-attempt `score` (or the raw session-level `teachback_score`) anywhere
  in rendered output — always route through `formatTeachbackLabel`. This is not a new rule; it is
  the same rule the existing Teach-Back tile already follows, extended to the new per-attempt
  entries.
- Do NOT render `segment_id` directly as a label — it is an internal identifier (e.g. `seg_003`),
  not student-facing text. Use array position (`Segment {index + 1}`) instead, relying on AC-2's
  `.order("created_at")` for correct sequencing.
- Do NOT change `teachback_score`, `formula_applied`, `signal_coverage`, or the CES formula in any
  way — this story is a read-only, additive extension, identical in spirit to Story 2-46's
  backend task.
- Do NOT invent synthetic placeholder text for a missing `feedback_praise`/`feedback_correction`
  (e.g. "No feedback available") — omit that piece of the entry entirely, per AC-4/AC-7.

### Testing standards

Follow `SessionReport.test.tsx`'s existing pattern of mocking `useSessionReport`'s return value
directly and asserting on rendered output (same convention Story 2-46 followed for
`AttentionChart`'s wiring tests). For the "never shows a raw score" AC, assert on rendered text
content with a regex, not just presence of the qualitative label — per
`docs/DEFECT-REGISTER.md` binding rule 2 (no test may assert only on a mock it constructed) and
Story 2-46's identical precedent for `AttentionChart`'s Y-axis.

**Verifying no new regressions (established pattern, used in Story 2-46 and this session's
earlier merges):** before this story's final commit, use a disposable `git worktree add
../transformED-s306-check main --detach` to run the same `apps/api`/`apps/web` test files against
the pre-story baseline, and diff the failure sets. Remove the worktree
(`git worktree remove --force`) when done.

### References

- [Source: docs/dev2-sprint-tracker.md §S3-06 — original AC text and file locations]
- [Source: apps/api/app/modules/assessment/router.py:44-81 — real `SessionReport` model, verified
  live 2026-08-18, not the tracker's description]
- [Source: apps/api/app/modules/assessment/service.py:600-710 — `score_and_persist_teachback`,
  confirms every field `TeachbackDetail` will expose is already written per attempt]
- [Source: apps/api/app/modules/assessment/service.py:913-939 — `get_session_report`'s existing
  Step 3 `teachback_attempts` query and BOUNDED comment to extend]
- [Source: supabase/migrations/20260611000000_initial_schema.sql:205-217 — real
  `teachback_attempts` table columns, validated per Defect Register binding rule 4]
- [Source: apps/web/src/types/assessment.ts:89-124 — real `SessionReport` TS interface to extend,
  and its existing `null`-vs-`[]` conventions for optional list fields]
- [Source: apps/web/src/lib/utils.ts:67-73 — `formatTeachbackLabel`, the single source of truth
  for score→label bucketing; its own doc comment stating raw scores are never shown to students]
- [Source: apps/web/src/components/reports/SessionReport.tsx — existing card styling, ordering,
  and conditional-render pattern (`AttentionChart`, `DnaSnapshotSection`) to match]
- [Source: docs/stories/2-46-attention-timeline-chart.md — direct precedent for extending an
  existing bounded report-endpoint query within the same story rather than deferring or adding a
  new endpoint, and for the worktree-based regression-verification pattern]
- [Source: docs/SCALE-CONTRACT.md — the six questions answered above]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-18 | Story created per S3-06 in `docs/dev2-sprint-tracker.md` (teach-back-detail half only — the attention-timeline half already shipped as Story 2-46/S3-05). Branch `sprint3/s3-06-teachback-detail` off `main`. Pre-implementation analysis confirmed the real `get_session_report`/`teachback_attempts` gap (aggregate-only `score` selected; richer per-attempt columns already persisted but never exposed) directly against live code, following the identical investigative pattern and resolution precedent already accepted for Story 2-46. | Dev 2 |

## Dev Agent Record

### Implementation Plan

_To be filled in during implementation._

### Completion Notes

_To be filled in during implementation._

### File List

_To be filled in during implementation._
