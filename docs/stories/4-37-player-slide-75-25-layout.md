---
story_id: "4-37"
title: "Player Slide 75/25 Horizontal Split Layout"
status: "in-progress"
baseline_commit: ""
---

# Story S4-37 — Player Slide 75/25 Horizontal Split Layout

## Story

**As a** student watching a lesson,  
**I want** the slide image to fill the majority of the player screen  
**so that** infographic content is fully readable and the lesson experience matches the manager's design intent.

## Context

The lesson player currently renders slides in a vertical stack (image → title → bullets) inside a single scrollable container. The image is constrained to `max-h-[38vh]`, which makes it too small for information-dense infographic slides. The manager wants the image to fill the entire area above the captions/controls bar.

The slide images are infographics — information-dense diagrams with their own internal labels. Text overlay (Option A) was rejected because it would obscure diagram content. The approved solution is a **75/25 horizontal split**: image occupies the left 75%, text sidebar (title + bullets) occupies the right 25%.

Files to change:
- `apps/web/src/components/player/SlideRenderer.tsx`
- `apps/web/src/__tests__/components/player/SlideRenderer.test.tsx`

## Acceptance Criteria

**AC1 — 75/25 split when image present:**  
When a slide has `image_url` or `fallback_image_url`, `SlideRenderer` renders a flex-row container where the image panel takes `w-3/4` and the text sidebar takes `w-1/4`.

**AC2 — Full-width layout when no image:**  
When both `image_url` and `fallback_image_url` are `null`, `SlideRenderer` renders a single full-width scrollable content area (no split).

**AC3 — Image fills panel without cropping:**  
The image uses `object-contain` (not `object-cover`) and has no fixed height constraint (`max-h-[38vh]` removed). The image fills the 75% panel's full height using `h-full`.

**AC4 — Text sidebar is independently scrollable:**  
The right sidebar (`w-1/4`) has its own `overflow-y-auto overscroll-y-contain` so long bullet lists can scroll without affecting the image.

**AC5 — `data-lenis-prevent` preserved:**  
The `data-lenis-prevent` attribute remains on the outer container (or is applied to the scrollable sidebar) so SmoothScroll's Lenis does not intercept wheel events.

**AC6 — Opacity and aria-hidden unchanged:**  
The outer div still applies `opacity-100`/`opacity-0` and `aria-hidden` based on `isActive`, identical to current behaviour. Existing tests for these properties pass without modification.

**AC7 — SlideImage error chain unchanged:**  
The `SlideImage` component's error/fallback/re-sign chain is not altered. All existing image-handling tests pass.

**AC8 — data-testids for new panels:**  
- Image panel: `data-testid="slide-image-panel"`
- Text sidebar: `data-testid="slide-text-sidebar"`
- Full-width fallback (no image): `data-testid="slide-content-full"`

**AC9 — New layout tests pass:**  
New tests verify: (a) split layout rendered when image present, (b) full-width layout rendered when no image, (c) testids present in both cases.

**AC10 — All existing SlideRenderer tests pass without modification** (except test file additions).

## Scale & Load

1. **Unit of work and range:** One CSS layout change per `SlideRenderer` mount. No LLM, DB, API, or network calls. Range: fixed, O(1).
2. **Fixed budgets vs variable input:** No budgets involved — pure CSS layout. No token window, no DB rows, no cost ceiling interaction.
3. **Scope of every limit:** N/A — client-side only, per-component.
4. **Unbounded reads/writes:** None. No DB queries.
5. **Inherited caps re-derived:** The `max-h-[38vh]` constraint was sized for the old vertical layout — it is explicitly removed by this story.
6. **Check-then-act concurrency:** N/A — pure render function, no shared state.

## Tasks

- [ ] T1 — Story-first commit: commit this story file alone, push to remote
- [ ] T2 — Update `SlideImage` component:
  - Remove `max-h-[38vh]` from `img` className → use `w-full h-full object-contain block`
  - Remove `aspect-video rounded-xl` from placeholder → use `w-full h-full bg-neutral-100 flex items-center justify-center`
- [ ] T3 — Update `SlideRenderer` layout:
  - Outer div: `absolute inset-0 flex transition-opacity duration-150` + isActive classes (remove `overflow-y-auto overscroll-y-contain p-6`)
  - When `hasImage` (image_url or fallback_image_url non-null):
    - Left panel `data-testid="slide-image-panel"` className `w-3/4 h-full overflow-hidden`
    - Right sidebar `data-testid="slide-text-sidebar"` className `w-1/4 h-full overflow-y-auto overscroll-y-contain p-5 border-l border-neutral-100` with `data-lenis-prevent`
  - When `!hasImage`:
    - Single div `data-testid="slide-content-full"` className `flex-1 h-full overflow-y-auto overscroll-y-contain p-6` with `data-lenis-prevent`
  - Title and bullets move into the right sidebar (or full-width div when no image)
- [ ] T4 — Add new tests to `SlideRenderer.test.tsx`:
  - 75/25 split renders when image present (check `slide-image-panel` and `slide-text-sidebar` testids)
  - Full-width layout renders when no image (check `slide-content-full` testid, absence of panel/sidebar)
  - Image panel does NOT have `overflow-y-auto` (image never scrolls)
  - Text sidebar has `overflow-y-auto` class (sidebar scrolls independently)
- [ ] T5 — Run full test suite: `cd apps/web && npx vitest run --reporter=verbose`
- [ ] T6 — Verify existing isActive/opacity/aria-hidden tests still pass
- [ ] T7 — 6-layer BMAD code review via `/bmad-code-review`

## Dev Notes

### Current state of SlideRenderer.tsx

**SlideImage img** (line 80):
```
className="w-full max-h-[38vh] object-contain rounded-xl mx-auto block"
```

**SlideImage placeholder** (line 35):
```
className="w-full aspect-video rounded-xl bg-neutral-100 flex items-center justify-center"
```

**SlideRenderer outer div** (lines 109-113):
```tsx
className={[
  'absolute inset-0 overflow-y-auto overscroll-y-contain p-6 transition-opacity duration-150',
  isActive ? 'opacity-100' : 'opacity-0 pointer-events-none',
].join(' ')}
```

### Target state

```tsx
// SlideImage img:
className="w-full h-full object-contain block"

// SlideImage placeholder:
className="w-full h-full bg-neutral-100 flex items-center justify-center"

// SlideRenderer outer div:
className={[
  'absolute inset-0 flex transition-opacity duration-150',
  isActive ? 'opacity-100' : 'opacity-0 pointer-events-none',
].join(' ')}

// Image branch (hasImage = true):
<div data-testid="slide-image-panel" className="w-3/4 h-full overflow-hidden">
  <SlideImage ... />
</div>
<div data-testid="slide-text-sidebar" data-lenis-prevent className="w-1/4 h-full overflow-y-auto overscroll-y-contain p-5 border-l border-neutral-100">
  <h3>...</h3>
  <ul>...</ul>
</div>

// No-image branch (hasImage = false):
<div data-testid="slide-content-full" data-lenis-prevent className="flex-1 h-full overflow-y-auto overscroll-y-contain p-6">
  <h3>...</h3>
  <ul>...</ul>
</div>
```

### Why `data-lenis-prevent` moves to sidebar

The outer div no longer has `overflow-y-auto` — only the sidebar (or full-width div) scrolls. `data-lenis-prevent` must be on the element with `overflow-y-auto` for Lenis to know to delegate wheel events to it.

### Existing tests that must still pass (do not modify)

- All `SlideRenderer — isActive / visibility` tests check `container.firstElementChild.className` for `opacity-100`/`opacity-0`/`pointer-events-none`/`aria-hidden`. These pass because the outer div class structure is preserved.
- All `SlideRenderer — image handling` tests check `data-testid="slide-image"` and `data-testid="slide-image-placeholder"`. These pass because `SlideImage` internals are unchanged.
- `SlideRenderer — content` and `SlideRenderer — JargonHover integration` tests check text/role presence — these pass because h3/ul/JargonHover still render.

## Dev Agent Record

### File List
- `apps/web/src/components/player/SlideRenderer.tsx`
- `apps/web/src/__tests__/components/player/SlideRenderer.test.tsx`

### Change Log
<!-- populated during implementation -->

### Completion Notes
<!-- populated on completion -->
