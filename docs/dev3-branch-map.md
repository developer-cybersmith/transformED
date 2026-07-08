# Dev 3 — Branch Map & Integration Plan

**Owner:** Dev 3 (tannmayygupta)
**Integration base:** `sprint1/s1-9-post-lessons-endpoint` (tip `5951dec`) — Dev 1's pipeline branch (POST /lessons, PDF extraction, chunking, embeddings)
**Last updated:** 2026-07-08

---

## Integration Branches

| Branch | Based on | Purpose |
|--------|----------|---------|
| `master-sprint1-dev3` | `sprint1/s1-9-post-lessons-endpoint` | All Sprint 1 Dev 3 work in development order |
| `master-sprint2-dev3` | `sprint1/s1-9-post-lessons-endpoint` | All Sprint 2 Dev 3 work in development order |
| `master-sprint3-dev3` | `sprint1/s1-9-post-lessons-endpoint` | All Sprint 3 Dev 3 work in development order |

> Sprint 0 branches are all reachable from `main` (the common ancestor of the integration base). No `master-sprint0-dev3` is needed — every Sprint 0 commit is already present in any branch descended from `main`.

---

## Sprint 0 — Foundation (Week 1)

**Stories:** 3-1 → 3-7 | All branches MERGED → main | All Sprint 0 branches are IN the integration base.

| Integration Order | Branch | Story | Purpose | Tip SHA | Date | Parent | Status |
|:-----------------:|--------|-------|---------|---------|------|--------|--------|
| 1 | `dev3-sprint0-task1` | 3-1 | Assessment module stub (router, schemas, service scaffold) | `df8744a` | 2026-06-26 | `main` | MERGED → main |
| 2 | `dev3-sprint0-task2` | 3-2 | Assessment DB tables (quiz_attempts, teachback_attempts) | `596c271` | 2026-06-26 | `main` | MERGED → main |
| 3 | `dev3-sprint0-task3` | 3-3 | Analytics DB tables (session_events) | `acc0a6b` | 2026-06-26 | `main` | MERGED → main |
| 4 | `dev3-sprint0-task4` | 3-4 | Onboarding diagnostic (20-question survey route) | `e492790` | 2026-06-26 | `main` | MERGED → main |
| 5 | `dev3-sprint0-task5` | 3-5 | GPT-4o-mini provider wired for scoring | `4d9f58c` | 2026-06-26 | `main` | MERGED → main |
| 6 | `dev3-sprint0-task6` | 3-6 | Teachback scoring prompt + rubric | `5b22ac0` | 2026-06-26 | `main` | MERGED → main |
| 7 | `dev3-sprint0-task7` | 3-7 | OpenAPI spec + contract freeze | `6f99028` | 2026-06-26 | `main` | MERGED → main |
| 8 | `sprint0/s0-7-onboarding-fix` | — | Onboarding page route fix (BMAD audit) | `1a20eeb` | 2026-06-26 | `main` | MERGED → main |
| 9 | `sprint0/s0-8-audit-test-fixes` | — | BMAD audit fixes (table-scoped assertions, CES validator, boundary tests) | `b3a856b` | 2026-06-27 | `main` | MERGED → main |
| 10 | `sprint0/s0-9-final-audit-fixes` | — | Final BMAD audit pass (120 unit tests GREEN) | `d8e0bdd` | 2026-06-27 | `main` | MERGED → main |

---

## Sprint 1 — Core Assessment API (Weeks 2–3)

**Stories:** 3-8 → 3-17 | 14 branches | Integration target: `master-sprint1-dev3`

> **Topology note:** Sprint 1 was non-linear. Story 3-8 was implemented twice (v1 → discovered missing IDOR guard + wrong CES formula → v2 full BMAD re-implementation). Stories 3-10..3-14 were implemented in parallel topic branches then consolidated into `dev3-sprint1-blocker-fixes` which is the canonical merged commit. The integration below replays them in the order they were authored.

| Integration Order | Branch | Story | Purpose | Tip SHA | Date | Parent Branch | Status |
|:-----------------:|--------|-------|---------|---------|------|---------------|--------|
| 1 | `sprint1/s1-1-quiz-endpoint` | 3-8 v1 | Initial quiz endpoint (POST /api/assessment/quiz) — superseded by v2 | `d399a2a` | 2026-06-27 | `main` | ARCHIVED (superseded) |
| 2 | `sprint1/s1-8-1-quiz-blockers` | 3-8-1 | Post-review blocker fixes for v1 (IDOR, CES scale, Field validators) — superseded | `e004743` | 2026-06-27 | `sprint1/s1-1-quiz-endpoint` | ARCHIVED (superseded) |
| 3 | `sprint1/s1-3-teachback-endpoint` | 3-9 | Teachback endpoint (POST /api/assessment/teachback) + GPT-4o-mini scoring | `ee05080` | 2026-06-27 | `main` | MERGED → main |
| 4 | `sprint1/s1-1-quiz-endpoint-v2` | 3-8 | Quiz endpoint v2 — full BMAD re-impl (IDOR guard, CES×100 fix, Field(ge=0), no ID enumeration) | `b6460a7` | 2026-06-28 | `main` | MERGED → main |
| 5 | `sprint1/s1-15-bmad-process-docs` | 3-15 | BMAD process documentation (story-first gate evidence) | `2e703a8` | 2026-06-30 | `main` | CODE IN MAIN (squash merge) |
| 6 | `sprint1/s1-10-quiz-security-hardening-impl` | 3-10 | Quiz security hardening — implementation (rate-limit, payload validation) | `ffbcf3b` | 2026-06-30 | `main` | CODE IN MAIN (via blocker-fixes) |
| 7 | `sprint1/s1-14-rubric-labels` | 3-14 | Rubric label fields on teachback response (concepts_hit/missed) | `6ce9a8d` | 2026-06-30 | `main` | CODE IN MAIN (via blocker-fixes) |
| 8 | `sprint1/s1-10-quiz-security-hardening` | 3-10 | Quiz security hardening — story doc + final review fixes | `9e7f4f5` | 2026-07-01 | `main` | CODE IN MAIN (via blocker-fixes) |
| 9 | `sprint1/s1-11-teachback-security-hardening` | 3-11 | Teachback security hardening (IDOR, schema validation) | `dbde04d` | 2026-07-01 | `main` | CODE IN MAIN (via blocker-fixes) |
| 10 | `sprint1/s1-12-quiz-attempt-number-fix` | 3-12 | Quiz attempt_number DB fix (DEFAULT 1, UNIQUE constraint) | `a709682` | 2026-07-01 | `main` | CODE IN MAIN (via blocker-fixes) |
| 11 | `sprint1/s1-13-unique-attempt-constraints` | 3-13 | Unique attempt constraints migration (quiz + teachback) | `4444899` | 2026-07-01 | `main` | CODE IN MAIN (via blocker-fixes) |
| 12 | `dev3-sprint1-blocker-fixes` | 3-10..3-14 | Canonical blocker-fix branch — consolidated Stories 3-10..3-14 into main | `26ff3da` | 2026-07-01 | `main` | MERGED → main (FINAL) |
| 13 | `sprint1/s1-16-audit-fixes` | 3-16 | BMAD audit fixes (DPDP logging, injection guard, caplog tests) | `1d167cd` | 2026-07-02 | `main` | MERGED → main |
| 14 | `sprint1/s1-17-dpdp-user-consents` | 3-17 | DPDP user_consents audit table (new migration + consent endpoint) | `0da62b7` | 2026-07-02 | `main` | MERGED → main |

---

## Sprint 2 — Analytics & Learner DNA Read (Weeks 4–5)

**Stories:** 3-18 → 3-22 | 5 branches | Integration target: `master-sprint2-dev3`

> **Topology note:** dev3-sprint2-task2 has 1 unmerged tip commit (bce07a1) — content is in main via a separate squash PR (`sprint2/s2-doc-3-19-review-fix`). All other Sprint 2 branches follow a linear stack: task1 → task2 → task3 → task4 → task5. Tasks 3–5 diverged from task2's parent (split at `a4409c7`).

| Integration Order | Branch | Story | Purpose | Tip SHA | Date | Parent Branch | Status |
|:-----------------:|--------|-------|---------|---------|------|---------------|--------|
| 1 | `dev3-sprint2-task1` | 3-18 | CES session score write (ces_final → sessions table, Redis rolling avg) | `84c0e4e` | 2026-07-02 | `main` | MERGED → main |
| 2 | `dev3-sprint2-task2` | 3-19 | Session summary report endpoint (GET /session/{id}/report) | `bce07a1` | 2026-07-02 | `dev3-sprint2-task1` | ARCHIVED ⚠️ (1 unmerged tip; content in main via sprint2/s2-doc-3-19-review-fix) |
| 3 | `dev3-sprint2-task3` | 3-20 | Learner DNA EMA update (upsert per session, 9 dimensions) | `0d61fcb` | 2026-07-03 | `main` | MERGED → main |
| 4 | `dev3-sprint2-task4` | 3-21 | DNA dimensions analytics endpoint (GET /analytics/session/{id}/summary) | `040b4d5` | 2026-07-03 | `dev3-sprint2-task3` | MERGED → main |
| 5 | `dev3-sprint2-task5` | 3-22 | DNA badge labels + onboarding submit endpoint | `1b8617d` | 2026-07-03 | `dev3-sprint2-task4` | MERGED → main |

---

## Sprint 3 — CES Calibration & DNA Intelligence (Weeks 6–7)

**Stories:** 3-23 → 3-27 | 5 branches (Tasks 6–7 not yet started) | Integration target: `master-sprint3-dev3`

> **Topology note:** Sprint 3 is fully linear. Each task branch was stacked on the previous: task1 → task2 → task3 → task4 → task5. All five have been merged to main.

| Integration Order | Branch | Story | Purpose | Tip SHA | Date | Parent Branch | Status |
|:-----------------:|--------|-------|---------|---------|------|---------------|--------|
| 1 | `dev3-sprint3-task1` | 3-23 | CES formula (ces.py — formula + None redistribution + Redis window) | `6604092` | 2026-07-03 | `main` | MERGED → main |
| 2 | `dev3-sprint3-task2` | 3-24 | CES per-learner baseline (Redis cache, 5-session rolling avg, TTL) | `77ee8dc` | 2026-07-03 | `dev3-sprint3-task1` | MERGED → main |
| 3 | `dev3-sprint3-task3` | 3-25 | Learner DNA EMA fusion (dna_fusion.py — 0.7 retain × 0.3 new, 9 dimensions) | `59b6d0b` | 2026-07-03 | `dev3-sprint3-task2` | MERGED → main |
| 4 | `dev3-sprint3-task4` | 3-26 | DNA profile text generation (GPT-4o-mini, badge_labels, DPDP disclaimer) | `54d4ec2` | 2026-07-06 | `dev3-sprint3-task3` | MERGED → main |
| 5 | `dev3-sprint3-task5` | 3-27 | DNA growth tracking (dna_growth.py, delta per dimension, session_events write) | `9132cc0` | 2026-07-07 | `dev3-sprint3-task4` | MERGED → main |
| — | *(not started)* | 3-28 | Sprint 3 Task 6 — TBD | — | — | — | NOT STARTED |
| — | *(not started)* | 3-29 | Sprint 3 Task 7 — TBD | — | — | — | NOT STARTED |

---

## Integration Status

| Integration Branch | Based on | Sprint | Branches to Integrate | Current State |
|--------------------|----------|--------|-----------------------|---------------|
| `master-sprint1-dev3` | `sprint1/s1-9-post-lessons-endpoint` | Sprint 1 | 14 (integration order 1–14 above) | CREATED — integrations pending |
| `master-sprint2-dev3` | `sprint1/s1-9-post-lessons-endpoint` | Sprint 2 | 5 (integration order 1–5 above) | CREATED — integrations pending |
| `master-sprint3-dev3` | `sprint1/s1-9-post-lessons-endpoint` | Sprint 3 | 5 (integration order 1–5 above) | CREATED — integrations pending |

---

## Notes

- **ARCHIVED branches** — tip commit not in main, but code content is present via a different PR or squash. These branches are kept for historical reference only and should not be re-merged.
- **CODE IN MAIN (via blocker-fixes)** — code landed in main through `dev3-sprint1-blocker-fixes` rather than directly. The individual topic branches are reference points for what changed; they are not re-merged into the integration branch separately (only `dev3-sprint1-blocker-fixes` is).
- **Sprint 0** — no `master-sprint0-dev3` branch is needed. All Sprint 0 commits are in `main`, which is the ancestor of the integration base (`sprint1/s1-9-post-lessons-endpoint`). They are already present in all three integration branches.
- **Mixed commits** — Sprint 1–3 branches occasionally contain commits from other devs (Dev 2 frontend, lead dev merge commits) because they were branched from shared `main`. The integration branches capture the full branch tip, including those mixed commits.
