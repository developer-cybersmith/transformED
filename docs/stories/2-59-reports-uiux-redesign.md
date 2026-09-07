---
title: "Story 2-59 — Reports Page UI/UX Redesign (BR-8)"
status: in-progress
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-59 — Reports Page UI/UX Redesign (BR-8)

## Problem Statement

Both report pages built in Story 2-58 (`/reports`) and originally in Story 2-4 (`/reports/[sessionId]`)
use a single narrow `max-w-2xl` centered column — direct user feedback (2026-09-05, after reviewing
the live pages with real production data restored) is that this reads as a plain list/document, not
a proper report: it wastes the available page width and presents every section as one long vertical
scroll with no visual grouping. The user asked explicitly for a redesign that uses the full page
width and divides the content into distinct blocks, on both pages.

This is a pure presentation/layout change — no new data, no new endpoints, no change to what
`useSessionReports()`/`useSessionReport()` fetch or what `SessionSummary`/`SessionReport` contain.

## Acceptance Criteria

- **AC1** — `/reports` (`ReportsIndex.tsx`) widens to use the full page (comparable to the dashboard's
  own content width, not `max-w-2xl`), adds a lightweight summary block above the list (counts derived
  client-side from the already-fetched list — no new network call), and replaces the single-column
  stacked row list with a responsive card grid.
- **AC2** — `/reports/[sessionId]` (`SessionReport.tsx`) widens similarly and is reorganized into
  distinct visual blocks: a header block (title/tier/date + the overall Focus score surfaced
  prominently, not buried in the stat grid), a stats block, a two-region layout for the remaining
  content (main region: attention chart + teach-back detail; side region: Learner DNA snapshot +
  the "Study Again" action) on wide viewports, collapsing to a single column on mobile.
- **AC3** — A "← Back to Reports" link is added to `SessionReport.tsx`, linking to `/reports` — a
  real, previously-missing piece of navigation: Story 2-58 built the index page but never wired the
  detail page back to it, leaving "Back to Dashboard" (only on the error state) as the sole way out.
- **AC4** — Every existing `data-testid`, rendered text assertion, and **DOM order guarantee** already
  covered by `SessionReport.test.tsx`/`ReportsIndex.test.tsx` continues to hold exactly as before —
  in particular the chart → teach-back-detail → DNA-snapshot document-order assertions (these check
  `container.querySelectorAll('*')` index order, which follows document order regardless of which
  parent element visually groups a block via CSS Grid, so the redesign's grouping must not reorder
  these three blocks' underlying JSX emission order, only their visual grouping/width).
- **AC5** — No behavior change: same loading/error/empty states, same data shown, same links, same
  formatters (`formatCesLabel`, `formatTeachbackLabel`, `cesScoreColor`) — this story changes layout
  and visual hierarchy only.
- **AC6** — `tsc --noEmit` and full frontend suite green, zero regressions, zero new tests required
  beyond what AC3's new "Back to Reports" link needs (one small addition) since this is a pure
  presentational change to already-tested components.

## Scale & Load

Pure frontend layout/CSS change — five of six questions are genuinely N/A, stated with reason per
`docs/SCALE-CONTRACT.md`'s own rule that a bare "N/A" is a missing answer (same precedent as Story
2-56's own Scale & Load section for an analogous frontend-only change).

1. **Unit of work / range**: N/A — no new data fetched or processed; same `SessionSummary[]`/
   `SessionReport` payloads as before, same bounds already established (Story 2-58's `.limit(50)`).
2. **Fixed budgets vs variable input**: N/A — no new fixed budget introduced.
3. **Scope of limits**: N/A — no server-side or per-user/per-instance limit involved.
4. **Unbounded reads/writes**: none — no new Supabase read/write, no new API call of any kind.
5. **Inherited caps re-derived**: N/A — no cap inherited or changed.
6. **Check-then-act under concurrency**: N/A — no shared mutable state; a client-side rendering/
   layout change only.

## Dev Notes

- `SessionReport.test.tsx`'s own DOM-order assertions (`chartIndex < detailIndex < dnaIndex`, using
  `Array.from(container.querySelectorAll('*')).indexOf(...)`) are a document-order walk, not a
  visual-position check — nesting the chart/teach-back-detail pair inside a "main column" wrapper
  and the DNA snapshot inside a "side column" wrapper preserves the required order as long as the
  main-column wrapper's JSX precedes the side-column wrapper's JSX (verified against the actual test
  file before implementing, not assumed).
- `session-report-root`'s existing `px-4 sm:px-8 lg:px-12` gutter classes (asserted by
  `SessionReport.test.tsx`'s own mobile-gutter test, Story 2-49/S3-08) must remain on whichever
  element carries that testid.
- `ReportsIndex.test.tsx`'s `session-card-{id}` testid must stay on the actual `<Link>` element
  (the test reads `.getAttribute('href')` directly off it), not a wrapping `<div>`.
- Icon language: reuses the existing `lucide-react` + colored-icon-box pattern already established
  in `LearningPulse.tsx` (dashboard) rather than introducing a new visual convention.

## References

- [Source: apps/web/src/components/reports/ReportsIndex.tsx] — current single-column implementation
- [Source: apps/web/src/components/reports/SessionReport.tsx] — current single-column implementation
- [Source: apps/web/src/__tests__/components/reports/SessionReport.test.tsx] — DOM-order and gutter
  assertions this redesign must preserve
- [Source: apps/web/src/__tests__/components/reports/ReportsIndex.test.tsx] — testid/content
  assertions this redesign must preserve
- [Source: apps/web/src/components/dashboard/sections/LearningPulse.tsx] — icon-box visual pattern
  reused here
- [Source: docs/stories/2-58-reports-index-page.md] — the story this one redesigns the output of
