---
baseline_commit: b1dcecf696041a9dd640545a2f93e5e4d9e3a796
---

# Story 2.55: Accessibility Audit — WCAG AA (S4-04)

Status: ready-for-dev

## Story

As a student using assistive technology (screen reader, keyboard-only navigation),
I want visible focus indicators, sufficient text contrast, live-region announcements for dynamic feedback, and real keyboard navigation through quiz options,
so that I can actually use the quiz, teach-back, and tutor-intervention flows — not just see them.

**Source:** `docs/dev2-sprint-tracker.md` S4-04 ("Accessibility Audit (WCAG AA)", P1), 5 checklist items:
1. All interactive elements have visible focus states
2. All images have `alt` text
3. Color contrast ≥ 4.5:1 for body text, 3:1 for large text
4. `aria-live` regions for quiz feedback and tutor intervention cards
5. Keyboard navigation through quiz options (arrow keys + Enter)

## Current State, Confirmed By Reading The Real Code (a dedicated audit pass, not assumption)

**Tooling**: no `eslint-plugin-jsx-a11y` is configured anywhere in `apps/web` (`eslint.config.mjs` only extends `eslint-config-next`'s `core-web-vitals`/`typescript`). There is no automated a11y lint safety net — fixes here must be verified manually/by test, and a guard test is worth adding where cheap (contrast values, ARIA attributes) since nothing else will catch a regression.

**Item 2 (alt text) is already compliant — no work needed.** All `<img>`/`next/image` usages across the app already carry real alt text. Corrected during review (Acceptance Auditor / Process Integrity, both independently): the original pass here undercounted — a repo-wide grep finds **11** files, not ~9, missing `AvatarOverlay.tsx`, `Features.tsx`, and `SlideRenderer.tsx`. The full, accurate list (also the guard test's `FILES_WITH_IMAGES`): signin/signup pages, `pending-approval`, `Footer.tsx`, `Navbar.tsx`, `Sidebar.tsx`, `TopUtilityBar.tsx`'s avatar, `ProfileTab.tsx`'s Dicebear avatar, `AvatarOverlay.tsx`, `Features.tsx`, `SlideRenderer.tsx`. One of these, `AvatarOverlay.tsx`, deliberately uses `alt=""` for its decorative loading-state thumbnail — correct WCAG practice, not a violation; the guard test allowlists it explicitly rather than silently passing every empty alt.

**Item 1 (focus states) — confirmed gaps, with an existing good pattern to match:**
- **Good precedent already in the codebase**: `apps/web/src/components/ui/button.tsx:22`, the shared `<Button>` component, has `focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20`. `Sidebar.tsx` nav links (`:66,143`) have `focus-visible:ring-2`. Any component using the shared `<Button>` (e.g. `QuestionCard.tsx`'s options) already inherits this for free — confirmed, not assumed.
- **`apps/web/src/components/player/QuizOverlay.tsx`** — 3 raw `<button>` elements (option buttons ~line 133, Submit ~line 180/187, Next ~line 190) use raw `<button>`, not the shared component — **zero focus-visible styling on any of them.**
- **`apps/web/src/components/player/TutorInterventionCard.tsx`** — the dismiss button (~line 91-96) has `aria-label="Dismiss"` but **zero focus classes.**
- **`apps/web/src/components/player/TeachBackModal.tsx`** — 3 raw buttons (Continue, Skip, Submit & Continue) have **zero focus classes**; the `<textarea>` actively does `focus:outline-none` with only a 50%-opacity border-color change as a substitute — a weak indicator, not compliant.

**Item 3 (contrast) — confirmed violations, both from the identical pattern:**
- `QuizOverlay.tsx` — the option-letter prefix (`A.`, `B.`, ...) uses `text-neutral-400` on `bg-neutral-50` ≈ **2.85:1** (needs 4.5:1 for body text).
- `apps/web/src/components/onboarding/QuestionCard.tsx:43` — the identical `text-neutral-400` option-letter prefix, on `bg-white` ≈ **2.9:1**.
- Lower-confidence, NOT fixed here (no rendered/measured evidence of actual failure, per this project's own evidence-over-assumption standard): `text-neutral-500` is used widely (~30 files) and computes close to the 4.5:1 line on white — left alone rather than mass-changed on a hunch.

**Item 4 (aria-live) — confirmed gap, with an existing good pattern to match:**
- **Good precedent already in the codebase**: `apps/web/src/components/dashboard/sections/ReassessmentPrompt.tsx:70-71` uses `role="status" aria-live="polite"` — this is the pattern to replicate, not invent from scratch.
- `QuizOverlay.tsx`'s "Correct!"/"Not quite." feedback block and `TutorInterventionCard.tsx`'s intervention message (~line 90) both currently have **no live-region announcement at all** — purely visual, silent to a screen reader.

**Item 5 (keyboard navigation) — confirmed gap in BOTH quiz-option components, different severities:**
- `QuizOverlay.tsx`: plain `<button>` elements, **zero `role`, zero `tabIndex` management, zero `onKeyDown`** — no semantic grouping, no arrow-key handling.
- `apps/web/src/components/onboarding/QuestionCard.tsx`: **already has `role="radiogroup"`/`role="radio"`/`aria-checked`** (lines 25, 33-34) but **no arrow-key handling at all**. Per the WAI-ARIA Authoring Practices radiogroup pattern, this is worse than having no roles: a screen reader announces "radio button, 1 of 4" and the user reasonably expects arrow keys to move selection, but only Tab/Enter/Space work (native button behavior) — **a real, pre-existing accessibility bug in already-shipped code**, not something introduced by this story. Treated here as a bug to fix, not a finished pattern to blindly copy into `QuizOverlay.tsx`.

## Acceptance Criteria

1. **AC-1 (focus states)** — Every interactive element in `QuizOverlay.tsx`, `TutorInterventionCard.tsx`, and `TeachBackModal.tsx` has a visible `focus-visible` indicator, matching the shared `<Button>` component's existing treatment (`focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20` or equivalent). `TeachBackModal.tsx`'s textarea gets a real focus ring, not just a border-opacity change.
2. **AC-2 (alt text)** — No code change; a guard test (or documented manual confirmation) records that all `<img>`/`<Image>` usages already have non-empty `alt` text, so a future regression is at least visible even without a full a11y linter.
3. **AC-3 (contrast)** — `QuizOverlay.tsx` and `QuestionCard.tsx`'s option-letter-prefix `text-neutral-400` is changed to a color meeting ≥4.5:1 against its actual background (e.g. `text-neutral-600`, verified ≥4.5:1 by calculation, not assumption). No other color is changed without similar confirmed-failing evidence — this story fixes confirmed violations, not every borderline color.
4. **AC-4 (aria-live)** — `QuizOverlay.tsx`'s correct/incorrect feedback and `TutorInterventionCard.tsx`'s intervention message both get `role="status" aria-live="polite"`, matching `ReassessmentPrompt.tsx`'s existing pattern exactly.
5. **AC-5 (keyboard navigation)** — Both `QuizOverlay.tsx` and `QuestionCard.tsx` get real arrow-key navigation (Up/Left = previous option, Down/Right = next option, wrapping at the ends) via a shared `useRovingRadioGroup` hook, implementing the standard "selection follows focus" radiogroup pattern (arrow keys move focus AND change the selected option together, matching native `<input type="radio">` group behavior) with roving `tabIndex` (only the selected/first option is a Tab stop). Enter/Space submission already works for free via native `<button>` semantics — not re-implemented. Disabled once a quiz question is submitted (`QuizOverlay.tsx`'s existing `submitted` state), matching the existing click-based disable behavior.
6. **AC-6 (tests)** — Focus-visible classes present (a class-list assertion, since JSDOM can't render real focus rings); contrast values calculated and asserted in a unit test (not just eyeballed); `aria-live`/`role="status"` present on both target elements; keyboard navigation tested end-to-end (ArrowDown/ArrowUp/ArrowRight/ArrowLeft move selection and focus, wrapping at both ends, disabled after submission).

## Scale & Load

Answering the six questions (`docs/SCALE-CONTRACT.md`):

1. **Unit of work and range:** N/A — this is static UI markup/styling and a small shared keyboard-handling hook, not a data-scale-sensitive operation. No input size varies here.
2. **Fixed budgets vs. variable input:** N/A — no budget introduced.
3. **Scope of every limit:** N/A — no limit introduced.
4. **Unbounded reads/writes:** N/A — no reads/writes introduced; this is entirely client-side rendering/interaction logic.
5. **Inherited caps re-derived:** N/A — nothing inherited.
6. **Concurrent check-then-act safety:** N/A — no shared/concurrent state; the roving-tabindex hook's state is local to one rendered component instance.

(All six are genuine N/A for a pure frontend styling/accessibility story with no data scale dimension — stated explicitly per the Scale Contract's own rule that a bare "N/A" needs a reason, not just the label.)

## Tasks / Subtasks

- [ ] Task 1 (AC: 1): focus-visible classes on `QuizOverlay.tsx` (3 buttons), `TutorInterventionCard.tsx` (dismiss button), `TeachBackModal.tsx` (3 buttons + textarea).
- [ ] Task 2 (AC: 2): guard test confirming all `<img>`/`<Image>` usages have non-empty `alt`.
- [ ] Task 3 (AC: 3): contrast fix in `QuizOverlay.tsx` and `QuestionCard.tsx`, with a calculated-contrast unit test.
- [ ] Task 4 (AC: 4): `aria-live`/`role="status"` on `QuizOverlay.tsx`'s feedback and `TutorInterventionCard.tsx`'s message.
- [ ] Task 5 (AC: 5, 6): `useRovingRadioGroup` shared hook; wired into `QuizOverlay.tsx` and `QuestionCard.tsx`; full keyboard-nav test coverage for both.
- [ ] Task 6: full `apps/web` suite + lint + typecheck green.

## Dev Notes

### What NOT to do

- Do NOT mass-change every `text-neutral-500` usage on a hunch — only the two confirmed-failing `text-neutral-400` sites are in scope (AC-3).
- Do NOT re-implement Enter/Space selection — native `<button>` semantics already provide this; only arrow-key movement is missing.
- Do NOT copy `QuestionCard.tsx`'s existing ARIA roles into `QuizOverlay.tsx` as-is without also adding the keyboard handling — that would reproduce the exact "roles without behavior" bug this story is fixing in `QuestionCard.tsx` itself.
- Do NOT add a new eslint a11y plugin as part of this story — that's a larger, separate tooling decision; this story fixes the confirmed gaps directly.

### Testing standards

Vitest + Testing Library, matching this repo's existing `apps/web/src/__tests__/` conventions. Contrast ratios are computed in a small pure-function test (WCAG relative-luminance formula), not eyeballed. Keyboard tests use `userEvent.keyboard()` / `fireEvent.keyDown`.

### References

- [Source: docs/dev2-sprint-tracker.md, S4-04] — origin of this task.
- [Source: apps/web/src/components/ui/button.tsx:22] — the focus-visible pattern to replicate.
- [Source: apps/web/src/components/dashboard/sections/ReassessmentPrompt.tsx:69-71] — the `aria-live` pattern to replicate.
- [Source: apps/web/src/components/onboarding/QuestionCard.tsx] — the half-built ARIA-radiogroup pattern this story completes (arrow-key handling), not a finished reference.

## Dev Agent Record

### Implementation Plan

1. `useRovingRadioGroup` shared hook (`apps/web/src/hooks/useRovingRadioGroup.ts`) — roving tabindex + arrow-key "selection follows focus" logic, used by both `QuizOverlay.tsx` and `QuestionCard.tsx`.
2. `apps/web/src/lib/a11y/contrast.ts` — pure WCAG relative-luminance/contrast-ratio functions, used only by the AC-3 guard test (not by the UI at runtime — the actual fix is a static Tailwind class change).
3. `QuizOverlay.tsx` — `role="radiogroup"`/`role="radio"`/`aria-checked` + roving tabIndex + `onKeyDown` on options; `focus-visible` ring on options, Submit, Next; `role="status" aria-live="polite"` on the correct/incorrect feedback block; `text-neutral-400` → `text-neutral-600` on the option-letter prefix AND on the post-submit dimmed-option state (a second confirmed instance of the same violation, found during implementation — not in the original story audit; same color, same failing ratio, in scope of the same fix).
4. `TutorInterventionCard.tsx` — `role="status" aria-live="polite"` on the card; `focus-visible` ring on the dismiss button.
5. `TeachBackModal.tsx` — `focus-visible` ring on Skip, Submit & Continue, and the result-view Continue button; textarea's weak `focus:border-opacity` swapped for a real `focus:ring-4`.
6. `QuestionCard.tsx` — wired the same roving-tabindex hook onto its already-present `role="radio"` options (completing the pre-existing partial ARIA implementation); `text-neutral-400` → `text-neutral-600`. No focus-ring change needed — inherited from the shared `<Button>` component already.

### Completion Notes

- All 6 ACs implemented as scoped. AC-2 required no code change — added a guard test (`__tests__/a11y/altText.test.ts`) enumerating every file with an `<img>`/`<Image>` usage found at audit time and asserting each tag carries non-empty `alt=` (with an explicit, named exception for `AvatarOverlay.tsx`'s decorative `alt=""`).
- Found one additional confirmed `text-neutral-400` contrast violation beyond the two named in the story (`QuizOverlay.tsx`'s post-submit dimmed-option text, same color/background class as the option-letter prefix) — fixed alongside the two originally scoped instances since it's the identical violation, not a new judgment call.
- `useRovingRadioGroup` implements "selection follows focus": arrow keys move focus and change the selected option together (matches native `<input type="radio">` group behavior per WAI-ARIA APG). Wrapping at both ends. Disabled once `QuizOverlay`'s question is `submitted`.
- Full `apps/web` suite: 88 test files, 1059 tests passed (was 1048 pre-story; +11 new test files' worth of assertions across new and modified specs). Lint: 0 errors/warnings. Typecheck: clean. Production build (`next build`): succeeds.

### Senior Developer Review (AI) — 8-layer adversarial round

Ran Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter, Story Quality, Test Coverage, AC Completeness, and Process Integrity in parallel against the implementation diff. All findings below were fixed in this same branch before merge; none were deferred silently.

| # | Finding | Layer(s) | Resolution |
|---|---------|----------|------------|
| 1 | `TutorInterventionCard`'s live region was on the same node that remounts (`key={renderKey}`) per intervention — a fresh node with pre-populated content, which some screen reader/browser combinations never announce (only content *mutations* on an already-present node reliably fire). | Edge Case Hunter, Scale & Load Hunter | Split into two elements: a permanently-mounted, visually-hidden (`sr-only`) `role="status" aria-live="polite"` announcer whose text content changes, plus the existing visual toast (unchanged remount-per-intervention behavior, kept for its enter animation/variant styling, no longer duplicating the live-region role). |
| 2 | `QuizOverlay`'s feedback `role="status"` div was conditionally *rendered* (`{submitted && (...)}`), i.e. unmounted/remounted on every submit — same category of issue as #1. | Scale & Load Hunter (one-line-test) | Div is now always mounted; only its content and visual classes toggle (`sr-only` when not submitted). |
| 3 | `QuestionCard.test.tsx`'s roving-tabindex test called `render()` a second time instead of using the first render's `rerender()` — RTL doesn't auto-cleanup between calls in the same test, so 8 stale+fresh radio buttons existed and the assertion trivially passed against the *first* render's untouched `option[0]`, regardless of whether `selectedIndex` was wired correctly. | Test Coverage, Edge Case Hunter (independently, both flagged the same bug) | Fixed to use `rerender()`; assertions tightened to check the exact expected index, not `.some(...)`. |
| 4 | `QuestionCard`'s arrow-key tests asserted only the `onSelect` mock's call argument, never `document.activeElement` — would still pass if `.focus()` were deleted from the hook entirely. Also missing ArrowLeft/ArrowRight and non-wrapping-case coverage (present for `QuizOverlay`, absent for `QuestionCard`). | Test Coverage, AC Completeness | Added `document.activeElement` assertions to all 4 arrow-key tests plus new ArrowLeft/ArrowRight (non-wrapping) tests. |
| 5 | No test asserted the *actual rendered* `text-neutral-600` className on `QuizOverlay`/`QuestionCard`'s option-letter spans or `QuizOverlay`'s post-submit dimmed text — `contrast.test.ts` only validated the WCAG math against hardcoded hex literals, disconnected from the components; a revert to `text-neutral-400` would have stayed green. | AC Completeness, Test Coverage | Added direct `className` assertions against the real rendered elements in both `QuizOverlay.test.tsx` and `QuestionCard.test.tsx`. |
| 6 | Alt-text guard only checked `alt=` presence, not a non-empty value, and `\balt=` could false-match a decoy like `data-alt=`. Also: the story's own "Current State" audit undercounted image usages (~9 named vs. 11 actual). | Acceptance Auditor, Test Coverage, Process Integrity | Guard rewritten to extract and assert the actual value is non-empty (with a named, documented exception for `AvatarOverlay.tsx`'s legitimate decorative `alt=""`), and to require whitespace immediately before `alt` so `data-alt=` can't satisfy it. Story's "Current State" section corrected to the real 11-file list. |
| 7 | `FOCUS_RING` was defined identically in 3 separate files instead of shared. | Process Integrity | Extracted to `apps/web/src/lib/a11y/focusRing.ts`, imported by all 3. |
| 8 | Story frontmatter `baseline_commit` was a fabricated/padded hash (only the first 7 chars were real). | Process Integrity | Corrected to the real full hash (`git rev-parse`). |
| 9 | `docs/dev2-sprint-tracker.md`'s S4-04 entry and dashboard were never updated to reflect completion. | Process Integrity | Updated in the same commit as this story's completion (see that file's own Change Log). |

**Findings reviewed and explicitly NOT changed, with reasoning:**
- **Shared `Button` component's `disabled={isLoading || props.disabled}` followed by `{...props}` silently lets a spread `disabled` override the computed value** (Edge Case Hunter, latent). Not triggered by anything in this diff — `QuestionCard` never passes both `isLoading` and `disabled` to `Button`. Fixing a shared, app-wide component opportunistically inside an accessibility story risks a blast radius far beyond this story's scope; left as a discovered-but-out-of-scope issue for a dedicated fix.
- **`altText.test.ts` and `contrast.test.ts` provide no ongoing enforcement against a *future* new image/color-token regression elsewhere in the codebase** (Scale & Load Hunter). This is an accepted, explicitly-stated limitation of the guard-test approach — the story's own "What NOT to do" explicitly rules out adding a new `eslint-plugin-jsx-a11y` dependency in this story. Documented here rather than silently accepted.
- **`useRovingRadioGroup`'s rapid-keydown/concurrency behavior**: independently traced by Scale & Load Hunter — the hook's `idx` comes from stable DOM position (the `.map()` index), not from `selectedIndex` state, so a second keydown before React commits the first one's re-render still targets the correct button and self-corrects. No race found; no change needed.

### File List

- `apps/web/src/hooks/useRovingRadioGroup.ts` (new)
- `apps/web/src/lib/a11y/contrast.ts` (new)
- `apps/web/src/lib/a11y/focusRing.ts` (new, review fix — shared `FOCUS_RING` constant)
- `apps/web/src/components/player/QuizOverlay.tsx` (modified)
- `apps/web/src/components/player/TutorInterventionCard.tsx` (modified)
- `apps/web/src/components/player/TeachBackModal.tsx` (modified)
- `apps/web/src/components/onboarding/QuestionCard.tsx` (modified)
- `apps/web/src/__tests__/a11y/altText.test.ts` (new)
- `apps/web/src/__tests__/lib/a11y/contrast.test.ts` (new)
- `apps/web/src/__tests__/components/player/QuizOverlay.test.tsx` (modified)
- `apps/web/src/__tests__/components/player/TutorInterventionCard.test.tsx` (modified)
- `apps/web/src/__tests__/components/player/TeachBackModal.test.tsx` (modified)
- `apps/web/src/__tests__/components/onboarding/QuestionCard.test.tsx` (modified)
- `docs/dev2-sprint-tracker.md` (modified — S4-04 marked done)

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-27 | Story created after a dedicated read-only accessibility audit against all 5 tracker checklist items (not assumption) — confirmed item 2 (alt text) is already compliant, confirmed real focus/contrast/aria-live/keyboard gaps in `QuizOverlay.tsx`/`TutorInterventionCard.tsx`/`TeachBackModal.tsx`, and found a pre-existing bug in already-shipped `QuestionCard.tsx` (ARIA radiogroup roles present with no arrow-key behavior to back them). Branch `sprint4/s4-04-accessibility-audit` off `sprint4-master`. | Dev 2 |
| 2026-08-29 | Implementation complete: all 6 ACs, shared `useRovingRadioGroup` hook, `lib/a11y/contrast.ts`, full test coverage. Full suite/lint/typecheck/build green. Found and fixed one additional confirmed contrast violation beyond the two named in the original audit. | Dev 2 |
| 2026-08-29 | 8-agent adversarial review round: fixed a genuine aria-live remount reliability gap (2 components), a false-positive test bug (stray `render()` vs `rerender()`, confirmed by 2 independent layers), missing focus/keyboard-nav/contrast assertions, an alt-text guard that didn't check non-empty values, a triplicated `FOCUS_RING` constant, a fabricated `baseline_commit` hash, and an undercounted alt-text audit claim. Updated `docs/dev2-sprint-tracker.md`. | Dev 2 |
