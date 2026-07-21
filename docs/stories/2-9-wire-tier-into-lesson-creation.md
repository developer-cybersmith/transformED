---
baseline_commit: "4b4ac2132a9db053a61a4394399d0b9aa9e53eb6"
---

# Story 2-9: Wire Selected Tier into Lesson Creation

Status: ready-for-dev

## Story

As a student who just picked a Learner Mode tier,
I want that choice to actually reach the backend and stay visible while my lesson generates,
so that Learner Mode does something real instead of being a screen the student clicks through with no effect.

## Context

This is Sprint 2 task **S2-09** from `docs/dev2-sprint-tracker.md` §11 — the third of four **Learner Mode** tasks (S2-07–S2-10). It was blocked on "the tier concept doesn't exist yet in the frozen request body" — **that is now resolved**: Dev1's Sprint 2 Phase B backend (PR #74, merged to `main` 2026-07-20, now merged into `feature-learner-mode`) added real tier support to `POST /lessons`.

**Confirmed contract (read directly from the current backend code, not assumed):**
```python
# apps/api/app/modules/content/router.py — upload_lesson()
tier: str = Form(
    _DEFAULT_TIER,  # "T2"
    description="Learner Mode tier: T1 (full depth), T2 (standard, default), T3 (critical-topics refresher)",
)
...
if tier not in _VALID_TIERS:  # frozenset({"T1", "T2", "T3"})
    raise HTTPException(status_code=422, detail=f"Invalid tier {tier!r} — must be one of {sorted(_VALID_TIERS)}")
```
`apps/api/app/schemas/lesson.py`: `LessonTier = Literal["T1", "T2", "T3"]`, `DEFAULT_TIER = "T2"`. This is a **multipart form field**, sibling to the existing `file: UploadFile = File(...)` — not JSON, not part of the `LessonUploadResponse`/`LessonStatusResponse` Pydantic models (neither response model has a `tier` field — confirmed by reading both). **Omitting `tier` entirely is safe and already the S1-08 behavior** — the `Form(_DEFAULT_TIER, ...)` default silently applies server-side, so a caller who never sends it gets `T2`, no error.

**Tier name mapping (frontend ↔ backend) — confirmed by matching semantics, not invented:** `docs/stories/2-lm3-lm4-lm5-tier-aware-generation.md` describes T1 = full depth, T2 = standard/default (no extra prompt framing), T3 = critical-topics-only/refresher — this maps exactly onto the existing frontend tier semantics already shipped in S2-07/S2-08 (`apps/web/src/types/learnerMode.ts`): `deep` → `T1`, `balanced` → `T2`, `refresher` → `T3`. No such mapping constant exists in the frontend yet — this story adds it.

**Branch:** `sprint2/s2-09-wire-tier`, branched from `feature-learner-mode` (not `main`, not `sprint2-master`) — same convention as S2-07/S2-08, confirmed standing team rule (2026-07-21): task branches are local-only, never pushed directly; this one merges into `feature-learner-mode`, which alone gets pushed/PR'd.

### What's already there to build on (read directly from the current files, not assumed)

- `apps/web/src/types/learnerMode.ts` — `LearnerTier = 'deep' | 'balanced' | 'refresher'`, `LearnerTierOption` (`{id, label, description, disclaimer?}`), `LEARNER_TIER_OPTIONS` (ordered array, from S2-07/S2-08). No backend-tier mapping exists yet.
- `apps/web/src/components/dashboard/upload/UploadFlow.tsx` — already tracks `selectedTier: LearnerTier | null` as component state, set in `handleTierSelect(tier)` when a card is clicked (state machine: `idle → selecting-mode → processing → completed/error`). The `'processing'` screen JSX already carries `data-selected-tier={selectedTier ?? undefined}` — an explicit forward-compat hook S2-07/S2-08 left in place (see its own comment: *"not rendered as visible text — it's a forward-compatible hook for the S2-10 tier-badge story"*). **This story is the one that must make it real** by (a) actually sending the tier and (b) rendering it as visible text (AC requires visible display — the existing attribute alone does not satisfy that).
- `apps/web/src/services/upload.service.ts` — `uploadLesson(file: File)` builds `FormData` with only `'file'` appended; no tier param exists. `getLessonStatus` is untouched by this story (status response has no tier field to read).
- By the time `uploadLesson` is ever called, `selectedTier` is always non-null in practice — `UploadFlow`'s state machine only reaches `'processing'` via `handleTierSelect`, and there is no "skip Learner Mode" path today. The defensive "omit tier if unset" behavior below exists for robustness (matches the backend's own safe default), not because a live skip path exists.
- `apps/web/src/__tests__/services/upload.service.test.ts` and `apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx` both already exist and pass. `UploadFlow.test.tsx`'s one existing assertion `expect(uploadLessonMock).toHaveBeenCalledWith(expect.any(File))` (single-arg) will need updating to include the new second argument once `uploadLesson` gains a `tier` parameter — this is an intentional, expected update to match the new call signature, not a regression.

## Acceptance Criteria

1. **Tier mapping constant added** to `apps/web/src/types/learnerMode.ts`: maps `LearnerTier` (`'deep'|'balanced'|'refresher'`) → backend tier string (`'T1'|'T2'|'T3'`) per the confirmed semantics above (`deep→T1`, `balanced→T2`, `refresher→T3`).
2. **`uploadService.uploadLesson` accepts an optional backend-tier string** and appends it to the `FormData` as `'tier'` when provided; when omitted/undefined, `FormData` has no `'tier'` key at all (not an empty string) — relying on the backend's own `Form(_DEFAULT_TIER, ...)` default, not a client-side default.
3. **`UploadFlow.tsx`'s upload call site passes the mapped tier**: `uploadService.uploadLesson(file, selectedTier ? LEARNER_TIER_TO_BACKEND[selectedTier] : undefined)`.
4. **The chosen tier is visibly displayed on the `'processing'` screen** — real text the student can read (e.g. the tier's `label` from `LEARNER_TIER_OPTIONS`), not just the existing invisible `data-selected-tier` attribute. Keep that attribute in place too (harmless, and S2-10 may still reference it).
5. **No regression to the existing upload flow**: all pre-existing `UploadFlow.test.tsx`/`upload.service.test.ts` behavior (idle→selecting-mode→processing→completed/error transitions, polling, error handling, "Choose a different file" reset) is unchanged in substance — only the one call-signature assertion noted above is updated to match the new second argument.
6. **Tests:**
   - `upload.service.test.ts`: a case asserting `tier` is appended to `FormData` when passed, and a case asserting `FormData` has no `'tier'` key when the tier argument is omitted.
   - `UploadFlow.test.tsx`: a case (or parametrized set) asserting `uploadLessonMock` is called with the correct mapped backend tier for at least one non-default tier selection (e.g. selecting "Refresher" → called with `'T3'`), and a case asserting the processing screen shows the selected tier's visible label.

## Tasks / Subtasks

- [ ] Task 1: Add the tier mapping constant (AC: #1)
  - [ ] 1.1 In `apps/web/src/types/learnerMode.ts`, add `export const LEARNER_TIER_TO_BACKEND: Record<LearnerTier, 'T1' | 'T2' | 'T3'> = { deep: 'T1', balanced: 'T2', refresher: 'T3' };` — do not change `LearnerTier`, `LearnerTierOption`, or `LEARNER_TIER_OPTIONS`

- [ ] Task 2: Extend `uploadService.uploadLesson` to send tier (AC: #2)
  - [ ] 2.1 Write failing tests first (RED) in `upload.service.test.ts`: `tier` appended to FormData when passed as a second arg; `FormData.has('tier')` is `false` when the arg is omitted
  - [ ] 2.2 Implement (GREEN): `uploadLesson: (file: File, tier?: string) => { const formData = new FormData(); formData.append('file', file); if (tier) formData.append('tier', tier); return api.post<LessonUploadResponse>('content/lessons', formData).then((r) => r.data); }` — keep the existing no-explicit-Content-Type comment/behavior unchanged

- [ ] Task 3: Wire `UploadFlow.tsx`'s call site + visible tier display (AC: #3, #4)
  - [ ] 3.1 Import `LEARNER_TIER_TO_BACKEND` alongside the existing `LearnerTier` import
  - [ ] 3.2 Update the upload call in the `'processing'`-effect to `uploadService.uploadLesson(file, selectedTier ? LEARNER_TIER_TO_BACKEND[selectedTier] : undefined)`
  - [ ] 3.3 Add a small visible label on the `'processing'` screen showing the chosen tier (look up `LEARNER_TIER_OPTIONS.find(o => o.id === selectedTier)?.label`); keep the existing `data-selected-tier` attribute as-is alongside it

- [ ] Task 4: Update the existing call-signature assertion + add new tests (AC: #5, #6)
  - [ ] 4.1 Update `UploadFlow.test.tsx`'s `expect(uploadLessonMock).toHaveBeenCalledWith(expect.any(File))` to include the second arg matching whatever tier `dropFileAndSelectTier`'s default (`'Deep'`) maps to (`'T1'`)
  - [ ] 4.2 Add the two new `UploadFlow.test.tsx` cases from AC #6 (mapped tier sent for a non-default selection; visible label shown)
  - [ ] 4.3 Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean (0 new warnings)

- [ ] Task 5: Tracker update
  - [ ] 5.1 Mark S2-09 in `docs/dev2-sprint-tracker.md` as done, update the Sprint 2 dashboard row and header; note that S2-10 is now unblocked (data path exists) for re-scoping

## Dev Notes

### Files this story touches

- `apps/web/src/types/learnerMode.ts` (MODIFY — add `LEARNER_TIER_TO_BACKEND` mapping constant)
- `apps/web/src/services/upload.service.ts` (MODIFY — `uploadLesson` gains optional `tier` param)
- `apps/web/src/components/dashboard/upload/UploadFlow.tsx` (MODIFY — pass mapped tier, add visible display)
- `apps/web/src/__tests__/services/upload.service.test.ts` (MODIFY — 2 new tests)
- `apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx` (MODIFY — 1 existing assertion updated, 2 new tests)
- `docs/dev2-sprint-tracker.md` (MODIFY — mark S2-09 done on completion)

### What NOT to do

- Do NOT touch `ModeSelection.tsx`, `learnerMode.ts`'s existing fields, or the disclaimer logic from S2-08 — this story only adds the mapping constant, doesn't change tier selection UI.
- Do NOT have `upload.service.ts` import `learnerMode.ts`'s `LearnerTier` type or do the deep/balanced/refresher→T1/T2/T3 mapping itself — keep the service layer agnostic of Learner Mode's frontend vocabulary; it just accepts an already-mapped string. `UploadFlow.tsx` does the mapping since it's the one holding `selectedTier`.
- Do NOT default the tier client-side (e.g. `tier ?? 'T2'` before sending) — per AC #2, omit the field entirely when unset and let the backend's own `Form(_DEFAULT_TIER, ...)` default apply. Sending an explicit client-guessed default duplicates a decision the backend already owns.
- Do NOT attempt to read tier back from `GET /lessons/{id}` for the visible display — that endpoint doesn't return it (confirmed above); the visible label must come from the already-held `selectedTier` client state.
- Do NOT touch `getLessonStatus` or `LessonStatusResponse` — out of scope, no tier field exists there.
- Do NOT re-scope or implement S2-10 (tier badge on player/session report) as part of this story — S2-10 is a separate task, to be picked up once this one is `done`.

### Project Structure Notes

Purely additive/extending 3 existing files plus their 2 test files. No conflicts with `packages/shared` frozen contracts — `tier` here is a plain multipart form field on a non-frozen endpoint (`POST /lessons` isn't one of the 4 frozen contracts in CLAUDE.md §16), not a shared TS/schema type change.

### Testing standards

Vitest + `@testing-library/react` + `@testing-library/user-event`, `jsdom` environment. `vi.hoisted` + `vi.mock` for module-level dependencies — `upload.service.test.ts` mocks `@/lib/api`'s `post`/`get`; `UploadFlow.test.tsx` mocks `@/services/upload.service` and `next/navigation`. Match these exact existing patterns; do not introduce a new mocking approach.

### References

- [Source: docs/dev2-sprint-tracker.md#S2-09 — Wire Selected Tier into Lesson Creation] (original sketch + blocked-status note)
- [Source: docs/stories/2-8-tier-disclaimers.md, docs/stories/2-7-mode-selection-screen.md] (prior 2 Learner Mode stories in this same feature — branch convention, `selectedTier` state origin)
- [Source: apps/api/app/modules/content/router.py] (live `tier` Form field contract on `POST /lessons`)
- [Source: apps/api/app/schemas/lesson.py] (`LessonTier`/`VALID_TIERS`/`DEFAULT_TIER` — single source of truth for valid values)
- [Source: docs/stories/2-lm3-lm4-lm5-tier-aware-generation.md] (T1/T2/T3 semantics — basis for the deep/balanced/refresher mapping)
- [Source: apps/web/src/types/learnerMode.ts] (file to extend with the mapping constant)
- [Source: apps/web/src/services/upload.service.ts] (file to extend with the `tier` param)
- [Source: apps/web/src/components/dashboard/upload/UploadFlow.tsx] (call site + visible display)
- [Source: apps/web/src/__tests__/services/upload.service.test.ts, apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx] (existing tests to extend, exact mocking conventions to match)

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

### Change Log
