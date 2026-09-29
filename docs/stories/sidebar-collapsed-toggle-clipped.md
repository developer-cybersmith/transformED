# Story: Sidebar's collapsed-state expand toggle is invisible (clipped by overflow-hidden)

**Discovered:** 2026-09-25, direct user report immediately after PR #251's sidebar
collapse/expand feature merged to `main`: "when the sidebar is collapsed, the arrow to
expand is not properly visible."

## Problem

`Sidebar.tsx`'s collapse toggle, when `isCollapsed`, was positioned
`absolute -right-3 top-11` — deliberately pushed 12px outside the sidebar's own right
edge, as a floating circular button peeking past the collapsed rail. The `<aside>` element
itself carries `overflow-hidden` (needed for the rounded-corner card look and the gradient
overlay pseudo-element). Positioning a child outside its nearest `overflow-hidden` ancestor's
bounds clips it — the button was rendered, but invisible (or only a sliver visible,
browser-dependent), with no way to click it to expand again short of clearing
`localStorage` or a hard reload landing on the always-expanded SSR-first-paint frame.

## Fix

The collapsed-state Logo Area now stacks the logo and the toggle button vertically
(`flex-col items-center gap-3`) instead of trying to fit them side-by-side in the ~40px of
content width left after padding on the 80px (`w-20`) collapsed rail. The toggle button no
longer uses `absolute` positioning or a negative offset in either state — it stays fully
in-flow, inside the sidebar's own clipped bounds, in both the expanded and collapsed layouts.

## Acceptance Criteria

1. **AC1**: The expand toggle is reachable and clickable when the sidebar is collapsed —
   not clipped by the `<aside>`'s `overflow-hidden`.
2. **AC2**: A regression guard test asserts the toggle button never carries `absolute`
   positioning with a negative offset class, which is the structural signature of the actual
   bug (jsdom does not compute real layout/clipping, so a class-level assertion is the
   meaningful guard here, not a visual/pixel one).
3. **AC3**: Existing Sidebar tests (main nav, account menu, collapse/expand behavior,
   localStorage persistence, accessible-name coverage) all still pass unchanged.

## Scale & Load

N/A — pure client-side CSS/layout fix, no new data, no new I/O, no new budget or limit of
any kind. The six questions do not apply to a positioning bug in already-rendered markup.

## Bundled in the same PR (unrelated file, explicit scope note)

Two follow-ups from independent review of PR #254 (`feature/249-context-wiring`, merged same
day), bundled here at the user's direction rather than as separate PRs:

1. **D189 renumbered to D192.** This story originally registered D189; PR #254 independently
   claimed D189 (and D190/D191) for unrelated context-wiring defects and merged first. Both
   branches auto-merged cleanly with no textual conflict (different sections of
   `docs/DEFECT-REGISTER.md`), which would have left two silently different "D189" entries on
   `main` — exactly the D166/168/169/170/173 collision class already on record. Renumbered
   ours to D192 (next free number after PR #254's merge) rather than let the collision reach
   `main`.
2. **Fixed a dead-code bug found in the same review**: `narration_generator_node`'s
   `chapter_context_truncated`/`book_context_truncated` log-dedup suppression
   (`if ... and not state.get(...)`) could never actually suppress anything —
   `_FAN_OUT_STATE_KEYS` (the tuple controlling what the Send()-dispatched node's own `state`
   payload carries) didn't include either flag, so `state.get(...)` inside the dispatched node
   was always falsy regardless of what `lesson_planner_node` had already set. Every dispatched
   section logged the "context truncated" warning instead of zero (the parent node already
   logged the one that matters). Added both keys to `_FAN_OUT_STATE_KEYS`, with two new tests
   in `test_249_context_wiring.py` proving the suppression fires when the flag is present
   (fixed shape) and does not when absent (the exact pre-fix regression case).
