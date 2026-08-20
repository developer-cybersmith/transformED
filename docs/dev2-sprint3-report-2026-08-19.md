# Dev 2 — Sprint 3 Completion Report

**Sprint:** Sprint 3, Weeks 6–7 — *"MediaPipe + CES + Full Tutor FSM"* (per `docs/master-tracker.md`)
**Owner:** Dev 2 (Frontend, Lesson Player, Product Experience, WebSocket Client)
**Report date:** 2026-08-19 (Sprint 3 closed out same day — S3-08, the last remaining item, shipped and merged this session)
**Sources:** `docs/master-tracker.md` (cross-team plan of record — task list below is taken from here) and `docs/dev2-sprint-tracker.md` §12 (personal tracker — used for dates, PR/story numbers, and the item that grew beyond the original plan)

---

## 1. What Sprint 3 was supposed to do

Per the master tracker's original Sprint 3 plan for Dev 2 — nine line items, seven of which are the actual distinct deliverables (two are sub-bullets of the MediaPipe integration):

1. MediaPipe Face Landmarker WASM integration (30fps local processing, 5-signal aggregation every 5 seconds, WebSocket attention payload sending — raw video never leaves the browser)
2. Consent flow UI (camera permission + privacy notice, server-persisted)
3. Tutor intervention card component (distraction / confusion / fatigue variants)
4. CES indicator in the player (subtle, qualitative-only engagement display)
5. Notifications UI wired to a real backend
6. Session report: attention timeline chart
7. Mobile responsive audit

The section also carries a standing prerequisite (Dev 1's, not Dev 2's): migrate FastAPI/ARQ off Railway to an India-region provider before real students join. That migration's topology was decided separately (`docs/decisions/ADR-001-india-region-migration-topology.md`) and doesn't block any Dev 2 deliverable below.

That's the full plan of record for Sprint 3's base scope. Nothing else was scoped for Dev 2 in Sprint 3 at planning time.

---

## 2. What it does now

| # | Task | Master tracker status | Actual status (verified) |
|---|---|---|---|
| 1 | MediaPipe Face Landmarker WASM integration | ✅ Done | **Done.** Story `2-44-attention-monitor.md`, `AttentionMonitor.tsx` + `useAttentionMonitor.ts` + `signalMath.ts`, merged 2026-08-10. 8-layer adversarial review found and fixed 21 real issues, most consequential a head-pose yaw/pitch axis-extraction bug and a missing `tutorState` gate on AC-1. Raw video confirmed never leaving the browser — only 5 aggregate numbers sent per 5-second window. |
| 2 | Consent flow UI | ✅ Done | **Done.** Story `2-42-attention-consent-modal.md`, `AttentionConsentModal.tsx` + `useAttentionConsent.ts`, merged 2026-08-06. Writes via Dev 3's real `POST /api/assessment/consent` (Story 3-32), not the originally-assumed `PATCH /api/users/consent` — corrected against the real endpoint once it landed mid-review. |
| 3 | Tutor intervention card | ✅ Done | **Done.** Story `2-40-tutor-intervention-card.md`, `TutorInterventionCard.tsx`, merged 2026-08-03. Three visual variants (distraction/confusion/fatigue), non-blocking (audio keeps playing), hard-guarded to never show during `TEACH_BACK`. |
| 4 | CES indicator | ✅ Done | **Done.** Story `2-41-ces-indicator.md`, `CESIndicator.tsx`, merged 2026-08-03. Qualitative label only (Low/Engaged/Focused) — the raw CES float is never shown to the student, enforced by a text-content regex test, not just a label-presence check. |
| 5 | Notifications UI | ✅ Done | **Done.** `useNotificationPreferences.ts` + `settings.service.ts` + `NotificationsTab.tsx`, wired to Dev 4's real `PATCH /api/auth/notifications` (Story 4-23), 2026-08-06/07. Storage only — no email-sending pipeline yet (that's separately tracked as Sprint 4 scope). |
| 6 | Session report: attention timeline chart | ❌ Shown unchecked at planning time | **Done.** Story `2-46-attention-timeline-chart.md`, `AttentionChart.tsx`, merged 2026-08-13. The real report endpoint had no per-window timeline data at all when this started — extended it within the same story (user decision) rather than deferring or faking the chart. Also registered **D109**: the underlying Redis history caps at the last 10 windows regardless of session length; the chart surfaces this honestly via a recency caption instead of implying full-session coverage. |
| 7 | Mobile responsive audit | ❌ Shown unchecked at planning time | **Done — closed today.** Story `2-49-mobile-responsive-audit.md`, merged via PR #149. See §4 below for what this actually turned up — it was not the "audit everything from scratch" job the one-line task description implied. |

**All 7 originally planned Sprint 3 tasks are done.** Two more items grew out of the Reports Page work while it was underway and are tracked as their own line in the personal tracker (S3-06, S3-09) — see below.

---

## 3. Work delivered beyond the original scope

| Story | What it added | Date |
|---|---|---|
| **S3-06 — Reports Page: teach-back summary detail** | The report endpoint already read `teachback_attempts` but only exposed the aggregate score — the richer per-attempt data (feedback praise/correction, concepts hit/missed) was already persisted and just needed exposing. Backend (Dev 3, PR #145) and frontend (Dev 2, PR #146) both shipped; a branch-naming collision between the two halves surfaced a gap in the team's branch-naming convention (now flagged for next time two devs split one task). | 2026-08-18 |
| **S3-09 — Signed-URL auto-refresh + DEFER-012** | Not in the master tracker's original Sprint 3 plan — ad-hoc off a real user-facing gap (`docs/LESSON-DELIVERY-TRACKER.md`'s L3 known risk): a student who paused past the 8-hour signed-URL expiry lost audio/images with only a manual page-level retry. `AudioTimeline`/`SlideRenderer` now each attempt one automatic re-sign before falling back to the existing manual recovery UI. Registered **D66**, **D67** in the same story. | 2026-08-11 |

---

## 4. Independent verification (2026-08-19)

Rather than take the tracker's word for the last item, the Mobile Responsive Audit was run against a real browser session (Playwright) with a real dev server and a real backend, not mocked data alone:

- **The task's own one-line description ("audit everything") turned out to be wrong about where the real gaps were.** The dashboard shell's mobile hamburger nav already existed and was already tested; dashboard/books already had real responsive Tailwind classes. The actual gaps were narrower: the lesson player had zero deliberate mobile handling at all (no "Desktop recommended" banner despite the task explicitly asking for one), and two genuinely broken layouts nobody had reported.
- **Two real bugs found and fixed, not assumed:** `SessionReport.tsx`'s three root containers were all missing horizontal padding (content sat flush against the screen edge on mobile) — found first via the report's error state, then reconfirmed against the real success state by completing a full lesson end-to-end. `/pending-approval` was genuinely horizontally scrollable at 768px — confirmed via `window.scrollTo` actually moving the page, not just a geometry heuristic — caused by a decorative background div missing the same `overflow-hidden` its sibling `signin`/`signup` pages already had.
- **Two flagged risks were checked and found NOT broken, so left alone:** `PlayerControls`'s narrow-width layout and `JargonHover`'s tooltip positioning were both called out as possible mobile-overflow risks during planning; live verification against a real generated lesson showed neither was actually broken (Radix's own collision-avoidance handles the tooltip correctly). Nothing was "fixed" that wasn't first confirmed broken.
- **A stale tracker entry was caught in the process.** The tracker's own S3-08 line still read "NOT STARTED" after the story had already shipped and merged — the story doc had been updated, but the tracker section itself never was. Corrected today (PR #153), verified against real code (`MobileNotice.tsx` exists, the `pending-approval` fix is present on `main`) rather than trusted at face value.
- Full regression: 80 files / 984 tests green, `tsc --noEmit` clean, `eslint` clean.

---

## 5. Bottom line

**Dev 2's Sprint 3 base scope is 100% complete** — all 7 originally planned tasks, plus 2 additional stories that emerged from real integration work, all merged to `main`, all tested, all reviewed. The MediaPipe integration, consent flow, and CES/intervention UI all carry the security guarantee they were built for (raw video never leaves the browser, raw CES/scores never shown to the student). The attention timeline chart and mobile audit both found and closed real gaps in what the report endpoint and the player actually did, rather than shipping to the letter of a one-line task description. Sprint 3 is closed; Sprint 4 is already underway in parallel.
