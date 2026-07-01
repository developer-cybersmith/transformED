# Sprint 4 — CES Threshold Analysis (methodology / pending data)

**Owner:** Dev 4 · **Task:** `threshold_tuning` · **Status:** ⏳ **METHODOLOGY ONLY — pending ≥20 real sessions**
**Last updated:** 2026-06-30

> This document is the **analysis plan + query templates + decision rule**, ready to execute once real
> session data exists. The "Results" section is intentionally empty — **no numbers are fabricated.**

---

## Objective (AC)

Validate whether `CES_THRESHOLD = 50` is the right intervention trigger point. Find the threshold where
**sensitivity (true interventions) > 70%** and **false-positive rate < 20%**, and propose an updated value
with data backing.

Current config (`config.py`): `ces_threshold = 50.0` on the **0–100** scale; weights
`quiz .35 / teachback .25 / behavioral .20 / head_pose .12 / blink .08` (§11). Trigger fires when **2
consecutive 5 s windows** are `< threshold`.

---

## Data sources (real schema)

| Need | Source | Note |
|------|--------|------|
| Per-window attention components | `attention_events` (`gaze_score, head_pose_score, blink_rate, behavioral_score, created_at`) | raw signals **are** persisted per window |
| Per-window **CES** | — | **NOT persisted** — `tutor_ces` / `ces_history` are Redis keys (24 h TTL) |
| Per-session final CES | `sessions.ces_final` | one value/session |
| Post-session outcome | `quiz_attempts (is_correct)`, `teachback_attempts (score)` | the ground-truth "did they actually learn" signal |

### ⚠️ Prerequisite (instrumentation gap)

Per-window CES is **not durably stored** (Redis-only). Two options before this analysis can run:

1. **Recompute** CES per window from `attention_events` using the §11 formula (`compute_ces`) — the raw
   components are persisted, so historical CES is reconstructable **except** for `quiz_accuracy` /
   `teachback_score`, which are not in `attention_events` (they'd need joining from `quiz_attempts` /
   `teachback_attempts` by timestamp window). Cleanest near-term path.
2. **Persist** each computed CES going forward (e.g. write `session_events(event_type='ces_window',
   payload={ces, ts})` from `process_attention_signal`). Recommended for clean future analyses.

Pick one and note it here before collecting the 20-session sample.

---

## Method

1. Collect **≥20 real sessions** (mix of engaged + disengaged learners).
2. For each session, build the per-window CES time series (recompute or logged) + label each window's
   "true engagement" using the proximate outcome (next quiz correctness / teach-back score as proxy).
3. Sweep candidate thresholds `T ∈ {40, 45, 50, 55, 60}`:
   - **sensitivity** = (# correctly-fired interventions) / (# windows that *should* have fired)
   - **false-positive rate** = (# fired on genuinely-engaged windows) / (# engaged windows)
4. Pick the T that satisfies sensitivity > 70% **and** FPR < 20% with the best margin; if none, report the
   ROC trade-off and recommend the closest.

### Query templates (Supabase SQL — fill once data exists)

```sql
-- Per-window attention components for a session, time-ordered (recompute CES from these).
select created_at, behavioral_score, head_pose_score, blink_rate
from attention_events
where session_id = :sid
order by created_at;

-- Post-session outcome proxy: quiz accuracy per session.
select session_id,
       avg(case when is_correct then 1.0 else 0.0 end) as quiz_accuracy
from quiz_attempts
group by session_id;

-- Final CES vs outcome across the cohort (session-level sanity scatter).
select s.session_id, s.ces_final, q.quiz_accuracy
from sessions s
join (select session_id, avg((is_correct)::int::float) quiz_accuracy
      from quiz_attempts group by session_id) q using (session_id)
where s.ended_at is not null;
```

---

## Decision rule & rollout

- If the analysis supports a different T, change **`CES_THRESHOLD`** via env var only (no code change —
  `settings.ces_threshold`). Document old → new + the sensitivity/FPR that justified it.
- Re-check the **2-consecutive-window** rule: if FPR is driven by single-window dips, the consecutive-window
  guard may already be doing the smoothing — note its contribution separately.

---

## Results

⏳ **PENDING — requires ≥20 real sessions.** Real-student data depends on the production deploy (India-region
migration — Sprint-3 prerequisite per CLAUDE.md). Populate the threshold sweep table + the proposed
`CES_THRESHOLD` here once the cohort exists. No results are invented.
