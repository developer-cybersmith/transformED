---
baseline_commit: 17fea79ca22bac41daa20d3b929480b64f86d0ea
---

# Story 2.10: Wire Tier Context into Player + Session Report (completes S2-10)

Status: ready-for-dev

## Story

As a student who picked a Learner Mode tier and completed a session,
I want to see which tier my lesson was generated at, and see my quiz performance as a real percentage of what was actually asked (not a raw, tier-blind percentage),
so that "78% quiz accuracy" means something different — and is shown as such — for a 3-question Refresher lesson versus a 20-question Full-Depth one.

**Source:** this is Dev 2's own Sprint 2 task **S2-10** (`docs/dev2-sprint-tracker.md` §11) — "Tier Badge on Player + Session Report." It was investigated twice and deferred both times: first on 2026-07-18 (no tier data path existed anywhere), then re-investigated on 2026-07-21 after S2-09 landed and split into two halves — an unblocked **player half** (the lesson's own tier was already available client-side, just never displayed) and a blocked **session-report half** (the `SessionReport` API response had no `tier` field at all). The session-report half is now unblocked: Dev 3 shipped **Story 3-29** (`tier`/`tier_label`/`quiz_total_questions`/`quiz_correct_count`/`quiz_accuracy_label` on `GET /session/{id}/report`) and **Story 3-30** (`learner_dna_snapshot`), both merged to `main` (PR #77/#78, `f7c758b`/`96ae37a`) as part of the Learner Mode Sprint. This story wires both halves, and additionally fixes a real bug found while scoping this: `SessionReport.tsx` currently displays `quiz_score` as a raw percentage, which is exactly the "Pitfall 2" violation Dev 3's own frontend integration guide (`docs/lm-sprint-frontend-integration.html`) calls out.

**Important correction versus Dev 3's HTML integration guide — verified against the actual shipped code/tests, not assumed:** the HTML guide's `DimensionLabel`/`GrowthLabel` types are stale relative to what actually shipped:
- Guide says `DimensionLabel = 'Beginning' | 'Developing' | 'Proficient' | 'Advanced'`. **Actual** (confirmed in `docs/stories/3-30-session-report-learner-dna-snapshot.md`'s AC-5/AC-6, reusing the existing `_score_to_label()` helper): `'Proficient'` (≥75) | `'Developing'` (≥60) | `'Emerging'` (≥40) | `'Beginning'` (<40) — **no `'Advanced'` tier exists**, and `'Emerging'` replaces one of the guide's bands.
- Guide says `GrowthLabel = 'Improving' | 'Stable' | 'Declining' | null`. **Actual** (AC-7): `'Improving'` (delta > 2.0) | `'Stable'` (-2.0 ≤ delta ≤ 2.0, boundary-inclusive both ends) | `'Needs Attention'` (delta < -2.0) | `null`. **There is no `'Declining'` value — it's `'Needs Attention'`.**

Use the values in this story (verified against the real story file + its tests), not the HTML guide's, wherever they conflict.

## Acceptance Criteria

1. **AC-1 — Tier badge on the player.** `Player.tsx` displays the lesson's tier as a human-readable label (e.g. "Full-Depth") somewhere in the existing pre-slide metadata area, using `lesson.metadata.tier` (`'T1'|'T2'|'T3'`, already a required field on the frozen `LessonPackage` type — no backend work needed). Label mapping must match the backend's own `_TIER_LABELS` exactly: `T1 → 'Full-Depth'`, `T2 → 'Standard'`, `T3 → 'Refresher'` (do not invent different copy).
2. **AC-2 — `SessionReport` TS type gains the 6 new fields.** `apps/web/src/types/assessment.ts`'s `SessionReport` interface gains: `tier: 'T1' | 'T2' | 'T3'`, `tier_label: string`, `quiz_total_questions: number`, `quiz_correct_count: number`, `quiz_accuracy_label: 'Strong' | 'Developing' | 'Needs Review' | null`, `learner_dna_snapshot: LearnerDnaSnapshot | null`. New `LearnerDnaSnapshot` type: `{ dimension_labels: Record<DnaDimension, DnaDimensionLabel>; growth_labels: Record<DnaDimension, DnaGrowthLabel | null> }` with `DnaDimensionLabel = 'Beginning' | 'Emerging' | 'Developing' | 'Proficient'` and `DnaGrowthLabel = 'Improving' | 'Stable' | 'Needs Attention'` (the corrected values, per the Source section above) over the 9 `DnaDimension` names (`pattern_recognition`, `logical_deduction`, `processing_speed`, `frustration_tolerance`, `persistence`, `help_seeking`, `goal_orientation`, `curiosity_index`, `study_independence`).
3. **AC-3 — fix the raw-percentage bug.** `SessionReport.tsx` must never render `quiz_score` as visible text. Replace the current `${Math.round(report.quiz_score * 10) / 10}% correct` line with the absolute counts (`"{quiz_correct_count} / {quiz_total_questions} correct"`) plus a `quiz_accuracy_label` badge/pill (falling back to something like "No quiz questions this session" when the label is `null`, matching the existing `teachback_score === null` fallback pattern already in this file). `quiz_score` stays in the TS type (still a real API field, used elsewhere for CES) — it just must never be rendered as text on this page.
4. **AC-4 — tier context shown on the report.** The report displays `tier_label` (e.g. "Full-Depth Session").
5. **AC-5 — DNA snapshot section, conditionally rendered.** When `learner_dna_snapshot` is non-null, show all 9 dimensions' `dimension_labels` (human-readable dimension names, e.g. "Pattern Recognition" — never the raw snake_case key) and, where a `growth_labels` entry is non-null, a directional indicator alongside it (null growth entries show no indicator, not a "Stable" default). When `learner_dna_snapshot` is `null` (pre-onboarding user), the whole DNA section is omitted — no empty card, no error.
6. **AC-6 — no raw DNA/quiz floats anywhere.** Only the descriptive labels from AC-2/AC-5 are ever rendered as text — never a raw 0-100 dimension score, never a raw delta, never `quiz_score`. Matches the existing established convention in this same file for `ces_score`/`teachback_score` (labels only, via `formatCesLabel`/`formatTeachbackLabel`).
7. **AC-7 — no regression to existing report behavior.** Loading state, error state, CES label, teach-back label, duration/interventions formatting, "Study Again" link, and the null-quiz-score/null-teachback-score friendly messaging all continue to work exactly as today — this story only changes how quiz accuracy is displayed and adds new sections, it doesn't touch the rest.
8. **AC-8 — tests.** Cover: player badge shows the correct label for each of T1/T2/T3; session report shows `tier_label`; session report shows counts + `quiz_accuracy_label` instead of a raw percentage (and the old "raw percentage" test is intentionally updated, not just deleted); `quiz_accuracy_label === null` shows a friendly fallback; DNA section renders all 9 dimension labels when present; DNA section is entirely absent when `learner_dna_snapshot` is `null`; a `null` `growth_labels` entry for one dimension renders no indicator for that dimension while others still show theirs; no raw dimension score or delta number ever appears in rendered text.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1): `apps/web/src/components/player/Player.tsx` — add a `_TIER_LABELS` (or equivalently named) local constant mapping `LessonTier → string` matching the backend exactly, and render the mapped label in the existing pre-slide metadata block (alongside `total_segments`/`estimated_duration_mins`).
  - [ ] 1.1 RED: a test asserting the correct label renders for a T1 lesson, and a second tier value renders a different label.
  - [ ] 1.2 GREEN.
- [ ] Task 2 (AC: 2): `apps/web/src/types/assessment.ts` — add the 6 new `SessionReport` fields and the new `LearnerDnaSnapshot`/`DnaDimension`/`DnaDimensionLabel`/`DnaGrowthLabel` types, using the corrected label values from this story's Source section (not the HTML guide's).
- [ ] Task 3 (AC: 3): `apps/web/src/components/reports/SessionReport.tsx` — replace the raw `quiz_score` percentage render with `quiz_correct_count`/`quiz_total_questions` counts + `quiz_accuracy_label` (with a null fallback).
  - [ ] 3.1 RED: update the existing `'renders quiz accuracy as a real percentage'` test in `SessionReport.test.tsx` to instead assert the new counts+label display (this is an intentional behavior change per AC-3, not a regression — same pattern as prior stories in this codebase updating a test to match a deliberately changed contract). Add a new test for `quiz_accuracy_label === null`.
  - [ ] 3.2 GREEN.
- [ ] Task 4 (AC: 4): `SessionReport.tsx` — display `tier_label`.
  - [ ] 4.1 RED: a test asserting `tier_label` text appears.
  - [ ] 4.2 GREEN.
- [ ] Task 5 (AC: 5, 6): `SessionReport.tsx` — add a DNA snapshot section: a small `DIMENSION_DISPLAY_NAMES` mapping (snake_case key → human-readable name) and rendering of all 9 `dimension_labels` + conditional `growth_labels` indicators, gated on `learner_dna_snapshot !== null`.
  - [ ] 5.1 RED: tests for (a) all 9 dimension labels shown when present, (b) section entirely absent when `learner_dna_snapshot` is `null`, (c) a single `null` growth entry shows no indicator for that dimension while a non-null one elsewhere still does.
  - [ ] 5.2 GREEN.
- [ ] Task 6 (AC: 7, 8): Full regression pass — confirm every pre-existing `SessionReport.test.tsx` test not touched by Task 3 still passes unmodified; add a regression test asserting no raw dimension score/delta number ever appears in rendered text.
- [ ] Task 7 (AC: 8): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.
- [ ] Task 8: Tracker update — mark S2-10 done in `docs/dev2-sprint-tracker.md` and `docs/master-tracker.md` once merged.

## Dev Notes

### Current state of every file this story touches (read directly, not assumed)

- **`apps/web/src/types/assessment.ts`** (full file, 106 lines): `SessionReport` (lines 62-82) currently has exactly 10 fields — `session_id`, `user_id`, `lesson_id`, `ces_score`, `ces_breakdown` (5 keys), `interventions_count`, `quiz_score: number | null`, `teachback_score: number | null`, `duration_minutes`, `completed_at`. Header comment: *"Do not modify field names without a 4-developer PR review (frozen interface contract)"* — this story only **adds** new fields, never renames/removes an existing one, so no cross-team sign-off is needed (matches how Story 3-29/3-30 themselves were additive-only on the backend side). `LearnerDNA` (lines 86-93) **already has** `reassessment_due: boolean` — Story 3-31's frontend type addition already landed here somehow; not this story's concern, just noting it's already present, don't re-add it.
- **`apps/web/src/components/reports/SessionReport.tsx`** (full file, 136 lines): `useSessionReport(sessionId)` → `{report, isLoading, error}`. `LoadingState`/`ErrorState` components (both `data-testid`-tagged, untouched by this story). The buggy line is 90-93:
  ```tsx
  {report.quiz_score === null
    ? 'No quiz questions this session'
    : `${Math.round(report.quiz_score * 10) / 10}% correct`}
  ```
  Teach-back already does this correctly one card below (line 101): `{formatTeachbackLabel(report.teachback_score)}` — a label-computing function, never the raw number. Match that established pattern for quiz, but note quiz's new label comes **from the backend** (`quiz_accuracy_label`) rather than being computed client-side like `formatTeachbackLabel` — do not write a duplicate client-side quiz-accuracy-label function; the backend's version is the source of truth (it knows `quiz_total_questions`/`quiz_correct_count` server-side; the frontend should just display what it returns).
- **`apps/web/src/lib/utils.ts`**: `formatCesLabel` (lines 49-55) and `formatTeachbackLabel` (lines 57-65) are the existing "compute a label from a raw score, never render the raw score" pattern for this page. `formatTeachbackLabel` already returns `'No teach-back this session'` for `null` — mirror this exact fallback-copy style for the new `quiz_accuracy_label === null` case (e.g. `'No quiz questions this session'`, matching what's already there today for `quiz_score === null` — same condition, same copy, just sourced from the new field now).
- **`apps/web/src/components/player/Player.tsx`** (full file, 125 lines): the pre-slide metadata block is lines 62-69:
  ```tsx
  {!currentSlideId && (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6">
      <h2 className="font-serif text-xl font-semibold">{lesson.metadata.title}</h2>
      <p className="text-neutral-400 text-sm">
        {lesson.metadata.total_segments} segments · ~{lesson.metadata.estimated_duration_mins} min
      </p>
    </div>
  )}
  ```
  Add the tier label here (e.g. as a small badge/pill above or alongside this existing `<p>`, exact visual treatment is this story's call — CLAUDE.md's original S2-10 sketch used the format `"Deep · 45 min"`; using the now-canonical `tier_label` values, that becomes something like `"Full-Depth"` shown near the existing `~45 min` text). Do not touch `PlayerControls.tsx` — the pre-slide overlay already has the right context and is a lower-risk touch point (a shared, more heavily-tested component like `PlayerControls` doesn't need to change for this).
- **`packages/shared/types/lesson.ts`**: `LessonMetadata.tier: LessonTier` (required, not optional), `LessonTier = 'T1' | 'T2' | 'T3'` — confirmed present and already flowing into `Player.tsx` today via its `lesson` prop. Frozen contract, do not modify.
- **`apps/web/src/hooks/useSessionReport.ts`** (full file, 28 lines): thin SWR wrapper around `getSessionReport` from `@/lib/assessment`; `shouldRetryOnError: false` (intentional — a 404 stays a 404). No changes needed here — the additive backend fields flow through automatically once the TS type is updated.
- **`apps/web/src/__tests__/components/reports/SessionReport.test.tsx`** (full file, 125 lines): `FULL_REPORT` fixture (lines 13-24) currently has only the 10 original fields — extend it with the 6 new ones for realism. The existing test `'renders quiz accuracy as a real percentage'` (lines 49-55) currently asserts `screen.getByText(/78(\.5)?%/)` — this directly encodes the bug being fixed; update it per Task 3.1, don't just delete it. All other existing tests in this file are expected to keep passing unmodified.
- **`apps/web/src/components/onboarding/DNAResultCard.tsx`**: existing Learner DNA display precedent (`badge_labels`/`profile_text` only) — a **different** shape than this story's per-dimension `learner_dna_snapshot` (9 dimensions × 2 label maps). Don't try to reuse this component directly; it solves a different display problem (onboarding-time overall badges vs. per-session per-dimension snapshot+growth). No existing component displays a 9-dimension label grid — this story introduces that display for the first time within `SessionReport.tsx` (a new sub-section, not necessarily a new separate component file — this story's call).

### Authoritative field values (verified against `docs/stories/3-29-...md` / `3-30-...md` and their own tests — NOT the HTML guide)

```ts
type LessonTier = 'T1' | 'T2' | 'T3';
// Must match backend's _TIER_LABELS dict exactly:
// {"T1": "Full-Depth", "T2": "Standard", "T3": "Refresher"}

type QuizAccuracyLabel = 'Strong' | 'Developing' | 'Needs Review'; // null when 0 questions attempted
// Strong: accuracy >= 80%; Developing: 60% <= accuracy < 80%; Needs Review: accuracy < 60%

type DnaDimension =
  | 'pattern_recognition' | 'logical_deduction' | 'processing_speed'
  | 'frustration_tolerance' | 'persistence' | 'help_seeking'
  | 'goal_orientation' | 'curiosity_index' | 'study_independence';

type DnaDimensionLabel = 'Beginning' | 'Emerging' | 'Developing' | 'Proficient';
// Beginning: <40; Emerging: >=40 and <60; Developing: >=60 and <75; Proficient: >=75
// (reuses the backend's existing _score_to_label() helper — NOT a new mapping)

type DnaGrowthLabel = 'Improving' | 'Stable' | 'Needs Attention'; // null when no prior-session delta event
// Improving: delta > 2.0; Needs Attention: delta < -2.0; Stable: -2.0 <= delta <= 2.0 (both boundaries inclusive of Stable)
```

### What NOT to do

- Do NOT invent different tier/dimension/growth label copy than what's listed above — it must match the backend's own vocabulary exactly, since this is what the API actually returns.
- Do NOT use the HTML guide's `'Advanced'` dimension label or `'Declining'` growth label — neither exists in the shipped backend; verified directly against `docs/stories/3-30-session-report-learner-dna-snapshot.md`'s ACs and tests.
- Do NOT compute your own client-side quiz-accuracy-label from `quiz_score`/`quiz_total_questions`/`quiz_correct_count` — always display the backend's own `quiz_accuracy_label` field directly; it's already computed server-side.
- Do NOT touch `packages/shared/types/lesson.ts`, `PlayerControls.tsx`, `useSessionReport.ts`, or any backend file — this is a pure frontend consumption story; both backend endpoints are already shipped and merged.
- Do NOT remove the `quiz_score` field from the `SessionReport` TS type — it's a real, still-used API field (retained server-side for CES computation per Dev 3's own notes); only stop *rendering* it as visible text.
- Do NOT build Story 3-28 (variable quiz count / question ID format change) as part of this story — that's the quiz player's concern, a separate, not-yet-scoped piece of work.

### Project Structure Notes

Touches only: `apps/web/src/types/assessment.ts`, `apps/web/src/components/reports/SessionReport.tsx`, `apps/web/src/components/player/Player.tsx`, and their test files. No backend touches, no shared-contract (`packages/shared`) changes, no new dependencies.

### Testing standards

Vitest + `@testing-library/react`, matching `SessionReport.test.tsx`'s existing pattern exactly: mock `@/hooks/useSessionReport` wholesale via `vi.hoisted`/`vi.mock`, assert on rendered text via `screen.getByText`/`container.textContent`. For `Player.tsx`'s new badge test, follow whatever existing test file/pattern covers `Player.tsx` today (check for an existing `Player.test.tsx` and match its mocking approach — e.g. `usePlayerStore`/`useLessonSocket` mocking conventions already established there) rather than introducing a new approach.

### References

- [Source: docs/dev2-sprint-tracker.md §11 S2-10] — original task sketch, 2026-07-18 and 2026-07-21 investigation notes
- [Source: docs/stories/3-29-session-report-tier-context.md] — authoritative AC-1/2/5/8 field definitions and label thresholds (backend, merged `main`)
- [Source: docs/stories/3-30-session-report-learner-dna-snapshot.md] — authoritative AC-2..9 `learner_dna_snapshot` shape, dimension/growth label thresholds (backend, merged `main`)
- [Source: docs/lm-sprint-frontend-integration.html] — Dev 3's frontend integration guide; useful for endpoint/flow context, but its `DimensionLabel`/`GrowthLabel` type definitions are stale — do not copy those two type definitions from it
- [Source: apps/web/src/types/assessment.ts, apps/web/src/components/reports/SessionReport.tsx, apps/web/src/components/player/Player.tsx, apps/web/src/lib/utils.ts, apps/web/src/hooks/useSessionReport.ts, apps/web/src/__tests__/components/reports/SessionReport.test.tsx] — all read in full this session, current state documented above

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-23 | Story created — completes Dev 2's S2-10, unblocked by Dev 3's Stories 3-29/3-30. Branch `sprint2/s2-10-tier-context-wiring` off `sprint2-master`. Corrected the HTML integration guide's stale DNA label values against the actual shipped story files/tests before writing ACs. | Dev 2 |

## Dev Agent Record

_Pending implementation._
