# Dev 3 Handoff: Sprint 2 Audit Findings (from the 360° Audit)

**From:** Dev 1 (developer1-cybersmith)
**To:** Dev 3 (Assessment / CES / Learner DNA owner)
**Date:** 2026-07-27
**Source:** `docs/reports/sprint2-360-audit-2026-07-27.md` + `docs/reports/sprint2-360-reaudit-2026-07-27.md`
**Severity:** One CRITICAL item needs your input before Dev2 can fix it. Everything else is your backend logic being confirmed correct — no action needed unless the team decides otherwise.

---

## TL;DR

Good news first: every finding that touched your module confirmed **your backend logic is correct**. The defects are either a naming mismatch with the frontend (one real bug) or a frontend gap in surfacing data you already compute correctly (not your problem to fix). One item needs a quick decision from you.

---

## 1. Quiz Feedback Field-Name Mismatch (CRITICAL — needs your input)

**What's happening:** `apps/api/app/modules/assessment/service.py` builds each quiz feedback item with keys `question_id, question, is_correct, correct_index, correct_option, selected_option, explanation`. Dev2's `QuizFeedbackItem` type and its only consumer, `QuizOverlay.tsx`, read `correct`/`message` instead — neither key exists on your side. **Every quiz in production currently renders every answer as wrong, with a blank explanation, regardless of what the student actually answered.**

Your `QuizResult.feedback` is typed `list[dict[str, Any]]`, so nothing on the Python side ever caught this — it's a pure wire-shape drift between two sides that were each internally consistent but never actually cross-checked.

**What I need from you:** confirm `is_correct`/`explanation`/`correct_option`/`selected_option` is the intended, final shape (it looks deliberate — reads like a considered design, not an accident). Once confirmed, Dev2 will rename their side to match (see `docs/dev2-sprint2-wiring-handoff.md` §4). If you'd rather add backend aliases instead of asking Dev2 to rename, that's your call — either resolves it, just needs to actually happen on one side or the other.

---

## 2. `rubric_scores` Type Drift (MEDIUM — no backend action, FYI)

Your backend intentionally sends `TeachbackResult.rubric_scores` as `dict[str, str]` — descriptive labels (accuracy/completeness/clarity → "Exceptional"/"Proficient"/etc.), per the no-raw-scores rule and Story 3-14's authorized breaking change. This is correct and confirmed unchanged.

The problem is entirely on Dev2's side: `types/assessment.ts` and `lib/assessment.ts` both still declare it as numeric, with two *different* key sets, neither matching yours. It's currently harmless only because `TeachBackModal.tsx` never actually reads the field. Flagged to Dev2 to fix their type files to match your (correct) backend shape — no action needed from you unless they ask for the exact canonical key names, which are in your `schemas.py`.

---

## 3. `SessionReport` Sends Raw Numeric Scores on the Wire (LOW — a decision, not a bug)

`SessionReport`'s response model (`ces_score: float`, `ces_breakdown: dict[str, float]`, `teachback_score: float | None`) carries raw numbers over the wire, even though `SessionReport.tsx` correctly converts to qualitative labels before rendering — so nothing raw ever reaches the DOM, but it's visible via network inspection. This is a known, documented Story 3-19 tradeoff, not a new regression.

**Worth a team decision, not urgent:** if CLAUDE.md's "no raw scores shown to students" is meant literally at the wire level (not just rendered UI), the label conversion would need to move server-side, which is a frozen-contract change requiring 4-dev review. If the current interpretation (DOM-only) is intentional, it'd be worth clarifying that in CLAUDE.md so future audits stop flagging it as a gap.

---

## 4. `reassessment_due` — Your Logic Is Correct, Frontend Discards It

Not your action item, just context: `GET /api/assessment/user/dna`'s `reassessment_due` computation (every 10th session, via the Redis key) is correct and confirmed working. Dev2's `OnboardingFlow.tsx` fetches it and then throws the result away before checking the flag — that's on their handoff doc (`docs/dev2-sprint2-wiring-handoff.md` §5), nothing for you to change.

---

## Bottom Line

Only §1 needs a response from you — everything else in the assessment domain checked out as backend-correct. Ping me or Dev2 directly once you've confirmed the quiz feedback shape.

---

## Reference

- `docs/reports/sprint2-360-audit-2026-07-27.md` — original full audit
- `docs/reports/sprint2-360-reaudit-2026-07-27.md` — re-verification, confirms all of the above unchanged
- `docs/dev2-sprint2-wiring-handoff.md` — Dev2's corresponding action items
