# Dev 3 — Branch Map & Integration Tracker

**Owner:** Dev 3 (tannmayygupta)
**Last updated:** 2026-07-20

---

## Integration Branch Topology

Each master branch is a clean, sprint-isolated integration point.
All three share the same base lineage (via `main`) but contain **only their own sprint's sub-branches**.

| Integration Branch | Base | Contains | State |
|-------------------|------|----------|-------|
| `master-sprint1-dev3` | `sprint1/s1-9-post-lessons-endpoint` | Sprint 1 Dev3 task branches only (14 branches) | COMPLETE |
| `master-sprint2-dev3` | `sprint1/s1-9-post-lessons-endpoint` | Sprint 2 Dev3 task branches only (5 branches) | COMPLETE |
| `master-sprint3-dev3` | `main` | Sprint 3 Dev3 task branches only (5 of 7 branches) | IN PROGRESS — Tasks 6–7 not started |

---

## Sprint 0 — Foundation (Week 1)

All Sprint 0 branches are merged to `main`. No separate integration branch needed.

| Branch | Story | Purpose | Status |
|--------|-------|---------|--------|
| `dev3-sprint0-task1` | 3-1 | Assessment module stub | MERGED → main |
| `dev3-sprint0-task2` | 3-2 | Assessment DB tables | MERGED → main |
| `dev3-sprint0-task3` | 3-3 | Analytics DB tables | MERGED → main |
| `dev3-sprint0-task4` | 3-4 | Onboarding diagnostic survey | MERGED → main |
| `dev3-sprint0-task5` | 3-5 | GPT-4o-mini provider wired | MERGED → main |
| `dev3-sprint0-task6` | 3-6 | Teachback scoring prompt + rubric | MERGED → main |
| `dev3-sprint0-task7` | 3-7 | OpenAPI spec + contract freeze | MERGED → main |

---

## Sprint 1 — Core Assessment API (Weeks 2–3)

**Integration target:** `master-sprint1-dev3`
**Base:** `sprint1/s1-9-post-lessons-endpoint`
**Sub-branches:** 14 (includes 2 archived superseded branches for history)

| # | Branch | Story | Purpose | Status |
|---|--------|-------|---------|--------|
| 1 | `sprint1/s1-1-quiz-endpoint` | 3-8 v1 | Initial quiz endpoint — ARCHIVED (superseded by v2) | ARCHIVED |
| 2 | `sprint1/s1-8-1-quiz-blockers` | 3-8-1 | Post-review partial fix — ARCHIVED (superseded by v2) | ARCHIVED |
| 3 | `sprint1/s1-3-teachback-endpoint` | 3-9 | `POST /assessment/teachback`, GPT-4o-mini scoring, 19 tests | MERGED → main |
| 4 | `sprint1/s1-1-quiz-endpoint-v2` | 3-8 | Full quiz v2: IDOR guard, CES×100 fix, Field validators, 28 tests | MERGED → main |
| 5 | `sprint1/s1-15-bmad-process-docs` | 3-15 | BMAD process docs, story-first gate evidence | MERGED → main |
| 6 | `sprint1/s1-10-quiz-security-hardening-impl` | 3-10 | Quiz security impl — SEC-006 oracle fix | MERGED → main (via blocker-fixes) |
| 7 | `sprint1/s1-14-rubric-labels` | 3-14 | `rubric_scores` descriptive labels on teachback response | MERGED → main (via blocker-fixes) |
| 8 | `sprint1/s1-10-quiz-security-hardening` | 3-10 | Quiz security story doc + extra tests | MERGED → main (via blocker-fixes) |
| 9 | `sprint1/s1-11-teachback-security-hardening` | 3-11 | Teachback IDOR guard → 403, 502 on GPT failure | MERGED → main (via blocker-fixes) |
| 10 | `sprint1/s1-12-quiz-attempt-number-fix` | 3-12 | Dynamic `attempt_number` via SELECT COUNT | MERGED → main (via blocker-fixes) |
| 11 | `sprint1/s1-13-unique-attempt-constraints` | 3-13 | 409 Conflict on duplicate attempt | MERGED → main (via blocker-fixes) |
| 12 | `dev3-sprint1-blocker-fixes` | 3-10..3-14 | Canonical consolidation of Stories 3-10 to 3-14 (PR #49) | MERGED → main |
| 13 | `sprint1/s1-16-audit-fixes` | 3-16 | `prompts.py` encoding fix, teachback log sanitization | MERGED → main |
| 14 | `sprint1/s1-17-dpdp-user-consents` | 3-17 | DPDP `user_consents` migration, RLS hardening | MERGED → main |

---

## Sprint 2 — Analytics & Learner DNA Read (Weeks 4–5)

**Integration target:** `master-sprint2-dev3`
**Base:** `sprint1/s1-9-post-lessons-endpoint`
**Sub-branches:** 5

| # | Branch | Story | Purpose | Status |
|---|--------|-------|---------|--------|
| 1 | `dev3-sprint2-task1` | 3-18 | CES session score write (`ces_final` → sessions, Redis rolling avg) | MERGED → main |
| 2 | `dev3-sprint2-task2` | 3-19 | `GET /assessment/session/{id}/report` — session summary, 30 tests | MERGED → main + master-sprint2-dev3 (2026-07-20) |
| 3 | `dev3-sprint2-task3` | 3-20 | Learner DNA EMA update — upsert per session, 9 dimensions | MERGED → main |
| 4 | `dev3-sprint2-task4` | 3-21 | `GET /analytics/session/{id}/summary` — DNA dimensions, 31 tests | MERGED → main |
| 5 | `dev3-sprint2-task5` | 3-22 | DNA badge labels + onboarding submit endpoint | MERGED → main |

---

## Sprint 3 — CES Calibration & DNA Intelligence (Weeks 6–7)

**Integration target:** `master-sprint3-dev3`
**Base:** `main` (all 5 task branches already merged to main before integration branch was created)
**Sub-branches:** 5 of 7 (Tasks 6–7 not started)

| # | Branch | Story | Purpose | Status |
|---|--------|-------|---------|--------|
| 1 | `dev3-sprint3-task1` | 3-23 | `ces.py` — CES formula, `None` redistribution, Redis 5s window | MERGED → main |
| 2 | `dev3-sprint3-task2` | 3-24 | `ces_baseline.py` — per-learner baseline, 5-session rolling avg, Redis | MERGED → main |
| 3 | `dev3-sprint3-task3` | 3-25 | `dna_fusion.py` — EMA fusion 0.7 retain × 0.3 new, 9 dimensions | MERGED → main |
| 4 | `dev3-sprint3-task4` | 3-26 | `dna_profile.py` — GPT-4o-mini profile text, badge_labels, DPDP disclaimer | MERGED → main |
| 5 | `dev3-sprint3-task5` | 3-27 | `dna_growth.py` — growth delta per dimension, session_events write | MERGED → main |
| — | *(not started)* | 3-28 | Sprint 3 Task 6 — TBD | NOT STARTED |
| — | *(not started)* | 3-29 | Sprint 3 Task 7 — TBD | NOT STARTED |

> **Note:** `master-sprint3-dev3` was created fresh from `main` on 2026-07-20.
> All 5 Sprint 3 task branches were already fully merged to `main` before this integration branch was created.
> This branch is the clean Sprint-3-only testing snapshot — it contains Sprint 3 code WITHOUT
> Sprint 2 task branches explicitly merged into it (Sprint 2 code is present via `main` ancestry).

---

## Learner Mode Sprint — PLANNED

**Integration target:** `master-learner-mode-dev3` (to be created)
**Base:** `main`
**Status:** NOT STARTED — branch and stories not yet created

| # | Branch | Story | Purpose |
|---|--------|-------|---------|
| 1 | `learner-mode-sprint-task1-dev3` | TBD | Tier-aware quiz/checkpoint count (T1: 3–5, T2: 2–3, T3: 1–2) |
| 2 | `learner-mode-sprint-task2-dev3` | TBD | Session report contextualised by tier |
| 3 | `learner-mode-sprint-task3-dev3` | TBD | Include tier + params in session report generation API |
| 4 | `learner-mode-sprint-task4-dev3` | TBD | Pricing-tier gate for T1 (DEFERRED — pending founder sign-off) |
