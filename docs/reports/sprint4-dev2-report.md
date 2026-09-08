# Sprint 4 Report — Dev 2 (Frontend)

**Sprint:** Weeks 8–9 (Polish + Platform)
**Report date:** 2026-09-07
**Scope:** Dev 2's own Sprint 4 backlog only (`docs/dev2-sprint-tracker.md` §13, S4-01 through S4-12). Bug Resolution (Feature Sprint 2, BR-1 through BR-7) is a separate post-Sprint-4 window and is excluded from this report by request.

---

## Story status

| # | Story | Status |
|---|-------|--------|
| S4-01 | Landing page + pricing polish (`/pricing` page, Razorpay CTA, animation pass) | **Not started.** Pricing content itself is on hold. |
| S4-02 | Razorpay Checkout integration (frontend) | **Partial.** `RazorpayCheckoutButton.tsx` / `useRazorpayCheckout` / `payment.service.ts` built and 8-agent reviewed (Story 2-53), merged. **Not yet wired into any real page** — no route imports the button yet, and the backend's `GET /api/payments/access` still doesn't exist (frontend polls a documented mock, D136). Backend counterpart (Dev 1's Razorpay PR #157) is open + approved, not yet merged. |
| S4-03 | PostHog full instrumentation | **Done** (Story 2-54). All 8 events wired at real trigger points; `identify()`/`reset()` tied to real accounts. Still needs `NEXT_PUBLIC_POSTHOG_KEY`/`HOST` added to Vercel production env before it produces real data — flagged, not silently assumed done. |
| S4-04 | Accessibility audit (WCAG AA) | **Done** (Story 2-55). Roving-tabindex keyboard nav, `aria-live` regions, focus-visible rings, contrast fix, alt-text audit. 8-agent review, all findings fixed in-branch. |
| S4-05 | Performance: code splitting + lazy loading | **Done** (Story 2-56). 2 of 4 backlog items were already true (verified, not re-implemented); 1 genuinely fixed (`recharts`/`AttentionChart` converted to `next/dynamic`, confirmed via before/after build manifest diff); 1 dropped as moot (HeyGen removed as dead code, D144). Lighthouse `/lesson/[id]` > 70 target honestly left unverified — no test credentials exist to reach a real authenticated lesson page; tooling itself verified against `/` instead of fabricating a score. |
| S4-06 | Fold My Library into My Books | **Done** (Story 2-47, ad-hoc live product decision). Backend touch (`content/router.py`) was an explicit user-approved exception. 6-agent review; one finding renumbered to **D115** after a mis-cited D59. |
| S4-07 | Fix CaptionOverlay's unreachable scroll (live bug) | **Done.** Two stacked root causes (`pointer-events-none` + missing `data-lenis-prevent`), both fixed; verified live in a real browser, not just asserted. |
| S4-08 | Fix lesson "restarting" after quiz + teach-back on the last segment (live bug) | **Done.** Root cause: `.play()` on an already-`ended` `<audio>` element seeks back to 0 per the HTML media spec. Fixed by checking `audio.ended` first. 2 regression tests. |
| S4-09 | Redesign CaptionOverlay to one-line-at-a-time captions | **Done**, direct user feedback after S4-07. Proportional per-line timing (no real per-line timestamps exist yet — flagged as a real, larger follow-up, not silently worked around). Verified live against real playback. |
| S4-10 | Loading + error + empty states for all flows | **Done** (Story 2-50, ad-hoc S4 number). |
| S4-11 | Lesson-status poll ceiling + lesson route error boundary | **Done** (Story 2-51, ad-hoc S4 number). Explicit poll-timeout UX state (was previously silent-forever polling) + route-level error boundary. |
| S4-12 | Email notifications (lesson ready, session report) | **Done** (Story 2-52, ad-hoc S4 number, reprioritized ahead of S4-02 by explicit user instruction). Backend touch (`notification_log`, `EmailProvider`/Resend, ARQ job) was an explicit user-approved exception. Review found and fixed a critical claim-before-send bug that could have permanently and silently lost a notification. |

**10 of 12 done. 1 partial (S4-02, blocked cross-team on backend). 1 not started (S4-01, on hold).**

---

## Findings (this Sprint 4 window)

- **D115** — a review finding during S4-06 was originally mis-cited against an existing D59 entry; corrected to its own register id rather than silently overloading D59's meaning.
- **D136** — `GET /api/payments/access` doesn't exist yet; S4-02's frontend is built against a documented mock (`payment.service.ts::checkAccess`), not silently assumed real.
- **D144** — HeyGen removed entirely as dead code (no node in the pipeline ever called it); S4-05 correctly dropped its "preload HeyGen video" backlog item as moot rather than preloading nothing meaningfully.
- Two real, live production bugs found and fixed **outside** any assigned backlog item but during this sprint window's own manual verification passes: the CaptionOverlay unreachable-scroll bug (S4-07) and the last-segment lesson-restart bug (S4-08) — both found by actually using the product in a browser, not by code review alone.

---

## Current metrics

- **Test suite (at S4-05, the last Sprint-4-numbered story to land):** 90 files / 1088 tests, zero regressions. `tsc --noEmit` / `eslint` clean.
- **Stories with adversarial review:** S4-03, S4-04, S4-06 (8/8/6-agent rounds respectively) — all findings resolved in-branch before merge, none deferred silently.
- **Cross-team blockers carried into next window:** S4-02 (Razorpay backend PR #157, open+approved, not yet merged — outside Dev 2's control).

---

## Known gaps

- **S4-01** — pricing page not started; content itself is on hold, not a Dev 2 execution gap.
- **S4-02** — frontend checkout unit exists but isn't reachable from any real page yet; real payment unlock is blocked until Dev 1's backend (`GET /api/payments/access`, PR #157) merges.
- **S4-03** — PostHog events are wired but inert in production until the real key/host are added to Vercel's env vars.
- **S4-05** — `/lesson/[id]` Lighthouse score is unverified (no disposable test account); tooling itself is proven working, the actual target route's score is not.
- **S4-09** — caption timing is a proportional approximation, not real per-line sync — no word/sentence-level timestamps exist anywhere in the pipeline yet (`NarrationTimestamp` is per-slide). Flagged as its own follow-up, since picked up as Bug Resolution's BR-3/BR-4 (out of scope for this report).

---

## Next steps

1. Wire `RazorpayCheckoutButton` into a real page once Dev 1's PR #157 merges (S4-02 completion).
2. Add real `NEXT_PUBLIC_POSTHOG_KEY`/`HOST` to Vercel production env (S4-03 completion).
3. Get a disposable test account to actually measure `/lesson/[id]`'s Lighthouse score (S4-05 residual gap).
4. Resume S4-01 once pricing content is unblocked.
