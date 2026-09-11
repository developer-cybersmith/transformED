---
story_id: "4-37"
title: "Player Slide 75/25 Horizontal Split Layout"
status: "done"
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
- [x] T7 — 6-layer BMAD code review via `/bmad-code-review`

### Review Findings

- [x] [Review][Patch] AC3 test gap: Add test asserting `slide-image` className contains `h-full` and does NOT contain `max-h-[38vh]` [apps/web/src/__tests__/components/player/SlideRenderer.test.tsx]
- [x] [Review][Patch] AC5 test gap: Add tests asserting `getAttribute('data-lenis-prevent')` is non-null on `slide-text-sidebar` (image branch) and `slide-content-full` (no-image branch) [apps/web/src/__tests__/components/player/SlideRenderer.test.tsx]
- [x] [Review][Patch] AC1 partial: Add assertions for `w-3/4` on `slide-image-panel`, `w-1/4` on `slide-text-sidebar`, and `flex` class on outer container [apps/web/src/__tests__/components/player/SlideRenderer.test.tsx]
- [x] [Review][Patch] AC4 partial: Add assertion that `slide-text-sidebar.className` contains `overscroll-y-contain` [apps/web/src/__tests__/components/player/SlideRenderer.test.tsx]
- [x] [Review][Patch] A11y: Add `aria-label="Slide illustration"` to `slide-image-panel` and `aria-label="Slide content"` to `slide-text-sidebar` [apps/web/src/components/player/SlideRenderer.tsx:117-143]
- [x] [Review][Defer] No URL scheme validation on `img src` [apps/web/src/components/player/SlideRenderer.tsx] — deferred, pre-existing in SlideImage; not introduced by this diff

## Review Findings (independent second review, 2026-09-11)

_8-layer BMAD code review by Dev 2 (player is Dev 2's owned territory) — Blind Hunter, Edge Case
Hunter, Acceptance Auditor, Scale & Load Hunter, Story Quality, Test Coverage, AC Completeness,
Process Integrity. This is a SEPARATE pass from the dev's own prior review already recorded above —
several findings below were missed by that prior pass._

- [x] [Review][Decision] **The story's own Context section contradicts its own AC1.** The Context
      says the manager wants the image to "fill the entire area above the captions/controls bar,"
      but the "approved solution" it names — a 75/25 split — permanently reserves 25% of that area
      for text, which is not "the entire area" by any plain reading. AC1 mandates exactly `w-3/4`/
      `w-1/4`, and the code faithfully implements that ratio — this is not an implementation defect,
      it's a contradiction inside the spec itself between aspirational framing and the concrete
      number it approved. Confirmed by Acceptance Auditor. **Resolved 2026-09-11: accept 75/25
      as-is.** No code change; ship the ratio the story already approved.
- [x] [Review][Decision] **Cross-team ownership boundary crossed with zero documented
      acknowledgment.** `SlideRenderer.tsx` is Dev 2's owned territory (CLAUDE.md §21: "Next.js,
      custom player..."), but this story was implemented and tracked entirely under Dev 3's own
      tracker (`docs/dev3-assessment-tracker.md`, whose stated domain is "Quiz API · Teachback
      Scorer · CES Formula · Learner DNA · Session Reports · Analytics" — none of which is player
      UI). Confirmed independently by Story Quality and Process Integrity: no `(Cross-team)` tag, no
      "Owner: Dev 3 + Dev 2," no Dev 2 mention anywhere — despite this exact tracker using that
      convention correctly elsewhere (its own T26/T28 entries). No equivalent to CLAUDE.md's
      documented "Dev 4 Flexible Scope" exception exists for Dev 3. **Resolved 2026-09-11: this was
      Dev 2-directed work** — Dev 2 asked Dev 3 to implement this task directly, so the ownership
      boundary was crossed with real authorization, just not recorded anywhere. Not a rogue
      cross-team action. Noted for next time: tag it `(Cross-team, Dev 2-directed)` in the tracker
      entry when this happens again, matching the T26/T28 convention this tracker already has.
- [x] [Review][Decision] **Scale & Load: no upstream cap exists on bullets-per-slide or title
      length, and the new 25%-width sidebar was never sized against that real range.** Confirmed by
      Scale & Load Hunter: the pipeline enforces `_MAX_SLIDE_BULLET_CHARS=200` per bullet and
      `_MAX_SLIDES_PER_SEGMENT` (slide count per segment), but nothing bounds bullet COUNT per slide
      or title length (`graph.py` only checks the title is non-blank). A realistic slide (5-8
      bullets near 200 chars each, plus a long title) renders with zero errors into a ~270px-wide,
      heavily-wrapped, scroll-only column — silently inverting the story's own stated goal ("fully
      readable" text) with no test, warning, or visual signal. Per `docs/SCALE-CONTRACT.md` §2 this
      cannot be dismissed. **Resolved 2026-09-11: add a frontend safety net.** Implemented
      `isDenseSlideContent()` — past a combined title+bullets character threshold (400 chars), the
      sidebar switches to smaller, denser text (`text-[13px]`/`leading-snug` vs. the default
      `text-[15px]`/`leading-relaxed`, plus a smaller title) so more of the real content is visibly
      readable at once — an explicit, surfaced degradation rather than a silent one. Scoped to the
      narrow sidebar only (`hasImage` branch); the full-width no-image layout has 4x the room and
      wasn't the shape this gap was found in. Does not fix the underlying missing upstream cap — that
      remains a backend decision, out of this story's scope. **Also incidentally found, out of scope
      for this diff but worth registering**: `apps/api/tests/evals/scoring.py`'s docstring claims to
      enforce a "1-8 bullets per slide" band, but the code it describes actually checks
      slide-count-per-segment, not bullet count — the eval harness believes a cap exists that does
      not. This is a backend (`apps/api`) defect, not something fixed inside this frontend story —
      flagging for Dev 1/Dev 3 to register as its own `D-nn` entry.
- [x] [Review][Patch] `aria-label` on `slide-image-panel`/`slide-text-sidebar` is applied to plain
      `<div>`s (ARIA role `generic`), which does not support name-from-author — screen readers
      likely ignore these labels entirely, so the dev's own prior review pass's a11y fix doesn't
      actually work as intended. Needs `role="group"` (or `role="region"`) added alongside the
      existing `aria-label` for the name to be exposed. Confirmed by Blind Hunter. **Fixed**:
      `role="group"` added to both panels. [`apps/web/src/components/player/SlideRenderer.tsx`]
- [x] [Review][Patch] **`CaptionOverlay` (a sibling in `Player.tsx`, `absolute bottom-0 inset-x-0
      max-h-[30%]`, full width) has no clearance reserved in the new sidebar/full-width content
      area.** A full bullet list's last lines can render underneath the semi-opaque caption bar with
      no way to scroll clear of it. This collision already existed in principle pre-diff, but this
      diff makes it materially more likely to trigger: the same bullet text now wraps into far more
      lines in a 25%-wide column than it did at 100% width, so filling the sidebar's scrollable
      height is common, not rare. Confirmed by Edge Case Hunter (the specific check I asked it to
      run). **Fixed**: `pb-24` added to both the sidebar and the full-width content area.
      [`apps/web/src/components/player/SlideRenderer.tsx`]
- [x] [Review][Patch] **No `min-w-0` on the flex-row panels, and no `break-words`/`overflow-wrap` on
      title/bullet text.** Flex items default to `min-width: auto` (their min-content width), so a
      long unbroken token (a URL, a jargon term, a long compound word — this component renders
      `jargon`-annotated text) can force the sidebar wider than `w-1/4`, silently violating AC1's
      75/25 contract, or overflow past the nearest clipping ancestor with no scrollbar to recover
      it. Didn't exist in the old block layout (block elements always wrap to the container edge) —
      introduced specifically by the new flex-row structure. Confirmed independently by Blind Hunter
      and Edge Case Hunter. **Fixed**: `min-w-0` added to both flex panels, `min-w-0 break-words`
      added to the bullet text span. [`apps/web/src/components/player/SlideRenderer.tsx`]
- [x] [Review][Patch] AC3's `object-contain` (not `object-cover`) sub-clause has zero test coverage
      — a regression back to `object-cover` (the exact defect this story fixes, previously causing
      image cropping) would not be caught by any existing test. Confirmed by AC Completeness.
      **Fixed**: new regression test added.
      [`apps/web/src/__tests__/components/player/SlideRenderer.test.tsx`]
- [x] [Review][Patch] Missing test: fallback-only image (`image_url: null`, `fallback_image_url`
      set) — the `??` "or" branch AC1 explicitly describes is never exercised; only both-set and
      both-null are tested. Confirmed by Test Coverage. **Fixed**: new test added.
      [`apps/web/src/__tests__/components/player/SlideRenderer.test.tsx`]
- [x] [Review][Patch] Missing test: `hasImage` true→false (or reverse) transition on re-render of an
      already-mounted `SlideRenderer` — related to a real behavior Blind Hunter separately flagged
      (the ternary swaps fragment shape, so React fully unmounts/remounts the text content on this
      transition, not just the image). No test confirms the layout actually swaps correctly rather
      than leaving stale panels. Confirmed by Test Coverage + Blind Hunter. **Fixed**: new tests
      added for both transition directions.
      [`apps/web/src/__tests__/components/player/SlideRenderer.test.tsx`]
- [x] [Review][Defer] Lost `rounded-xl` corners on the image/placeholder (cosmetic — full-bleed vs.
      rounded is a design/taste call, not a functional defect) — noted, not blocking; a one-line
      revert if the team wants rounded corners back. [Blind Hunter]
- [x] [Review][Defer] Empty `bullets` array has no dedicated test — low severity, no conditional
      logic depends on bullet count. [Test Coverage]

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

**Second-pass review + fixes (Dev 2, 2026-09-11):** an independent 8-layer `/bmad-code-review` found
3 real gaps beyond the dev's own prior review pass and 6 additional patch-worthy findings. All 3
decisions resolved with the user: 75/25 accepted as-is; the cross-team crossing confirmed as
Dev-2-directed (not unauthorized); a frontend dense-content safety net added for the missing
upstream bullet/title cap. All 6 patches applied: `role="group"` for real a11y naming,
`pb-24` caption-bar clearance on both scroll containers, `min-w-0`/`break-words` overflow
protection, and 3 new test categories (`object-contain` regression guard, fallback-only-image path,
`hasImage` transition in both directions) plus the safety net's own 4 tests. 12 new tests (34 → 46
in the file); full frontend suite 93 files / 1209 tests (was 1197), zero regressions. `tsc --noEmit`
and targeted `eslint` clean (one pre-existing, unrelated `<img>`/`next/image` warning, not
introduced by this pass).
