# TransformED AI — Go-to-Market Readiness Audit

**Prepared:** 2026-08-18 | **Method:** 11 parallel codebase/documentation audits across backend, pipeline, frontend, adaptive tutor, assessment, data model, decisions, sprint tracking, QA, cost/infra, and privacy/compliance | **Scope:** `/Users/apple/HIE/transformED` monorepo as of this date

---

## 1. What this product is

TransformED AI converts a textbook PDF into a personalized, narrated multimedia lesson: an AI "teacher" walks a student through a chapter with slides, voice narration, an avatar, in-line quizzes, jargon tooltips, and a "teach-back" step where the student explains the concept back and gets AI-scored feedback. A webcam-based attention signal ("CES," Cognitive Engagement Score) and a longitudinal "Learner DNA" profile are meant to make the tutor adaptive — nudging a distracted or fatigued student, and tracking mastery over time.

It is being built specifically for the Indian market: INR pricing (₹799/₹999/₹1,499 tiers), Sarvam AI for Indian-language TTS, DPDP Act 2023 (India's privacy law) named directly in the engineering guide, and an in-progress migration to India-region infrastructure (Fly.io Mumbai). This is not a generic global product with India as one market — it is architected around Indian data-residency law and pricing from day one.

Built by a 4-person dev team since roughly mid-June 2026, against a self-declared goal: **"First paying student completes a full session by end of Week 10."** Today is Week 10+, and that milestone is not confirmed met anywhere in the project's own tracking documents.

## 2. Headline verdict

**Not ready for a real customer-facing launch today — but closer than the defect count suggests.** The engineering underneath is unusually disciplined for a 10-week MVP (schema contracts, decision logs, defect registers, cost enforcement, real security hardening on quiz/teach-back). The blockers are concentrated, not diffuse: a missing child-safety mechanism, a non-functional privacy control, a core promise (whole-book lesson generation) that is unverified, and a headline feature ("Learner DNA personalizes your learning") that doesn't yet do what its name claims. These are fixable in weeks, not a rebuild — but they are the kind of gaps a PM should not let reach a live customer.

## 3. Subsystem scorecard

| Area | Rating | One-line finding |
|---|---|---|
| Backend architecture | Developing | Resilience/circuit-breaker engineering is excellent; but auth sign-up/sign-in endpoints are literal `501 Not Implemented` stubs, and "swap LLM vendor via env var" is not really true — only OpenAI is wired. |
| Content generation pipeline | Developing → Fragile | Real 15-node pipeline, cost ceiling genuinely enforced — but the one run that proves whole large textbooks work has been **blocked since 2026-08-05** on a zero API balance, and the root-cause context-window cap that caused the original 4%-of-book bug is still unfixed. |
| Frontend / learner UX | Strong | Full learner journey wired end-to-end with real loading/error states and a genuinely well-built attention-consent flow — undercut by thin accessibility (keyboard nav absent) and a live brand-name bug ("HIEIQ.AI" / "Join HIE" instead of TransformED AI) in onboarding/signup. |
| Adaptive tutor (CES + Learner DNA) | Developing | CES scoring and race-safe intervention guards are production-grade engineering; but **Learner DNA does not feed back into lesson planning, pacing, or difficulty anywhere in the pipeline** — it's a report/dashboard feature today, not an adaptive engine. Intervention thresholds are launch-day guesses, unvalidated against real sessions. |
| Assessment (quiz / teach-back / onboarding) | Strong | Genuinely security-hardened (IDOR fixes, prompt-injection defenses, enumeration-oracle fix) with a real EMA-based mastery/reassessment loop. Onboarding is a static style survey, not adaptive placement — don't oversell it as one. |
| Data model & schema | Strong | Disciplined migration history, a frozen and multi-dev-reviewed LessonPackage contract — a trustworthy foundation with a few disclosed, tracked gaps (an idempotency race, weak SQL-string migration tests). |
| Decision hygiene & defect tracking | Strong process, heavy debt | Every decision and defect is dated, ID'd, and requires a CI-enforced closure — better practice than most orgs this size. But 119 logged defects and several open High-severity items (dead image-fallback vendor, a cache-key bug that will break interventions once turned on) remain. |
| Sprint timeline | Behind | Today is past the team's own Week-10 "first paying student" deadline; that milestone is not confirmed hit in any tracker. Sprint 4 (load testing, Stripe, hardening) is largely untouched. |
| Test coverage & QA | Fragile | Large test suite by count (~130 backend + 79 frontend files), but the team's own audit found 24% of assertions test a mock against itself, and a prior "360-audit" found **11 of 12 backend↔frontend integration routes were actually broken or mocked** despite green backend tests — including quiz answers rendering as wrong due to a field-name mismatch. Real production-load testing has never been run. |
| Cost & infrastructure | Developing | The $3.00/lesson ceiling is genuinely enforced in code — but empirically unvalidated: only ~23 lessons have ever been generated, no real cost-per-lesson benchmark exists, and one paid vendor (Imagen, the image fallback) is already dead. Deployment has quietly (and successfully) moved from Railway to Fly.io Mumbai, ahead of stale docs. |
| Privacy, compliance & regional readiness | Fragile | The DPDP consent flow for webcam monitoring is well-built and honestly worded. But: the account-deletion button has no click handler (right-to-erasure isn't actually exercisable), analytics profiles are never erased on deletion, compute/Redis are still outside India despite a stated residency requirement — and most seriously, **there is no age-gating or parental-consent mechanism anywhere in the product**, despite webcam-based monitoring of what is very likely a substantially-minor user base. This gap is not even logged in the team's own defect or deferred-work trackers. |

## 4. Why "Learner DNA" needs a marketing gut-check

This is worth calling out on its own because it's a positioning risk, not just an engineering gap. The product's name and pitch imply adaptive, personalized tutoring. As built today:

- **CES (engagement scoring)** is real, live, and reasonably sophisticated — it detects distraction/fatigue from quiz performance, teach-back scores, and webcam-derived head-pose/blink signals, and triggers pre-written intervention messages. This part earns the "attentive tutor" story.
- **Learner DNA (the longitudinal mastery profile)** is computed and displayed, but a direct code search across the entire content pipeline found **zero references to it** — it does not change what lesson gets planned, how hard a quiz is, or how a chapter is paced. It is a session-report feature, not a personalization engine.

Recommendation: launch messaging should say "engagement-aware tutoring with a personal learning report," not "AI that adapts your lessons to you" — until Learner DNA actually closes that loop.

## 5. Full subsystem detail

The 11 underlying audits (full text preserved in the session transcript, condensed here) covered: backend API/module architecture; the LangGraph content pipeline; the Next.js frontend and lesson player; the CES/Learner DNA adaptive engine; the quiz/teach-back/onboarding assessment system; the Supabase data model and schema contracts; the product's own decision log and defect register; sprint/story completion tracking; automated test coverage; cost tracking and infrastructure; and privacy/DPDP/child-safety readiness. Each is summarized in the scorecard above and expanded in the priority list in `launch-readiness-plan.md`.

## 6. Bottom line for a senior PM

This team can ship a good product — the craftsmanship in the parts that are done (assessment security, schema discipline, resilience engineering, consent UX copywriting) is above what's typical at this stage. The job now is not "build more," it's "close a short, specific list of trust and truth-in-advertising gaps," get real usage data from a small closed pilot, and then launch honestly scoped. See `launch-readiness-plan.md` for the phased plan and `user-personas.md` for who this needs to work for.
