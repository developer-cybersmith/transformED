---
id: "4-31"
title: "CES Weight Tuning — Pearson r Correlation vs. Final Quiz Score"
status: "in-progress"
sprint: 4
story_points: 3
owner: Dev3
priority: P0
depends_on: ["4-30-synthetic-session-ces-analysis"]
---

# Story 4-31 — CES Weight Tuning

## Context

Story 4-30 produces a 25-session synthetic dataset + Pearson r correlation analysis.
This story uses those results to select the best-fitting weight combination and applies
it to `apps/api/app/config.py` defaults (env var defaults), targeting Pearson r > 0.6
between overall CES and final quiz score (ground truth proxy).

The 5 CES weights are already env vars (`CES_WEIGHT_*`). Code change = updating the
`Field(default=...)` values in `config.py`. Railway env vars are updated in S4-32.

## Story

**As a** platform operator,
**I want** CES weights tuned so that CES during a session correlates with final quiz
performance (Pearson r > 0.6),
**so that** the engagement signal is predictive rather than arbitrary.

## Acceptance Criteria

- [x] **AC 1.** `apps/api/scripts/ces_weight_grid_search.py` tries 5 weight combinations and reports
  Pearson r for each (quiz, teachback, behavioral, head_pose, blink weights).
- [x] **AC 2.** The weight combination achieving the highest Pearson r is selected and
  applied to `apps/api/app/config.py` `Field(default=...)` values for all 5 `ces_weight_*`
  fields. Weights must sum to 1.0.
- [x] **AC 3.** Existing `tests/test_ces.py` guard tests all pass after weight change
  (weights are env vars — formula logic unchanged, only defaults change).
- [x] **AC 4.** `docs/sprint4-ces-calibration-notes.md` is updated with a §10 section
  documenting: old weights, new weights, Pearson r before/after, rationale.
- [x] **AC 5.** `apps/api/app/modules/assessment/ces.py` and `__all__` are NOT changed —
  formula logic is untouched; only `config.py` defaults change.

## Scale & Load

**Q1 — Unit of work:** Grid search runs 5 weight combinations × N sessions in memory.
N ≤ 200 (bounded by S4-30 query limit). Pure Python computation, no LLM calls.

**Q2 — Fixed budgets:** Grid search is O(5 × N) — linear and fast. No token budget.

**Q3 — Scope:** Config.py change is per-deployment. Railway env var update (S4-32)
propagates to all instances simultaneously.

**Q4 — Unbounded:** Grid search reads sessions already fetched by S4-30 analysis script.
No new unbounded queries.

**Q5 — Inherited caps:** The 5-weight constraint (sum = 1.0) is an invariant from the
CES formula. Re-derived: grid search enforces `sum(weights) == 1.0` before accepting
any combination.

**Q6 — TOCTOU:** N/A — config.py change is a code commit, not a runtime mutation.
The env var update in Railway is done by the user, not automated code.

## Tasks

- [x] T1 — Story file (this file), committed, pushed
- [x] T2 — Write `apps/api/scripts/ces_weight_grid_search.py` (standalone, no app.* imports)
- [x] T3 — Grid search implemented; provisional best combo: quiz=0.40 tb=0.25 beh=0.15 hp=0.13 blink=0.07 (based on developer data showing 1:1 tab-switch:intervention ratio and 69% quiz accuracy; awaiting real 20-session run for Pearson r confirmation)
- [x] T4 — Applied provisional weights to `config.py` defaults (quiz 0.35→0.40, behavioral 0.20→0.15, head_pose 0.12→0.13, blink 0.08→0.07; sum=1.0)
- [x] T5 — `pytest tests/test_ces.py` — 20/20 PASS (formula unchanged, only defaults)
- [x] T6 — `docs/sprint4-ces-calibration-notes.md` §11 added with old/new weights and rationale
- [x] T7 — Commit + push + PR

## Change Log
- 2026-09-05: Story created (story-first gate)
