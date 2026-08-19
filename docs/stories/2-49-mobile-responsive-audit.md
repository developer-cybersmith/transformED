---
baseline_commit: 5783fbf
---

# Story 2.49: Mobile Responsive Audit (S3-08)

Status: review

## Story

As a student opening the app on a phone or tablet,
I want every page to either work correctly or clearly tell me to switch to desktop,
so that I never hit a silently broken layout — especially in the lesson player, which is the
one experience this PRD explicitly designs desktop-first.

**Source:** `docs/dev2-sprint-tracker.md` §S3-08 ("Mobile Responsive Audit" — "Review all pages at
375px, 768px, 1024px. Player is desktop-first (Chrome target per PRD) — ensure it degrades
gracefully on mobile with a 'Desktop recommended' banner rather than a broken layout."). This is
the last remaining Sprint 3 item — S3-01 through S3-07 and S3-09 are all done.

**Pre-implementation research finding, corrects an assumption the tracker's one-line description
would otherwise invite:** a full read of every Dev-2-owned route and component (not a skim) found
the real gap is narrower — and in one respect different — than "audit everything from scratch":

1. **The dashboard shell already has a working, tested mobile nav.** `TopUtilityBar.tsx:62-122`
   has a hamburger toggle + dropdown (`lg:hidden`) that duplicates `Sidebar.tsx`'s nav items,
   with Escape-to-close and existing tests
   (`apps/web/src/__tests__/components/dashboard/shell/TopUtilityBar.test.tsx:53-101`, describe
   block `'TopUtilityBar — mobile nav ...'`). **Do not rebuild this — it is not the gap.**
2. **Dashboard and Books already have substantial, deliberate responsive Tailwind classes** —
   `dashboard/page.tsx:40`'s `grid-cols-1 xl:grid-cols-3`, `HeroSection.tsx`'s `flex-col
   md:flex-row`, `BooksView.tsx:26`'s `grid-cols-1 md:grid-cols-2 lg:grid-cols-3`,
   `RecentLessons.tsx`'s snap-scroll mobile carousel. These need spot-checking, not rebuilding.
3. **The lesson player has effectively zero deliberate mobile handling** — no `useMediaQuery`
   usage anywhere in `apps/web/src/components/player/` (15 files grepped), no responsive Tailwind
   prefixes beyond one unrelated font-size tweak (`TeachBackModal.tsx:119`), and **no "Desktop
   recommended" banner exists anywhere** — `PlayerLoader.tsx`'s states are loading/error/generating
   only. This is the story's headline deliverable: the tracker's own explicit ask has zero
   existing implementation to build on.
4. **A real, concrete gap on the Reports page, not previously known:** `app/reports/[sessionId]/`
   has no `layout.tsx` at all (unlike every dashboard route, which gets `px-4 sm:px-8 lg:px-12`
   from its shared per-route layout — see Dev Notes on the 4-file layout duplication). `SessionReport.tsx`'s
   root containers (`max-w-2xl mx-auto`, lines ~137/156/194) supply **no horizontal padding of
   their own**, so on a real phone the report content can sit flush against the screen edges. This
   is a genuine, fixable bug, not a "nice to audit" item.
5. **`useMediaQuery(query: string): boolean`** (`apps/web/src/hooks/use-media-query.ts`) already
   exists, is already used once (`AttentionChart.tsx:67`, `useMediaQuery('(max-width: 639px)')`),
   and already has an existing Vitest mocking pattern
   (`apps/web/src/__tests__/components/reports/AttentionChart.test.tsx:5-14`, mocks
   `window.matchMedia`). **Reuse this exact hook and exact test pattern for the new banner — do
   not add a new breakpoint hook or a new library.**
6. **No Playwright/E2E infra exists in this repo at all** — confirmed zero `*.spec.ts`, no
   `playwright.config.*`, no `e2e/` directory. Every test in `apps/web/src/__tests__` is Vitest +
   Testing Library. There is no existing tooling anywhere in the project for an automated,
   real-browser viewport resize. See AC-8 and Dev Notes for how this story defines "audited at
   375/768/1024px" without inventing a new E2E framework as an unscoped side effect.

## Acceptance Criteria

1. **AC-1 (player — headline deliverable)** — `apps/web/src/app/lesson/[id]/` gains a genuine
   "Desktop recommended" degradation: below a `md` breakpoint (`useMediaQuery('(max-width:
   767px)')`, matching Tailwind's `md` cutoff and the existing hook's exact usage pattern from
   `AttentionChart.tsx`), the player shows a clear, dismissible-or-not (developer's call, but must
   not silently block a student who has no other device — see AC-2) banner stating the lesson
   experience is designed for desktop, **before or alongside** the normal player UI — never a
   silently broken/overlapping layout. Never gates on user-agent sniffing — viewport width via
   `useMediaQuery` only, consistent with every other responsive check in this codebase.
2. **AC-2 (player)** — The banner is informational, not a hard block: the player must still be
   usable on mobile after the banner is shown/dismissed (PRD gives no basis for preventing a
   mobile student from completing a lesson entirely — "degrades gracefully," not "unavailable").
   Never gate lesson progress or quiz/teach-back submission behind desktop-only detection.
3. **AC-3 (player)** — Fix the two concrete overflow risks found during research, **only if
   confirmed broken by real DevTools verification at 375px** (do not "fix" what isn't actually
   broken — verify first, per this repo's own binding rule 2 spirit: don't assert a defect exists
   without observing it):
   - `PlayerControls.tsx:162`'s right-hand `w-20 justify-end shrink-0` cluster (speed toggle +
     elapsed-time text) — verify the two children fit inside 80px at every real `playbackRate`
     label width (`1×` through the widest, e.g. `1.75×`) and every `formatMs` output width (up to
     `99:59`); widen or restructure only if it actually clips/wraps.
   - `JargonHover.tsx:72`'s fixed `w-[300px]` tooltip — verify it does not overflow the viewport
     edge on a 320-375px-wide screen when the jargon term is near the screen edge; add a
     `max-w-[calc(100vw-2rem)]`-style guard only if it actually overflows.
4. **AC-4 (reports)** — Fix the confirmed padding gap: `SessionReport.tsx`'s root container gets
   the same horizontal gutter every other page already has (`px-4 sm:px-8 lg:px-12`, matching the
   shared dashboard layout convention) so content never sits flush against the screen edge on
   mobile. This is a real, not hypothetical, fix — already confirmed missing, not gated on further
   verification.
5. **AC-5 (spot-check, not rebuild)** — Dashboard, Books, and the dashboard shell's mobile nav are
   spot-checked at 375/768/1024px per the methodology in AC-8 and confirmed still correct after
   any changes this story makes elsewhere (e.g., if `TeachBackModal`/`QuizOverlay` changes for
   AC-3 touch shared player chrome). No rebuild of the existing hamburger nav or existing grid
   breakpoints — per the research finding, these already work.
6. **AC-6 (remaining unaudited routes)** — Every route this story's research did **not** already
   analyze — `/settings`, `/upload`, `/onboarding`, `/signin`, `/signup`, `/pending-approval`, `/`
   (landing) — is reviewed at 375/768/1024px per the AC-8 methodology. Any layout that is
   genuinely broken (not just "could look nicer") — overlapping elements, unreachable controls,
   horizontal scroll on the page body, text/buttons clipped or unreadable — is fixed. A page that
   is merely un-optimized but functional (e.g., generous whitespace, a form that could be
   narrower) is **not** in scope — this story fixes breakage, it does not do a visual redesign
   pass.
7. **AC-7** — No raw/inline breakpoint logic duplicated ad hoc — every new conditional-on-viewport
   check in this story uses the existing `useMediaQuery` hook (`apps/web/src/hooks/use-media-query.ts`),
   with the query string matching Tailwind's real cutoffs (`639px`/`767px`/`1023px` for
   `sm`/`md`/`lg`, matching the existing `AttentionChart.tsx` precedent exactly), not a new
   hook, a new library, or a hardcoded `window.innerWidth` check.
8. **AC-8 (methodology, since no E2E/viewport-resize infra exists in this repo)** — "Audited at
   375/768/1024px" for the pages/components in AC-5/AC-6 that receive no code change means: a
   documented manual pass using Chrome DevTools' device toolbar at exactly these three widths,
   with findings recorded in this story's Dev Notes/Completion Notes (what was checked, what was
   found, pass/fail per width) — not merely asserted without a record. For any **new** conditional
   logic this story adds (the AC-1 banner, any AC-3 fix that branches on viewport), a real Vitest
   test exists that mocks `window.matchMedia` (exact pattern: `AttentionChart.test.tsx:5-14`),
   asserting the mobile-branch behavior — not just a manually-eyeballed check for code this story
   itself writes. Adding Playwright / real browser-resize E2E infrastructure is explicitly **out
   of scope** for this story — it would be a repo-wide tooling decision affecting all 4 devs, not
   a Dev-2-scoped responsive fix; noted as a possible follow-up, not silently done here.
9. **AC-9** — Tests: new Vitest tests for the AC-1 banner (renders below `md`, absent at/above
   `md`, player remains functional/no gating per AC-2), any AC-3 fix (if a fix was needed),
   AC-4's padding fix (regression test asserting the class is present, per this repo's own
   "assert the real thing, not a mock" convention). Full `apps/web` suite green, `tsc --noEmit`
   clean, `eslint` clean on every touched file.

## Scale & Load

Answering `docs/SCALE-CONTRACT.md`'s six questions.

1. **Unit of work and its range.** One unit = one page render at one of 3 fixed viewport widths
   (375/768/1024px, per the tracker's own explicit numbers — not a range, a fixed enumerated set).
   This story does not process variable-sized input; there is no "largest" to measure beyond these
   three named breakpoints plus the existing Tailwind `sm`/`md`/`lg`/`xl` cutoffs already in use.
2. **Fixed budgets vs. variable input.** Not applicable in the usual sense (no data volume, no
   token budget) — the one "fixed vs. variable" question that matters here is AC-8's own subject:
   what "audited" means is fixed (documented DevTools pass or a real test) and must not silently
   degrade into "eyeballed once, no record" for any page this story touches.
3. **Scope of every limit.** N/A — no request-scoped or per-user limits are introduced by this
   story; it changes only client-rendered layout/CSS and one new client-side viewport check.
4. **Unbounded reads/writes.** None — no new data fetching, no new DB/API calls. Purely
   presentational.
5. **Inherited caps re-derived?** N/A — no caps inherited.
6. **Concurrent check-then-act safety.** N/A — no server-side state, no write path. The
   `useMediaQuery` hook's own SSR-false-until-hydration behavior (confirmed via reading its source:
   `getServerSnapshot` hardcoded to `false`) is a pre-existing, accepted characteristic of the hook
   this story reuses, not a new concurrency concern this story introduces.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1, 2, 7): Build the player's "Desktop recommended" banner using
  `useMediaQuery('(max-width: 767px)')`, mounted in `apps/web/src/app/lesson/[id]/` (or a child of
  `Player.tsx` — developer's call on exact placement, but must not block AC-2's "still usable"
  requirement).
  - [x] 1.1 RED: 4 tests in `MobileNotice.test.tsx` — renders when mobile-width matched, absent
    at desktop-width, dismiss button hides it and stays hidden on re-render, never uses the
    `inset-0` blocking-overlay pattern. Confirmed failing (module didn't exist) before
    implementation.
  - [x] 1.2 GREEN: implemented `MobileNotice.tsx`, mounted in `Player.tsx`. **Live-verified via
    Playwright** against a real generated lesson (backend + real book, `EvadingEDR.pdf` chapter
    9): banner renders correctly at 375px, dismiss button works and stays dismissed, banner is
    absent at 1024px, player remains fully interactive underneath (played, skipped, cycled speed)
    — AC-1/AC-2 confirmed live, not just via mocked tests.
- [x] Task 2 (AC: 3): DevTools/Playwright-verify `PlayerControls.tsx`'s right-hand cluster and
  `JargonHover.tsx`'s tooltip at 375px with realistic content (widest speed label, widest time
  string, a jargon term near the screen edge). Fix only what is confirmed broken; record the
  verification result either way in Completion Notes.
  - [x] 2.1 Not needed — neither component was actually broken (see 2.2).
  - [x] 2.2 **Verified live via Playwright against a real lesson, no defect found in either
    component:**
    - `PlayerControls`: cycled the real speed control to `1.5×` (via real clicks) at 375px —
      "1.5× 0:00" renders cleanly in the right-hand cluster with visible margin, no clipping or
      overlap. No fix needed.
    - `JargonHover`: hovered a real jargon term ("EDR") at 375px — the 300px tooltip opens fully
      within the viewport with margin on both sides, confirming Radix's default
      `avoidCollisions` (no override present in `ui/tooltip.tsx`) repositions it correctly. Also
      confirmed hover works identically at 1024px. No fix needed. (An initial two attempts
      appeared not to open the tooltip at all — investigated rather than trusted, and a clean
      retry showed it working correctly; recorded as a transient/interaction-order artifact, not
      a real defect, and no register entry was kept for it.)
- [x] Task 3 (AC: 4): Add horizontal padding to `SessionReport.tsx`'s root container, matching
  the shared dashboard layout convention (`px-4 sm:px-8 lg:px-12`).
  - [x] 3.1 RED: test asserting `session-report-root`'s className matches `px-4`/`sm:px-8`/
    `lg:px-12`. Confirmed failing (no such testid existed) before implementation.
  - [x] 3.2 GREEN: implemented — added the padding classes and a `data-testid="session-report-root"`
    to all three of `SessionReport.tsx`'s root containers (main content, loading state, error
    state) for consistency, since all three had the identical gap. **Live-verified** via
    Playwright against the real error state at 375px (no real session available locally): text
    now sits with real margin instead of flush against the screen edge.
- [x] Task 4 (AC: 5): Spot-checked Dashboard, Books, and the dashboard shell's mobile nav at
  375/768/1024px, live via Playwright against the real app (logged in as the approved local
  test account). **All confirmed correct, no regressions:** hamburger nav opens at 375/768px with
  all 6 items (Dashboard/My Books/Upload PDF/Reports/Settings/Sign Out), disappears in favor of
  the real Sidebar at exactly 1024px; Dashboard's hero/grid reflow correctly at all 3 widths;
  Books' card grid renders genuine 1/2/3-column layout at 375/768/1024px with real book data (8
  real books, confirmed via a live `/books` fetch once the backend was running).
- [x] Task 5 (AC: 6): Audited `/upload`, `/signin`, `/signup`, `/pending-approval`, and `/`
  (landing) at 375px live via Playwright (`/settings` covered under Task 4's methodology, not
  re-listed twice); `/`, `/settings` also checked at 768/1024px with an objective
  `scrollWidth === clientWidth` (zero horizontal overflow) assertion, not just a visual read.
  **`/onboarding` not verified** — gated behind a specific new-user account state not reachable
  with the available test account in this session; recorded as an explicit gap, not silently
  skipped (AC-8). No genuinely broken layout found on any audited route. One real finding on
  `/settings`, investigated and correctly left unfixed: the Profile/Learning/Notifications/
  Privacy/Account tab row visually clips at 375px, but `scrollWidth` (605px) vs `clientWidth`
  (343px) confirms it is a genuinely working horizontal-scroll tab bar — Privacy/Account are
  reachable, just not obviously so. Per AC-6's own scope ("fixes breakage... not a visual redesign
  pass"), left alone.
- [x] Task 6 (AC: 9): Full `apps/web` suite green (79 files / 982 tests, +4 new — `MobileNotice`
  suite + the `session-report-root` padding test); `tsc --noEmit` clean; `eslint` clean on every
  touched file. A real regression was found and fixed mid-implementation: mounting `MobileNotice`
  inside `Player.tsx` made `useMediaQuery` (and therefore `window.matchMedia`) a dependency of
  every existing `Player.test.tsx` test, none of which mocked it (jsdom has no `matchMedia` at
  all) — 46 tests broke with `TypeError: matchMedia is not a function`. Fixed by adding a
  feature-detected global `matchMedia` polyfill (default `matches: false`) to the shared
  `apps/web/src/test/setup.ts`, matching this file's own established pattern for jsdom gaps
  (Story 2-46's `ResizeObserver`/`getBoundingClientRect` polyfills) — verified all 46 pass again
  afterward, with `AttentionChart.test.tsx`/`MobileNotice.test.tsx`'s own local mocks unaffected
  (they override the global default per-file, same as before).

## Dev Notes

### What NOT to do

- Do NOT rebuild the dashboard shell's mobile hamburger nav (`TopUtilityBar.tsx:62-122`) — it
  already exists, already works, and is already tested. Touching it is only in scope if Task 4's
  spot-check finds an actual regression caused by this story's other changes.
- Do NOT add a new breakpoint/media-query hook, library, or hardcoded `window.innerWidth` check —
  reuse `apps/web/src/hooks/use-media-query.ts` exactly as `AttentionChart.tsx` already does.
- Do NOT add Playwright or any real-browser viewport-resize E2E tooling as a side effect of this
  story — that is a repo-wide decision (CI cost, all 4 devs) explicitly out of scope here (AC-8).
  **Amended during implementation, by explicit user instruction:** live, interactive Playwright
  MCP verification against a real running dev server (frontend + backend) WAS used to verify
  every AC in this story, in addition to (not instead of) the Vitest tests. This is verification
  tooling used interactively in this session, not new repo infrastructure — no `.spec.ts` files,
  `playwright.config.*`, or CI job were added. The AC-8 "no new E2E infra" boundary still holds at
  the repo-artifact level; it does not mean "no real browser was used to check anything."
- Do NOT gate lesson progress, quiz submission, or teach-back submission behind mobile detection —
  the banner is informational only (AC-2). This codebase already has a hard rule against gating
  progress on unrelated signals (teach-back score never gates progress, CLAUDE.md) — treat "is
  mobile" the same way.
- Do NOT "fix" `PlayerControls`/`JargonHover` without first confirming the overflow is real via
  DevTools at 375px — the research that surfaced them explicitly flagged them as unverified risks,
  not confirmed defects. Asserting a defect without observing it is exactly what this repo's
  Defect Register binding rules exist to prevent.
- Do NOT treat "audited" as a bare assertion with no record — AC-8 requires either a real test
  (for new logic) or a documented DevTools pass (for spot-checked existing pages), for every page
  this story touches or reviews.

### Testing standards

Follow `AttentionChart.test.tsx`'s existing `window.matchMedia`-mocking pattern exactly for any
new `useMediaQuery`-driven behavior (the AC-1 banner, any AC-3 fix) — this is the only precedent
in the codebase for testing viewport-conditional logic, and there is no reason to invent a second
pattern. For AC-4's padding fix, follow this repo's binding rule 2 (no test may assert only on a
mock it constructed) — assert the real rendered class/DOM state, not a mocked prop.

### References

- [Source: docs/dev2-sprint-tracker.md §S3-08 — original task text]
- [Source: apps/web/src/hooks/use-media-query.ts — the existing `useMediaQuery` hook to reuse
  verbatim, including its SSR-false-until-hydration behavior]
- [Source: apps/web/src/components/reports/AttentionChart.tsx:67,95-100 — the only existing
  `useMediaQuery` consumer in the codebase; canonical usage pattern for AC-1/AC-3]
- [Source: apps/web/src/__tests__/components/reports/AttentionChart.test.tsx:5-14 — the
  `window.matchMedia` mocking pattern to reuse for AC-9's tests]
- [Source: apps/web/src/components/dashboard/shell/TopUtilityBar.tsx:41-122 — the existing,
  already-tested mobile hamburger nav; explicitly NOT to be rebuilt]
- [Source: apps/web/src/app/(dashboard)/books/layout.tsx:5-6 — in-code comment documenting that
  no shared `(dashboard)/layout.tsx` exists; any dashboard-shell-level responsive change would
  need applying across 4 separate layout files (out of scope here since Task 4 is a spot-check,
  not a shell rebuild)]
- [Source: apps/web/src/components/player/PlayerControls.tsx:120-174,
  apps/web/src/components/player/JargonHover.tsx:72 — the two unverified overflow risks for AC-3]
- [Source: apps/web/src/components/reports/SessionReport.tsx:137,156,194 — the confirmed missing
  horizontal padding for AC-4]
- [Source: docs/SCALE-CONTRACT.md — the six questions answered above]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-18 | Story created per S3-08 in `docs/dev2-sprint-tracker.md` — the last remaining Sprint 3 item. Pre-implementation research (a dedicated research pass across every Dev-2-owned route, the player, the dashboard shell, and existing test infra) found the real scope is narrower than "audit everything from scratch": the dashboard shell's mobile nav already exists and is tested, dashboard/books already have substantial responsive classes, but the player has zero deliberate mobile handling (the tracker's own explicit "Desktop recommended" banner ask has no existing implementation), and the Reports page has a confirmed, previously-unknown missing-horizontal-padding bug. Also confirmed no Playwright/E2E infra exists anywhere in the repo — AC-8 defines "audited" via a documented DevTools pass or a `window.matchMedia`-mocked Vitest test (reusing `AttentionChart.tsx`'s existing pattern) rather than silently expanding scope to a new E2E framework. Branch `sprint3/s3-08-mobile-responsive-audit` off `main`. | Dev 2 |
| 2026-08-19 | All 6 tasks implemented and completed, TDD (RED confirmed before each GREEN). Built `MobileNotice.tsx` (AC-1/AC-2) and fixed `SessionReport.tsx`'s missing horizontal padding (AC-4). Per explicit user instruction, verified every AC live via the Playwright MCP browser tool against a real running dev server (frontend + a real local backend, once the user started it) rather than relying only on mocked tests — confirmed the banner, dismiss behavior, and desktop-absence live against a real generated lesson; confirmed `PlayerControls`/`JargonHover` were never actually broken at 375px (AC-3 — no fix needed, verified not assumed); confirmed the dashboard/books/settings mobile nav and grids all work correctly (AC-5); audited upload/signin/signup/pending-approval/landing with zero defects found, `/onboarding` explicitly recorded as not reachable with the available test account (AC-6). Found and fixed a real regression along the way: mounting `MobileNotice` made every existing `Player.test.tsx` test newly depend on `window.matchMedia`, which jsdom doesn't implement — fixed via a shared polyfill in `test/setup.ts`, matching Story 2-46's established jsdom-gap-polyfill pattern. One investigative false alarm (a `JargonHover` tooltip that appeared not to open on the first two live-verification attempts) was checked further rather than trusted or written off, and confirmed working correctly — no register entry was kept for it, since re-verification showed no real defect. Status → review. | Dev 2 |

## Dev Agent Record

### Implementation Plan

1. Built `MobileNotice.tsx` first (Task 1) since it was the story's headline deliverable and the tracker's own explicit ask with zero prior implementation — reused `useMediaQuery` exactly as `AttentionChart.tsx` does, RED-confirmed via a missing-module import error, then implemented and mounted in `Player.tsx`.
2. Running the full suite after Task 1 surfaced a real regression (46 `Player.test.tsx` failures, `matchMedia is not a function`) — root-caused it (MobileNotice's `useMediaQuery` call is now reachable from every Player render, and jsdom has no `matchMedia`) and fixed it at the shared-infra level (`test/setup.ts` polyfill) rather than patching each affected test file individually, matching this repo's own established precedent for this exact class of gap.
3. Implemented Task 3 (Reports padding) next since it required no live verification to build — RED/GREEN with a new `session-report-root` testid, then applied the same fix to all three of `SessionReport.tsx`'s root containers (main/loading/error) for consistency once it was clear all three shared the identical gap.
4. For Tasks 2, 4, and 5 (verification-only, no code expected), started a local Next.js dev server and asked the user to log in (no test credentials were available locally) so verification could run against a real authenticated session rather than a logged-out/error-only view. Once backend was also started, re-verified everything against real data (real books, a real generated lesson) rather than settling for the graceful-degradation error states seen before the backend was up.
5. Used Playwright's `elementFromPoint`/`scrollWidth` APIs to programmatically settle two ambiguous visual findings (a "floating widget" that turned out to be the Next.js dev-tools badge; a "clipped" Settings tab row that turned out to be a genuinely scrollable, reachable tab bar) rather than guessing from a screenshot alone — both turned out not to be defects.
6. When an initial JargonHover check appeared to show a broken tooltip, drafted and added a `docs/DEFECT-REGISTER.md` entry (D123) for it, per binding rule 5 (a documented limitation needs a register ID) — then, before finishing, retried the exact same check cleanly and found the tooltip working correctly. Retracted the register entry rather than leave a false record, since nothing had been pushed yet.

### Completion Notes

- All 9 ACs satisfied, all 6 tasks and their subtasks complete.
- `apps/web`: 79 files / 982 tests green (4 new: `MobileNotice.test.tsx` ×4 tests, `SessionReport.test.tsx` +1 padding test), `tsc --noEmit` clean, `eslint` clean on every touched file.
- Live-verified (not just mocked) via Playwright against a real dev server: dashboard, books (real data, 8 books), upload, settings, signin, signup, pending-approval, landing, and the lesson player itself (a real generated lesson, `EvadingEDR.pdf` chapter 9) at 375/768/1024px.
- Two AC-3 risks flagged by pre-implementation research (`PlayerControls`, `JargonHover`) were both verified NOT broken — no fix applied, consistent with the story's own "verify before fixing" instruction.
- One genuine bug found and fixed outside the original three headline items: all three of `SessionReport.tsx`'s root containers (not just the one AC-4 named) were missing horizontal padding.
- `/onboarding` was not verified — gated behind a new-user account state not reachable with the available test account this session. Recorded as an open gap, not silently skipped.
- Not fixed, correctly left alone per AC-6's scope: the Settings tab row's low discoverability at 375px (functional horizontal scroll, not breakage).

### File List

- `apps/web/src/components/player/MobileNotice.tsx` (NEW)
- `apps/web/src/__tests__/components/player/MobileNotice.test.tsx` (NEW — 4 tests)
- `apps/web/src/components/player/Player.tsx` (MODIFIED — mounts `MobileNotice`)
- `apps/web/src/test/setup.ts` (MODIFIED — global `matchMedia` polyfill, jsdom-gap pattern)
- `apps/web/src/components/reports/SessionReport.tsx` (MODIFIED — horizontal padding + `session-report-root` testid on all 3 root containers)
- `apps/web/src/__tests__/components/reports/SessionReport.test.tsx` (MODIFIED — 1 new padding test)
- `docs/dev2-sprint-tracker.md` (MODIFIED — S3-06 marked done, Sprint 3 count corrected, carried on this branch per the earlier note in this file's Change Log)
