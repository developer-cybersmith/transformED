# Sprint 2 Completion Audit — 2026-07-29

**Scope:** Cross-team — all 4 devs' Sprint 2 + Learner Mode tracker claims (from the online tracker), verified against actual code, not against what any tracker file says.
**Method:** Two independent angles compared against each other: (1) every frontend page in `apps/web`, read in full, to see what it actually calls and whether that's real or mocked; (2) every backend endpoint accessible to the frontend in `apps/api`, read in full, to see whether it's genuinely implemented and who calls it. A 14-agent workflow ran both in parallel, synthesized a wiring cross-reference, then had one agent per dev independently verify their Sprint 2/Learner Mode tracker lines against the codebase, then a final adversarial pass tried to refute every PARTIAL/DISPUTED verdict. Nothing was overturned.

> **A note on timing.** This audit ran while `main` was moving fast under other devs' active work — by the time findings were being written up, D19, D20, D23, and D27 (this session's own Suspense fix) had all already been independently fixed and closed on `main`. Everything below reflects the state as **independently re-verified on 2026-07-30 against the current `main`**, not the snapshot from when the workflow first ran. Two IDs originally drafted as "D28"/"D29" collided with a `D28` Dev 1 had separately opened in the interim for an unrelated structure-detection defect — renumbered to **D29**/**D30** below to avoid collision.

## Legend

| Tag | Meaning |
|---|---|
| 🔴 **Blocking** | Breaks the core student journey for a real (non-mocked) user |
| 🟡 **Real gap** | Genuine, currently-true gap — not urgent to the demo path but real |
| 🟢 **Resolved this session** | Found and fixed/closed as part of this audit |
| 📋 **Process** | Tracker/doc says "Done" but an explicit precondition of "Done" is unmet |

---

## Bottom line

**Sprint 2 is not completely finished.** The core content pipeline (Dev 1) and the upload → generate → play-lesson path (Dev 2 frontend + Dev 1 backend) are genuinely solid — every node, every endpoint, every page in that path was independently read and confirmed real, not mocked, not stubbed. But **the assessment path (quiz submission → teach-back submission → session report) is structurally broken end-to-end** for any real student, because of a single missing piece: nothing anywhere in `apps/api` ever creates a row in the `sessions` table. This is the already-registered **D18** (`docs/DEFECT-REGISTER.md`) — independently reproduced from scratch via direct grep (zero `.insert()` calls against `sessions` anywhere in the codebase), and re-confirmed **still open** as of 2026-07-30.

Two more real gaps were found and added to the defect register (D29, D30). One long-blocked cross-team item (the WebSocket contract sign-off) was resolved during this audit — and in re-verifying it, one further staleness was caught and corrected (see below) rather than signed off blindly.

---

## 🔴 Blocking

### 1. D18 — no code path anywhere creates a `sessions` row *(already registered, confirmed still open)*
`apps/api/app/modules/tutor/service.py::start_session()` only dispatches a Redis-backed FSM event — it never inserts into Postgres. `assessment/service.py` (`grade_quiz`, `grade_teachback`, `get_session_report`) and `analytics/service.py` only ever `.select()` the `sessions` table. Confirmed via direct grep: **zero** `.insert()` calls against `sessions` exist in `apps/api`.

**Effect:** `POST /api/assessment/quiz`, `POST /api/assessment/teachback`, and `GET /api/assessment/session/{id}/report` are all genuinely, correctly implemented — and all three will 404/lookup-miss for any real student, because the row they depend on is never written. The frontend code calling them (`QuizOverlay.tsx`, `TeachBackModal.tsx`, `SessionReport.tsx`) is also correct — this is not a frontend-vs-backend mismatch, it's a missing write path nobody has built yet.

A story file exists (`docs/stories/2-35-session-lifecycle-endpoint.md`, target: `POST /api/assessment/sessions`) — the register notes it's awaiting Dev 3's A/B/C decision.

**Status:** Open. Needs a joint Dev 2 + Dev 3 + Dev 4 decision per D18's existing register entry.

---

## 🟡 Real gaps found this session

### 2. D29 (new) — DPDP `user_consents` table has zero writers
CLAUDE.md §18 names this table an explicit **Sprint 2 priority**: a `user_consents` audit table is required before any attention data is collected, because the `users.attention_consent` boolean alone is insufficient for compliance. The migration (`20260702000000_dpdp_user_consents.sql`) genuinely creates the table, RLS, and a sync trigger — but `process_onboarding()` (`apps/api/app/modules/assessment/service.py:864-976`) never inserts into it. Schema shipped, write path never built. Grepping `apps/api` for `user_consents` finds only a migration-name string inside a test assertion. Re-verified 2026-07-30 against current `main` — still no write path.

**Owner:** Dev 3. **Blocks:** Sprint 3's `AttentionMonitor` cannot legally initialize without this.

### 3. D30 (new) — 3 tests currently failing on `main`
`apps/api/tests/test_tutor_service.py::test_two_below_threshold_no_cooldown_dispatches`, `test_intervention_delivers_tutor_intervene_message`, `test_intervention_no_delivery_on_cache_miss` — all three reproduced live via `pytest`, twice (2026-07-29 and again 2026-07-30 against current `main`, identical failures both times). A `state_raw == "TEACHING"` guard was added to the CES-trigger check (correct behavior per CLAUDE.md §10 — CES monitoring only active in TEACHING), but the tests' mock Redis never returns `"TEACHING"`, so the guard now silently blocks the trigger the tests assert on. The dev4-tracker line these tests belong to (`intervention_selection`) is currently marked `[Completed]`.

**Owner:** Dev 4. Fix is narrow: update the mock fixtures, not the guard (the guard is correct).

### 4. 🟢 WebSocket message contract — Dev 2 sign-off, resolved this session
`docs/ws-message-contract.md` had sat at "Proposed for Dev 2 sign-off" since 2026-07-23. This audit verified the document line-for-line against `apps/api/app/core/websocket.py` — and caught a real staleness in the process: a 2026-07-24 PRD §18 fix dropped the raw `ces` float from `attention_ack`'s payload, which the doc still described in its old shape. **Corrected the doc first** (new reconciliation item (f)), confirmed the change is non-breaking (the frontend already treats `attention_ack` as a Sprint-3-scope no-op and never reads `.ces`), then **signed off 2026-07-29** — see the doc's own Sign-off section for the full basis. The other 5 reconciliation items (a–e) remain open as the scope of a future 4-dev `ws.ts` PR; sign-off freezes the *wire protocol as documented*, not those pending edits.

---

## Dev 2 (my own) domain — gaps found

### 🟢 Fixed same day
- **Dashboard "Reports" quick action was a dead link** — `QuickActions.tsx` linked to `/reports`, which has never been a real route (the real route is `/reports/[sessionId]`, session-scoped, reached from the player after a lesson ends). **Fixed:** removed the card rather than repoint it at a guess — there is no session-history/index page yet to send it to. Add it back once one exists.
- **Behavioral event tracking was backend-ready but never called from the frontend.** Dev 3's `POST /api/analytics/events` is fully implemented and tested (jargon_hover, tab_switch, retry_after_fail, etc. all accepted) — but nothing in `apps/web` called it. **Fixed:** added `lib/analytics.ts` (a thin, fire-and-forget `trackEvent()` wrapper that never throws and no-ops before a session exists) and wired two real call sites — `jargon_hover` from `JargonHover.tsx` on term hover, and `tab_switch` from `Player.tsx` via a `visibilitychange` listener. 7 new tests, `tsc`/`eslint` clean. The remaining known event types (`retry_after_fail`, `quiz_skip`, `teachback_skip`, `intervention_acknowledged`) have no natural existing call site yet and are left for whoever builds the UI they'd attach to.

### Not fixed — lower priority, noted for later
- **Dead code:** `apps/web/src/mocks/api/auth.ts`, `lessonService.getLesson`/`updateProgress` (`lesson.service.ts`), and `reports.service.ts` are all unused by any real page — harmless today, but should be pruned before someone mistakenly builds on them.
- **`SignInForm.tsx:44`** logs `console.error("Login map error:", err)` — stale/mislabeled debug text, not the actual error message.
- **`SignInForm.tsx:103`** — "Forgot password?" is a non-interactive `<span>`, no `href`/`onClick`. Dead end (plausibly intentional — no password-reset flow exists yet — but unlabeled as such).

## Settings page and auth stubs — known, not urgent

- **Settings page (`/settings`) is 100% mocked** — no backend surface exists at all for profile/preferences/notifications/privacy (not just unwired; the endpoints genuinely don't exist server-side). Not a Sprint 2 scope item per the tracker; noting for completeness.
- **`apps/api`'s own `/api/auth/signup`, `/signin`, `/onboarding/complete` are stubs** (`HTTPException(501)`, TODO comments) — the frontend bypasses all of them by calling Supabase Auth's SDK directly, which is a legitimate, working integration. `GET /api/auth/me` is the only genuinely implemented auth endpoint and has zero callers. Worth a cross-team conversation on whether the FastAPI auth module is meant to do anything at all, or whether it should be trimmed.

---

## Per-dev Sprint 2 / Learner Mode tracker scorecard

Verdict counts from independent per-dev verification, each cross-checked a second time by an adversarial recheck pass (0 verdicts overturned).

| Dev | Confirmed | Partial | Unverifiable | Disputed |
|---|---|---|---|---|
| **Dev 1** (pipeline) | 20 | 2 (self-flagged by the tracker itself: S2-7's missing Langfuse cost field, S2-14's eval harness never actually run live) | 1 (S2-12 WS `lesson_ready` push — plumbing confirmed, live delivery can't be confirmed statically) | 0 |
| **Dev 2** (frontend, mine) | 10 | 3 (S2-01, S2-02, S2-04 — all correct code, all blocked by D18) | 4 (S2-08, S2-13, S2-26, S2-34 — not independently re-diffed this pass; S2-34 was separately verified earlier this session via its own 3-agent code review) | 0 |
| **Dev 3** (assessment/analytics) | 10 | 2 (D29's DPDP write-path gap; session report/DNA logic correct but blocked by D18) | 0 | 0 |
| **Dev 4** (tutor/WebSocket) | 7 | 2 (D30's 3 failing tests; WS contract sign-off — now resolved, see above) | 0 | 0 |

**No fabricated "Done" claims were found for any dev.** Every PARTIAL is either a pre-existing, already-registered defect (D18) blocking otherwise-correct code, a newly-found real gap (D29, D30), or the tracker's own honest self-reported caveat. Dev 1's Sprint 2 work in particular was unusually well-substantiated — every pipeline node, provider file, and migration checked was present and matched its documented behavior, including caveats the tracker already disclosed rather than hid.

---

## Wiring matrix — backend endpoints vs. frontend callers

| Endpoint | Real/Stub | Frontend caller |
|---|---|---|
| `POST /api/content/lessons` | Real | `upload.service.ts` |
| `GET /api/content/lessons/{id}` | Real | `upload.service.ts`, `lesson.service.ts` |
| `GET /api/content/lessons` | Real | `library.service.ts`, `dashboard.service.ts` |
| `POST /api/assessment/quiz` | Real | `QuizOverlay.tsx` (blocked by D18 for real students) |
| `POST /api/assessment/teachback` | Real | `TeachBackModal.tsx` (blocked by D18) |
| `GET /api/assessment/session/{id}/report` | Real | `useSessionReport.ts` (blocked by D18) |
| `GET /api/assessment/user/dna` | Real | `onboarding.service.ts` |
| `POST /api/assessment/onboarding/submit` | Real | `onboarding.service.ts` |
| `POST /api/assessment/sessions` (D18 target) | **Does not exist** | — (nothing to call) |
| `WS /ws/{session_id}` | Real | `lessonSocket.ts` |
| `POST /api/auth/signup` / `signin` / `onboarding/complete` | Stub (501) | None — frontend uses Supabase Auth SDK directly |
| `GET /api/auth/me` | Real | None |
| `GET /api/media/signed-url` | Real | None — dormant by design, signing happens inline in content router |
| `GET/POST /api/admin/*` (jobs, jobs/{id}, costs, health) | Real | None — no admin UI in the web app |
| `GET /api/tutor/session/{id}/state`, `POST .../intervene` | Stub (501) | None — Sprint 3 scope |
| `POST /api/analytics/events` | Real | `JargonHover.tsx` (jargon_hover), `Player.tsx` (tab_switch) — wired same day, see Dev 2 gaps above |
| `GET /api/analytics/session/{id}/summary` | Real | None |

---

## What changed as a direct result of this audit

- **`docs/DEFECT-REGISTER.md`**: D29 and D30 added as new open defects (renumbered from an initial D28/D29 draft to avoid colliding with Dev 1's own concurrently-opened D28). Scorecard updated.
- **`docs/ws-message-contract.md`**: a stale `attention_ack` payload description corrected first, then Dev 2 sign-off given, with the verification basis recorded inline.
- **`docs/dev2-sprint-tracker.md`**, **`docs/master-tracker.md`**: cross-team notes added summarizing this audit.
- This file created as the durable record of the audit itself.
- **Both Dev 2-domain gaps fixed same day**: removed the dead `/reports` dashboard link (`QuickActions.tsx`); added `apps/web/src/lib/analytics.ts` and wired `jargon_hover`/`tab_switch` tracking into `JargonHover.tsx`/`Player.tsx`. 7 new tests, full suite green.

The two cross-team defects (D29, D30) remain documented, not fixed — they belong to Dev 3 and Dev 4 respectively, pending their direction on priority.
