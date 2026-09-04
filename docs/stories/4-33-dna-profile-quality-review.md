---
id: "4-33"
title: "Learner DNA Profile Quality Review"
status: "ready-for-dev"
sprint: 4
story_points: 2
owner: Dev3
priority: P1
depends_on: []
---

# Story 4-33 — Learner DNA Profile Quality Review

## Context

`learner_dna.profile_text` values are LLM-generated descriptions of a student's learning
style. The CLAUDE.md non-negotiable rules require:
- No clinical claims (no IQ / EQ / SQ language)
- No raw numeric dimension scores shown to students
- Every `profile_text` ends with the DPDP Act 2023 disclaimer
- `badge_labels` use plain English (e.g. "Pattern Thinker", not "IQ: High")
- Tone is encouraging, not diagnostic

This story delivers a review script that checks these invariants on real (or sample)
Learner DNA profiles, produces a structured checklist report, and documents any
prompt fixes needed.

## Story

**As a** Dev 3 (quality engineer),
**I want** to run an automated quality checklist against at least 10 Learner DNA profiles
and document any violations with their fixes,
**so that** real-student data is not contaminated with clinical language, raw scores, or
missing DPDP disclaimers before launch.

## Acceptance Criteria

- [x] **AC 1.** `apps/api/scripts/review_dna_profiles.py` — standalone script:
  - Reads `learner_dna` rows from Supabase (service-role key) OR from a local JSON fixture
  - For each profile: runs 5 checklist rules (no_clinical, no_raw_scores, has_dpdp,
    encouraging_tone, plain_badge_labels)
  - Outputs: CSV report with one row per profile per rule (pass/fail/warn)
  - Exits 0 if all rules pass, 1 if any fail

- [x] **AC 2.** 5 checklist rules implemented and documented:
  1. `no_clinical` — profile_text contains none of: IQ, EQ, SQ, clinical, diagnos*, disorder
  2. `no_raw_scores` — profile_text contains no patterns matching `\d+/\d+` or `score: \d`
  3. `has_dpdp` — profile_text ends with the DPDP Act 2023 disclaimer substring
  4. `encouraging_tone` — profile_text does NOT contain: "struggle", "fail", "weak", "poor"
  5. `plain_badge_labels` — badge_labels (if present) contain no ":" character (e.g. "IQ: High" fails)

- [x] **AC 3.** At least 10 sample Learner DNA profiles reviewed — either real Supabase data
  or a local fixture file (`apps/api/tests/fixtures/sample_dna_profiles.json`) with 10+ entries.
  Results documented in `docs/sprint4-dna-quality-review.md`.

- [x] **AC 4.** Script has no `from app.*` imports (standalone).

- [x] **AC 5.** Unit tests: `apps/api/tests/test_s4_33_dna_review.py` with ≥ 10 tests
  covering each checklist rule (pass + fail cases).

- [x] **AC 6.** Guard tests `pytest tests/unit/test_unbounded_queries.py
  tests/unit/test_node_return_shape.py` — GREEN (no changes to guarded modules).

## Scale & Load

**Q1 — Unit of work:** One profile_text review = 5 regex/substring checks. N profiles ≤ 10,000
(bounded by `--limit` CLI arg). Local fixture is bounded by file size.

**Q2 — Fixed budgets:** Supabase read bounded with `.limit(10_000)` + signals_capped warning.
No LLM calls — all checks are regex/substring only.

**Q3 — Scope:** Review runs locally, not on Railway. No per-user / per-instance impact.

**Q4 — Unbounded:** All Supabase reads carry `.limit()`. Local fixture: entire file is
loaded into memory — max practical size is the file the developer creates.

**Q5 — Inherited caps:** N/A — new script.

**Q6 — TOCTOU:** N/A — read-only review, no writes.

## Tasks

- [x] T1 — Story file committed, pushed (story-first gate)
- [x] T2 — Write `apps/api/scripts/review_dna_profiles.py`
- [x] T3 — Write `apps/api/tests/fixtures/sample_dna_profiles.json` (10 profiles, 5 pass + 5 with intentional violations)
- [x] T4 — Write `apps/api/tests/test_s4_33_dna_review.py` (≥ 10 tests)
- [x] T5 — Run review against fixtures; document results in `docs/sprint4-dna-quality-review.md`
- [x] T6 — Commit + push + PR

## Change Log
- 2026-09-05: Story created (story-first gate)
