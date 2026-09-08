---
title: "Story 2-60 — Mode-Selection Cards: Explicit Duration Labels (BR-2)"
status: in-progress
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-60 — Mode-Selection Cards: Explicit Duration Labels (BR-2)

## Problem Statement

`ModeSelection.tsx`'s three tier cards (`/upload` flow, `LEARNER_TIER_OPTIONS`) show only a name
("Deep" / "Balanced" / "Refresher") and a prose description — nothing on the card states how long
the resulting lesson actually takes. `docs/dev2-sprint-tracker.md` §13A's BR-2 item asks for
explicit "15 min / 30 min / 45 min" labels, alongside the existing names (not replacing them —
the names carry real meaning: "Refresher" implies prior mastery, which a bare "15 min" wouldn't).

BR-2's own stated dependency — confirming the tier→minute mapping with Dev 3 — is already resolved:
Dev 3's Story F2-3 (`docs/dev3-assessment-tracker.md`, done 2026-09-04) verified and made
machine-checkable `T1=45min (Full-Depth), T2=30min (Standard), T3=15min (Refresher)`
(`_TIER_MINUTES` in `apps/api/app/modules/assessment/service.py`). The frontend's own tier ids map
to these via the already-existing `LEARNER_TIER_TO_BACKEND` (`deep→T1, balanced→T2, refresher→T3`,
`types/learnerMode.ts`) — no new backend call, no new contract, this is a pure frontend copy/data
addition using a mapping that already exists on both sides.

## Acceptance Criteria

- **AC1** — Each `LearnerTierOption` (`types/learnerMode.ts`) gains a `durationMinutes: number`
  field: `deep: 45`, `balanced: 30`, `refresher: 15` — matching `_TIER_MINUTES`/`LEARNER_TIER_TO_BACKEND`
  exactly, not re-derived or guessed independently.
- **AC2** — `ModeSelection.tsx` renders each card's duration as a distinct, visible "N min" label
  next to its existing name — never replacing the name (`option.label` stays exactly as-is, all 3
  existing name-text assertions in `ModeSelection.test.tsx` must keep passing unmodified).
- **AC3** — The duration label reads exactly `"{durationMinutes} min"` (e.g. `"45 min"`), not a
  range or approximation — these are fixed, already-confirmed values, not estimates.
- **AC4** — New tests assert each card shows its own correct duration text (Deep→"45 min",
  Balanced→"30 min", Refresher→"15 min") and that no card shows a different tier's duration.
- **AC5** — `tsc --noEmit` and targeted `eslint` clean; full frontend suite green, zero regressions.

## Scale & Load

N/A for all six questions — this is a static copy/data change on a fixed, 3-item, hand-authored
array (`LEARNER_TIER_OPTIONS`); no new query, no new network call, no variable-sized input, no
concurrency-sensitive path. The three duration values are fixed constants mirroring the backend's
own already-fixed `_TIER_MINUTES`, not computed from anything that could grow unbounded.

## Dev Notes

- Source of truth for the mapping: `apps/api/app/modules/assessment/service.py`'s `_TIER_MINUTES`
  (Story F2-3) — `{"T1": 45, "T2": 30, "T3": 15}` — combined with this frontend's own existing
  `LEARNER_TIER_TO_BACKEND` (`types/learnerMode.ts:13-17`) to get `deep→45, balanced→30, refresher→15`.
  Do not hardcode a fourth, independent copy of this mapping — the two existing ones already agree.
- `ModeSelection.tsx`'s current render: `<h4>{option.label}</h4>` then `<p>{option.description}</p>`.
  The duration badge is added next to the `<h4>`, styled as a small pill (mirrors `Player.tsx`'s
  existing tier-badge pill convention: `rounded-full`, muted background, `text-xs font-medium`) —
  a new small visual element, not a rewrite of the card's existing layout.
- Confirmed via grep: `LEARNER_TIER_OPTIONS`/`LearnerTierOption` are consumed in exactly 3 files
  (`types/learnerMode.ts`, `ModeSelection.tsx`, `ModeSelection.test.tsx`) — no other consumer to
  account for.

## Dev Agent Record

### Completion Notes

(filled in during implementation)

### File List

- `apps/web/src/types/learnerMode.ts`
- `apps/web/src/components/dashboard/upload/ModeSelection.tsx`
- `apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx`

## References

- [Source: docs/dev2-sprint-tracker.md §13A, BR-2] — the task itself, its stated dependency
- [Source: docs/dev3-assessment-tracker.md, Story F2-3] — the confirmed tier→minute mapping this
  story consumes rather than re-deriving
- [Source: apps/api/app/modules/assessment/service.py — `_TIER_MINUTES`] — backend source of truth
- [Source: apps/web/src/types/learnerMode.ts — `LEARNER_TIER_TO_BACKEND`] — existing frontend tier-id
  → backend-tier mapping this story reuses
- [Source: apps/web/src/components/player/Player.tsx — tier badge pill] — existing visual pattern
  this story's duration badge mirrors
