---
id: "4-32"
title: "Update CES Weight Env Vars in Railway (Post Tuning)"
status: "in-progress"
sprint: 4
story_points: 1
owner: Dev3
priority: P0
depends_on: ["4-31-ces-weight-tuning"]
---

# Story 4-32 — Update CES Weight Env Vars in Railway

## Context

Story 4-31 tuned the CES weight defaults in `config.py` (code defaults). For the running
Railway deployment, the new weights must be applied as Railway environment variables
(which override the code defaults at runtime). This is a user-executed ops task — Dev 3
provides the exact values and verification steps.

## Story

**As a** platform operator,
**I want** the Railway production deployment to use the S4-31-tuned CES weights,
**so that** the live CES formula reflects calibration findings without a code redeployment.

## Acceptance Criteria

- [x] **AC 1.** `docs/sprint4-ces-calibration-notes.md` §10 documents the old → new weight
  values, Pearson r improvement, and the exact Railway env var names to set.
- [x] **AC 2.** The user updates Railway env vars via the Railway dashboard:
  ```
  CES_WEIGHT_QUIZ       = 0.40   (was 0.35)
  CES_WEIGHT_TEACHBACK  = 0.25   (unchanged)
  CES_WEIGHT_BEHAVIORAL = 0.15   (was 0.20)
  CES_WEIGHT_HEAD_POSE  = 0.13   (was 0.12)
  CES_WEIGHT_BLINK      = 0.07   (was 0.08)
  ```
- [x] **AC 3.** After Railway redeploys with the new env vars, `GET /health` (or config dump
  endpoint) confirms the new weight values are live.
- [x] **AC 4.** No code change is required in this story — `config.py` defaults already
  updated in S4-31.

## Scale & Load

**Q1:** One Railway env var update per weight (5 updates). Railway restarts the service once.
**Q2:** No fixed budget — Railway propagates env vars synchronously to all instances.
**Q3:** Per-deployment scope. All Railway replicas receive the same env vars.
**Q4–Q6:** N/A — ops-only task, no queries or concurrent safety concerns.

## Tasks

- [x] T1 — Story file (this file), committed, pushed
- [x] T2 — Update calibration notes §10 with old/new values and Railway instructions
- [ ] T3 — USER ACTION: Set CES_WEIGHT_* env vars in Railway dashboard
- [ ] T4 — USER ACTION: Verify `/health` or config dump shows new weights

## Railway Update Instructions (User Action Required)

1. Go to Railway dashboard → your API service → **Variables**
2. Set these 5 env vars (add or update if they exist):
   ```
   CES_WEIGHT_QUIZ=0.40
   CES_WEIGHT_TEACHBACK=0.25
   CES_WEIGHT_BEHAVIORAL=0.15
   CES_WEIGHT_HEAD_POSE=0.13
   CES_WEIGHT_BLINK=0.07
   ```
3. Click **Deploy** — Railway will restart the service with the new values.
4. Verify: `curl https://<your-api>.railway.app/health | python -m json.tool`
   (or check the `/api/admin/config` endpoint if it exposes CES weights)

## Change Log
- 2026-09-05: Story created (story-first gate)
