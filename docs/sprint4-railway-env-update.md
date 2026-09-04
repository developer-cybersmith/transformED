# Sprint 4 — Railway CES Weight Env Var Update Runbook
**Author:** Dev 3 (tannmayygupta)  
**Date:** 2026-09-05  
**Story:** S4-32 — Update tuned CES weights in Railway env vars  
**Applies to:** Production Railway deployment (API service + ARQ worker)

---

## Prerequisites

Complete ALL of the following before applying:

- [ ] Story S4-31 merged to main — provisional weights confirmed in `apps/api/app/config.py`
- [ ] Story S4-30 calibration run completed — at least 10 sessions with `ces_final IS NOT NULL`
- [ ] D116 fix (Story S4-6) confirmed live in production — check Supabase: `SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL AND ces_final IS NOT NULL`
- [ ] Dev 2's PR #161 (`?? null` fix in `useAttentionMonitor.ts`) merged and deployed
- [ ] Pearson r from `ces_weight_grid_search.py` confirms these weights outperform defaults (target: > 0.6)

If Pearson r target is not met with real data, keep the original defaults and open a new story for further tuning.

---

## Env Vars to Update

Apply these in the Railway dashboard under **Settings → Environment Variables** for BOTH the `api` service and the `worker` service:

| Variable | Old value | New value | Notes |
|----------|-----------|-----------|-------|
| `CES_WEIGHT_QUIZ` | 0.35 | **0.40** | Strongest calibrated signal |
| `CES_WEIGHT_TEACHBACK` | 0.25 | **0.25** | No change — insufficient calibration data |
| `CES_WEIGHT_BEHAVIORAL` | 0.20 | **0.15** | Reduced: 1:1 tab-switch:intervention over-trigger |
| `CES_WEIGHT_HEAD_POSE` | 0.12 | **0.13** | Minor adjustment to maintain sum=1.0 |
| `CES_WEIGHT_BLINK` | 0.08 | **0.07** | Minor adjustment to maintain sum=1.0 |

**Sum check:** 0.40 + 0.25 + 0.15 + 0.13 + 0.07 = **1.00** ✓

> If Railway does not have any `CES_WEIGHT_*` env vars set, the code defaults in
> `apps/api/app/config.py` (from Story S4-31) will take effect automatically on the
> next deploy. In that case, only set env vars if you need to OVERRIDE the S4-31 defaults.

---

## How to Apply

### Railway Dashboard (preferred)

1. Go to [https://railway.app](https://railway.app) → your project → **api** service
2. Click **Settings** → **Environment Variables**
3. Add or update each variable from the table above
4. Click **Deploy** (Railway auto-deploys on env var save)
5. Repeat for the **worker** service (ARQ worker must have the same weights)

### Railway CLI (alternative)

```bash
railway variables set CES_WEIGHT_QUIZ=0.40
railway variables set CES_WEIGHT_TEACHBACK=0.25
railway variables set CES_WEIGHT_BEHAVIORAL=0.15
railway variables set CES_WEIGHT_HEAD_POSE=0.13
railway variables set CES_WEIGHT_BLINK=0.07
```

---

## Verification

After deployment, run the verification script:

```bash
# Requires API to be accessible (local dev or production URL)
python apps/api/scripts/verify_ces_weights.py \
    --api-url https://your-api.railway.app \
    --auth-token <your-jwt-token>
```

Expected output:
```
CES weight verification
-----------------------
ces_weight_quiz:       0.40  ✓
ces_weight_teachback:  0.25  ✓
ces_weight_behavioral: 0.15  ✓
ces_weight_head_pose:  0.13  ✓
ces_weight_blink:      0.07  ✓
Sum: 1.00  ✓
All weights match S4-31 targets.
```

Exit code 0 = verification passed.

Alternatively, check the startup logs in Railway for:
```
INFO: CES weights loaded — quiz=0.40 teachback=0.25 behavioral=0.15 head_pose=0.13 blink=0.07
```
(If this log line is not present, the app is not logging weights at startup — add it in a follow-on story.)

---

## Rollback

If CES behavior degrades after the weight change (intervention rate spikes or drops
unexpectedly):

1. Railway dashboard → **api** service → **Settings** → **Environment Variables**
2. Restore:

| Variable | Rollback value |
|----------|---------------|
| `CES_WEIGHT_QUIZ` | 0.35 |
| `CES_WEIGHT_TEACHBACK` | 0.25 |
| `CES_WEIGHT_BEHAVIORAL` | 0.20 |
| `CES_WEIGHT_HEAD_POSE` | 0.12 |
| `CES_WEIGHT_BLINK` | 0.08 |

3. Deploy. The `@model_validator` in `config.py` will validate the sum=1.0 invariant at
   startup and raise if any combination is invalid.

---

## Evidence trail

- Calibration data source: `docs/sprint4-ces-calibration-notes.md` §9–§10
- Weight selection rationale: `docs/sprint4-ces-calibration-notes.md` §10 (behavioral over-trigger evidence)
- Grid search script: `apps/api/scripts/ces_weight_grid_search.py`
- Config defaults: `apps/api/app/config.py` (ces_weight_* fields)
