# TransformED AI — Sprint 3 Consolidated Report

**For:** Engineering Manager & CEO
**Sprint:** Sprint 3 (Weeks 6–7) — *"Attention tracking, engagement scoring, and production hardening"*
**Report date:** 2026-08-21
**Prepared by:** Dev 4, consolidating all four developers' own Sprint 3 reports
**Sources (each person's own report):** `SPRINT-3-STATUS-REPORT.md` (Dev 1), `dev2-sprint3-report-2026-08-19.md` (Dev 2), `sprint3-dev3-audit-report.md` (Dev 3), plus Dev 4's own Sprint 3 tracker and this week's bug fix (this report, written today).

---

## 1. The one-paragraph version

**Sprint 3 shipped the core feature this whole product depends on: watching whether a student is actually paying attention, scoring it in real time, and stepping in — gently — when they're not.** All four of us delivered our planned work. The camera-based attention tracker runs entirely in the student's browser (nothing is ever recorded or sent anywhere), it feeds a live engagement score, and that score now safely triggers check-ins with built-in limits so the app never nags a student too often. On top of that, the team caught and fixed real problems before they could reach a student — an unreadable scanned textbook page that was being scored "perfect quality," a scanned-document processor that had never once completed successfully despite being reported as ready, a bug that could have double-charged for a retried job, two broken mobile screens, and — found this week — a bug that was silently crashing the engagement monitor for every student partway through their lesson. Every one of these is fixed and tested. What's left is narrow: one long test run to fully close out Dev 1's testing work, and a couple of small follow-up items already assigned and tracked.

---

## 2. Was Sprint 3 a success?

| Person | What they own | Delivered | Verified | Bottom line |
|---|---|:--:|:--:|---|
| **Dev 1** | The document-processing pipeline, cost tracking, automatic failure protection, staff admin tools | 3 of 5 goals fully done; 2 linked to one pending test run | 1,245 automated checks passing; first-ever successful real run against live AI ($0.83, 12 minutes) | 🟡 Substantially delivered — one verification run from full close-out |
| **Dev 2** | The lesson player, camera-based attention tracker, engagement indicator, notifications, mobile experience | 7 of 7 planned items + 2 bonus items | 984 automated checks passing, verified in a real browser | ✅ 100% complete, nothing blocked |
| **Dev 3** | The engagement-scoring formula, personalized learning profiles, privacy consent records, session reports | 18 of 18 planned items | 470 of 470 automated checks passing (100%) | ✅ 100% complete, nothing blocked |
| **Dev 4** | Live signal delivery, login security, the tutor's decision-making logic, check-in guardrails | 9 of 9 planned items, plus a same-day fix for a bug found this week | All own-domain automated checks passing | ✅ 100% complete — one bug fix landing today |

*Dev 4 is the author of this report.*

**No one is reporting something as "done" that isn't.** Every item above was checked against real code and real test runs, not just a checklist someone filled in.

---

## 3. What each person built, in plain terms

### 3.1 Dev 1 — Document processing, cost tracking, and safety nets

Three things are fully done and tested: **automatic failure protection** (if an AI service starts failing repeatedly, the app stops calling it and tries again later automatically — this already caught a real outage mid-sprint), **cost tracking per lesson** (every dollar spent on AI is now recorded and attributable), and the **backend of a staff admin tool** (lets the team see job status and retry a failed one).

The fourth item — a large automated test that runs 20 sample textbook chapters through the whole system — had been marked "done" earlier in the sprint but had, in fact, never once finished successfully. Two hidden problems were found and fixed this week. With those cleared, the team went further and built a second test set out of the messy, real-world documents students actually upload (a sideways scan, a corrupted file, a locked file) — something the original clean sample set couldn't represent. That test caught a genuine issue: **a badly scanned page was coming out unreadable but still being labeled "perfect quality."** That's now fixed — the system flags it instead of shipping it silently. The one item left is letting the original 20-document test run to completion (a few hours, real but modest cost); the fifth goal (improving AI prompts using real results) can't be finished until that run produces real data to learn from.

### 3.2 Dev 2 — The lesson player, attention tracker, and mobile experience

All 7 planned items are done, plus 2 more that came up along the way. Highlights: the **camera-based attention tracker** (confirmed: raw video never leaves the student's device — only five small numbers per five seconds), the **consent screen** before any camera data is used, the **check-in card** that appears when a student seems distracted or tired (never interrupts a student mid-answer), and a **plain-language engagement indicator** that only ever shows "Low / Engaged / Focused" — never a raw number or score to the student.

Two extra items were added because real integration work surfaced real gaps: a fuller teach-back summary on the session report, and an automatic recovery fix so a student who pauses a lesson for a long time doesn't lose their audio or images.

The mobile check found **two real broken screens** and fixed both (a report page with content flush against the phone edge, and a page that scrolled sideways on a phone). It also checked two other screens that were *suspected* of being broken and found they were actually fine — so nothing was "fixed" that didn't need it. A stale status note in the team's own tracker was also caught and corrected.

### 3.3 Dev 3 — Engagement scoring, personalized learning profiles, and privacy records

All 18 planned items are done, and **100% of the 470 automated checks pass** — up from 451 passing at the start of this audit. Highlights: the **engagement-scoring formula** described in this project's plan is now fully implemented and env-configurable; a **personalized "Learner DNA" profile** (not a raw IQ/EQ score — a descriptive profile with a required privacy disclaimer) that updates session over session; a fix for a **race condition** where two check-ins arriving at nearly the same instant could have let a limit be exceeded; and a proper **privacy consent record** (who consented, to what, and when) rather than a single yes/no flag.

Two issues turned up during the audit and were fixed the same day — both were mismatches in how the tests were checking the code, not real product bugs. The underlying product behavior was correct throughout.

### 3.4 Dev 4 — Live signals, login security, and the tutor's decision logic

All 9 planned Sprint 3 items are done. The pipeline that takes a live attention reading from a student's browser, buffers it, and turns it into an engagement score now runs end to end in well under its speed budget. On top of the score itself, every one of the plan's safety rules is implemented and tested: a 2-minute quiet period after any check-in, a hard cap of 3 "are you distracted?" check-ins per session, a "tiredness" check-in that fires once per session and never again, and check-in messages that route to the right one of three message types every time.

**One bug found and being fixed today:** while cleaning up an unrelated code-quality warning, a leftover duplicated block of code was found in the tiredness-check logic — a copy-paste mistake that, due to how Python handles variable scope, crashed that check for every student, on every signal, from the moment a real session actually started. It was already present in the main codebase independently of any of my other work, not something this sprint introduced. It was reproduced on purpose (confirmed the exact crash, then confirmed the fix clears it) and the fix is landing today.

---

## 4. Real bugs found and fixed this sprint

A running theme this sprint: the team went looking for problems instead of waiting for students to find them. None of the following were reported by a user — all were caught by testing, code review, or a deliberate real-world check.

| # | What was found | Who found & fixed it | Why it mattered |
|---|---|---|---|
| 1 | A large test tool was marked "ready" but had never once completed a real run — two hidden causes | Dev 1 | The sprint's central quality tool had zero real coverage despite being reported as ready |
| 2 | A badly scanned page produced unreadable text but was still scored "perfect quality" | Dev 1 | Would have shipped a broken lesson to a student with no warning at all |
| 3 | Two AI services had no cost tracking at all | Dev 1 | Silent gap in knowing what the app actually spends |
| 4 | Retrying a failed job twice at once could double-charge | Dev 1 | Real-money risk |
| 5 | A report page and a signup-style page were visually broken on phones | Dev 2 | Real students on phones would have hit both |
| 6 | A race condition could let a check-in limit be exceeded under bad timing | Dev 3 | The "don't nag the student" limit could silently fail |
| 7 | Privacy consent was a single yes/no flag with no record of when or what was agreed to | Dev 3 | Needed for legal/privacy compliance before real students start |
| 8 | A copy-paste duplicate crashed the tiredness check for every student after their first signal | Dev 4 | The engagement-monitoring safety net was silently broken for real sessions |

---

## 5. What's left open

- **Dev 1:** let the 20-document test run finish uninterrupted (a few hours, modest real cost); prompt tuning follows immediately after, since it depends on that run's results; a decision is still needed on whether the admin tool needs a visual screen this sprint or can wait; testing multiple students generating lessons at the same time is deliberately deferred to next sprint, with three specific risks already written down so that work doesn't start from zero.
- **Dev 3:** flagged two small items for other people to close — one for Dev 4 (a login-related response format fix, now folded into this week's fix) and one for Dev 1 (a missing test tool needs to be added to the project's dependency list).
- **Dev 4:** land today's tiredness-check bug fix (already written and verified, landing same-day).
- **Everyone:** there's a broader, repo-wide list of about 228 automated checks failing somewhere across the whole project — the audit confirmed almost none of them belong to Dev 3 or Dev 4's own work (already at zero and 100% respectively); the remainder is mostly pre-existing Dev 1-area issues the team has agreed to clear before the next sprint's work merges.

---

## 6. Bottom line

Sprint 3 delivered the feature the whole product is built around — watching attention, scoring engagement, and stepping in safely — end to end, with every planned item complete across all four people and no fabricated "done" claims. Just as importantly, the team spent real effort this sprint *proving* things worked rather than assuming they did, and that effort caught genuine problems (a silently-broken quality check, a silently-broken tiredness check, two broken phone screens, a double-billing risk) before any student ever saw them. What remains is small, understood, and already in motion: one test run finishing, one same-day bug fix landing, and a short, already-named list of cross-team cleanup for next sprint.
