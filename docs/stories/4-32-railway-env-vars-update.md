---
id: "4-32"
title: "Update CES Weights in Railway Env Vars"
status: "ready-for-dev"
sprint: 4
story_points: 1
owner: Dev3
priority: P1
depends_on: ["4-31-ces-weight-tuning"]
---

# Story 4-32 — Update Tuned Weights in Railway Env Vars

## Context

Story 4-31 applied provisional CES weights to `apps/api/app/config.py` defaults. Those
defaults are overridden in production by Railway environment variables (`CES_WEIGHT_*`).
This story produces the runbook for applying the tuned weights as Railway env vars so
the production instance uses the calibrated weights, not the old PRD §11 defaults.

Dev 3 cannot apply Railway env vars directly — only the platform operator (team lead
or DevOps) can do that. The deliverable is a runbook document + a local validation script.

## Story

**As a** platform operator,
**I want** a clear runbook documenting which Railway env vars to update and to what values,
**so that** the CES weight tuning from Story 4-31 takes effect in the production deployment
without me having to guess the correct values.

## Acceptance Criteria

- [x] **AC 1.** `docs/sprint4-railway-env-update.md` runbook created with:
  - List of all 5 `CES_WEIGHT_*` env var names and their new values
  - Verification step: how to confirm the change took effect (log line or API response)
  - Rollback instructions: old values to restore if CES behavior degrades
  - Prerequisites checklist (calibration notes §10 run completed, D116 live)

- [x] **AC 2.** `apps/api/scripts/verify_ces_weights.py` validation script:
  - Reads the Railway-set env vars via `GET /api/health` or config endpoint
  - Prints current CES weight values and whether they match the S4-31 targets
  - Exit code 0 = weights correct, 1 = mismatch, 2 = can't connect

- [x] **AC 3.** `apps/api/app/config.py` already has the correct `Field(default=...)` values
  from Story 4-31 — no additional config.py change required.

- [x] **AC 4.** `pytest tests/test_ces.py -v` — still GREEN (no formula changes, only runbook).

## Scale & Load

**Q1 — Unit of work:** One env var update in Railway dashboard = instant propagation to all
replicas. No data migration. No code change beyond the runbook document.

**Q2 — Fixed budgets:** N/A — no LLM calls, no database writes, no file size limits.

**Q3 — Scope:** Railway env vars are per-deployment (not per-user). Change propagates to all
instances simultaneously on Railway's next deploy or env var refresh.

**Q4 — Unbounded:** N/A — no Supabase reads or writes.

**Q5 — Inherited caps:** The 5-weight constraint (sum = 1.0) is enforced in `config.py` via
`@model_validator` — if Railway values are set incorrectly, the validator raises at startup.

**Q6 — TOCTOU:** N/A — env var update is atomic in Railway dashboard.

## Tasks

- [x] T1 — Story file (this file), committed, pushed (story-first gate)
- [x] T2 — Write `docs/sprint4-railway-env-update.md` runbook
- [x] T3 — Write `apps/api/scripts/verify_ces_weights.py` validation script
- [x] T4 — Write unit tests for verify script (≥ 5 tests)
- [x] T5 — Run `pytest tests/test_ces.py` — confirm still GREEN
- [x] T6 — Commit + push + PR

## Change Log
- 2026-09-05: Story created (story-first gate)
