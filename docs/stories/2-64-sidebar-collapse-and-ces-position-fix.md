---
title: "Story 2-64 — Slide Sidebar Collapse Toggle + CES Indicator/Dashboard Link Overlap Fix (BR-9)"
status: in-progress
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-64 — Slide Sidebar Collapse Toggle + CES Indicator/Dashboard Link Overlap Fix (BR-9)

## Problem Statement

Two direct user requests, bundled into one story per explicit instruction ("fix this as well in
the same run") — same bundling precedent as BR-5's own mid-story additions.

**1. Sidebar collapse toggle.** Story S4-37 gave the lesson player a 75/25 split (image left,
notes sidebar right) when a slide has an image. The user now wants a minimizer button: click it
and the 25% notes sidebar collapses, the image panel expands to fill 100% of the width; click it
again and it restores to 75/25. This is a player-wide toggle (shared across every slide in the
segment), not a per-slide one — a student who collapses the sidebar on slide 1 does not expect it
to silently reappear on slide 2.

**2. CES indicator overlapping the Dashboard link.** Confirmed by direct code inspection:
`Player.tsx`'s Dashboard link (`absolute top-3 right-3 z-10`) and `CESIndicator.tsx`'s own root
element (`absolute top-3 right-3 z-10`) are positioned at the **exact same coordinates**. Both can
be visible simultaneously (Dashboard link shows whenever `status !== 'ENDED'`; `CESIndicator` shows
whenever `cesScore !== null && status === 'PLAYING'` — both true during normal lesson playback), so
the CES dot renders directly on top of the Dashboard button (later in DOM order → wins the paint
order at the same z-index). This is a real, reproducible bug, not a hypothetical.

## Acceptance Criteria

**Sidebar collapse (AC1–AC6):**

- **AC1** — `SlideRenderer` gains two new optional props: `isSidebarCollapsed?: boolean` and
  `onToggleSidebarCollapsed?: () => void`. Omitting them (as every pre-existing test does) renders
  exactly as before this story — zero behavior change, zero new elements — so all 46 pre-existing
  `SlideRenderer` tests pass unmodified.
- **AC2** — When `hasImage` is true and `isSidebarCollapsed` is `true`: the image panel becomes
  `w-full` (not `w-3/4`), and `slide-text-sidebar` is not rendered at all (not hidden via CSS —
  actually absent from the DOM, so it can't be tabbed into or scrolled while collapsed).
- **AC3** — When `hasImage` is true and `onToggleSidebarCollapsed` is provided, a toggle button
  (`data-testid="sidebar-collapse-toggle"`) is rendered regardless of collapsed state, positioned at
  the boundary between panel and sidebar when expanded (`right-1/4`) and flush to the right edge
  when collapsed (`right-0`) — so it's always reachable to reverse the last action. `aria-expanded`
  reflects whether the sidebar is currently shown; `aria-label` reads "Collapse slide notes panel" /
  "Expand slide notes panel" accordingly.
- **AC4** — The toggle button is never rendered at all when `hasImage` is false (the full-width,
  no-image layout has no sidebar to collapse) or when `onToggleSidebarCollapsed` is not provided.
- **AC5** — `Player.tsx` lifts `isSidebarCollapsed` as local component state (not the global
  Zustand store — this is ephemeral, session-local UI preference, not state any other part of the
  player needs to react to), defaulting to `false` (75/25, matching S4-37's shipped default), and
  passes the same state + toggle callback to **every** `SlideRenderer` instance in the segment
  (`segment.slides.map(...)`) — so the collapse state is shared across all slides, per the Problem
  Statement's stated intent, not reset per slide.
- **AC6** — Toggling is a pure CSS/layout change — no re-fetch, no re-render of `SlideImage`'s own
  `src`/`failed` state (confirmed: `SlideImage` is keyed only on `imageUrl`/`fallbackUrl`, neither
  of which changes when the sidebar collapses, so it does not remount).

**CES indicator / Dashboard link overlap fix (AC7–AC8):**

- **AC7** — `CESIndicator`'s root element moves from `top-3 right-3` to `top-12 right-3` — clears
  the Dashboard link above it (which ends well before 48px from the top) and stays clear of
  `TutorInterventionCard` below it (`top-24 right-4`, i.e. 96px — `top-12` (48px) + the indicator's
  own fixed 40px height (AC-5 of the original CES story) ends at 88px, an 8px gap before
  `TutorInterventionCard` begins).
- **AC8** — A new regression test in `CESIndicator.test.tsx` asserts the badge's `className`
  contains `top-12` and does **not** contain `top-3` — guards against a future regression back to
  the exact colliding value.

## Scale & Load

1. **Unit of work and range.** One boolean toggle per player session, applied to N `SlideRenderer`
   instances (N = slides in the current segment, already bounded — Story 4-37's own Scale & Load
   established slide count per segment is pipeline-capped). No new data fetch, no new element count
   growth.
2. **Fixed budgets vs. variable input.** None introduced — pure CSS class swap driven by one
   boolean; no new content is measured, generated, or capped.
3. **Scope of limits.** `isSidebarCollapsed` is local `useState` in `Player.tsx` — scoped to one
   mounted player instance (one student, one lesson, one browser tab). Not persisted, not shared
   across sessions or users.
4. **Unbounded reads/writes.** None — no network/DB call in either change.
5. **Inherited caps re-derived.** N/A — no cap is being reused or repurposed here.
6. **Check-then-act under concurrency.** N/A — client-only UI state, no shared mutable state, no
   concurrent-request race.

## Dev Notes

- `SlideImage`'s existing `key={slide.image_url ?? slide.fallback_image_url ?? 'none'}` is
  untouched — confirms AC6 (no remount on collapse toggle) without any new code needed to prove it.
- Reuses `FOCUS_RING` (not currently imported in `SlideRenderer.tsx`) for the new toggle button,
  matching this codebase's established a11y convention (`TeachBackModal`, `CaptionOverlay`, etc.).
- `ChevronLeft`/`ChevronRight` from `lucide-react` (already a project dependency — see
  `Player.tsx`'s own `ArrowLeft` import) for the toggle icon, flipping direction with state.
- CES/Dashboard fix is a one-line class change in `CESIndicator.tsx`; no props/behavior change, so
  `CESIndicator.test.tsx`'s existing 8 tests (none of which assert positioning classes today) pass
  unmodified.

## Dev Agent Record

### Completion Notes

_(filled in after implementation)_

### File List

- `apps/web/src/components/player/SlideRenderer.tsx`
- `apps/web/src/__tests__/components/player/SlideRenderer.test.tsx`
- `apps/web/src/components/player/Player.tsx`
- `apps/web/src/components/player/CESIndicator.tsx`
- `apps/web/src/__tests__/components/player/CESIndicator.test.tsx`

## References

- [Source: docs/stories/4-37-player-slide-75-25-layout.md] — the 75/25 split this story adds a
  toggle to
- [Source: apps/web/src/components/player/Player.tsx] — Dashboard link, CES indicator mount site
- [Source: apps/web/src/components/player/CESIndicator.tsx] — the colliding element being repositioned
