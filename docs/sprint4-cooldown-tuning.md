# Sprint 4 — Intervention Cooldown Tuning (methodology / pending data)

**Owner:** Dev 4 · **Task:** `cooldown_tuning` · **Status:** ⏳ **METHODOLOGY ONLY — pending data + instrumentation**
**Last updated:** 2026-06-30

> Analysis plan + decision rule, ready to run once intervention timestamps are logged and real sessions
> exist. No timing numbers are fabricated.

---

## Objective (AC)

Analyse the time between consecutive interventions in real sessions. **If the average inter-intervention
time < 4 minutes, increase `INTERVENTION_COOLDOWN_SECONDS`** (currently `120` = 2 min). Update the env var
and document the change with the data rationale.

Current config (`config.py`): `intervention_cooldown_seconds = 120`. The cooldown is a Redis TTL key
(`tutor_cooldown:{sid}`) checked by `_can_intervene_distraction`.

---

## ⚠️ Prerequisite (instrumentation gap)

Inter-intervention timing needs **per-intervention timestamps**, which are **not persisted** today (only the
Redis cooldown/counter keys). This depends on the same instrumentation as `intervention_response_review`:
write `session_events(event_type='intervention', payload={type, ts})` on each fire. See
`docs/sprint4-intervention-review.md`.

---

## Method (once instrumented + real sessions)

1. Pull `intervention` events ordered by `(session_id, created_at)`.
2. Within each session, compute deltas between consecutive interventions (`LEAD/LAG`).
3. Report the **mean** and **distribution** (p50/p90) of inter-intervention gaps.
4. **Decision:** if mean gap `< 240 s`, raise `INTERVENTION_COOLDOWN_SECONDS` (candidate: to the value that
   pushes the p50 gap comfortably above the cooldown, e.g. 180–240 s) so interventions don't cluster and
   feel naggy. If mean gap `≥ 240 s`, keep 120 s and record that it was validated.

### Query template (fill once instrumented)

```sql
-- Inter-intervention gaps (seconds) within each session.
with iv as (
  select session_id, created_at,
         lag(created_at) over (partition by session_id order by created_at) as prev_at
  from session_events
  where event_type = 'intervention'
)
select session_id,
       extract(epoch from (created_at - prev_at)) as gap_seconds
from iv
where prev_at is not null
order by session_id, created_at;

-- Cohort summary.
with gaps as ( /* the gap_seconds query above */ )
select count(*)                                   as n_gaps,
       round(avg(gap_seconds))                    as mean_gap_s,
       percentile_cont(0.5) within group (order by gap_seconds) as p50_gap_s,
       percentile_cont(0.9) within group (order by gap_seconds) as p90_gap_s
from gaps;
```

---

## Decision rule & rollout

- Change is **env-var only** (`INTERVENTION_COOLDOWN_SECONDS` on Railway / the India-region host) — no code
  change. Record old → new + the mean/p50 gap that justified it.
- Interacts with the **max-3-distraction cap** and **fatigue-once** guards: confirm the new cooldown doesn't
  combine with the cap to silence interventions for a learner who genuinely needs them (check the per-session
  fired-count distribution alongside the gaps).

---

## Results

⏳ **PENDING** — blocked on intervention-timestamp instrumentation + real sessions (production deploy).
Populate the mean/p50/p90 gap table + the cooldown decision here once data exists. No timings invented.
