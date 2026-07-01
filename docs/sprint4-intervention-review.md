# Sprint 4 — Intervention Response Review (methodology / pending data)

**Owner:** Dev 4 · **Task:** `intervention_response_review` · **Status:** ⏳ **METHODOLOGY ONLY — pending data + instrumentation**
**Last updated:** 2026-06-30

> Analysis plan + query templates, ready to run once interventions and acknowledgements are logged and real
> sessions exist. No acknowledgement rates are fabricated.

---

## Objective (AC)

Compute the **acknowledgement rate per intervention type** (`distraction | confusion | fatigue`) and flag any
type with **< 50% ack rate** for message-copy revision.

---

## ⚠️ Blocking prerequisite (instrumentation gap — must be built first)

Today, **neither intervention fires nor acknowledgements are persisted**:

- Intervention firing updates only Redis counters (`tutor_distraction_count`, `tutor_fatigue_fired`,
  `tutor_cooldown`) and delivers a `tutor_intervene` WS message. **No `session_events` row is written.**
- There is **no `intervention_acknowledged` inbound message or handler** — the analytics `event_type` enum
  is `head_pose | blink_rate | attention_signal | page_view | pause | resume` (`analytics/router.py:26`);
  intervention ack is not among them, and the WS endpoint has no such branch.

**Before this review can run, add (small, well-scoped):**
1. On intervention fire (`process_attention_signal` / `intervening_node` delivery), write
   `session_events(event_type='intervention', payload={type, segment_index, message, ts})`.
2. A client → server `intervention_acknowledged` message (dismiss/engage tap) → write
   `session_events(event_type='intervention_acknowledged', payload={type, intervention_ts})`.

These are flagged as a follow-up instrumentation story (Dev 4 + Dev 2 for the client tap).

---

## Method (once instrumented + ≥1 real cohort)

1. Pull all `intervention` and `intervention_acknowledged` events.
2. Match each ack to its preceding `intervention` (same `session_id`, nearest prior intervention of that
   `type` within a sensible window, e.g. ≤ 60 s).
3. `ack_rate[type] = acked_interventions[type] / fired_interventions[type]`.
4. Flag any type with `ack_rate < 0.50` → propose copy revision (hand off to `intervention_copy_review` +
   Dev 1, the pipeline/message owner).

### Query templates (fill once instrumented)

```sql
-- Interventions fired, by type.
select payload->>'type' as type, count(*) as fired
from session_events
where event_type = 'intervention'
group by 1;

-- Acknowledged, by type.
select payload->>'type' as type, count(*) as acked
from session_events
where event_type = 'intervention_acknowledged'
group by 1;

-- Ack rate by type (after the above are populated).
select f.type,
       f.fired,
       coalesce(a.acked, 0) as acked,
       round(coalesce(a.acked,0)::numeric / nullif(f.fired,0), 3) as ack_rate
from (select payload->>'type' type, count(*) fired
      from session_events where event_type='intervention' group by 1) f
left join (select payload->>'type' type, count(*) acked
           from session_events where event_type='intervention_acknowledged' group by 1) a
  on a.type = f.type;
```

---

## Results

⏳ **PENDING** — blocked on (a) the intervention/ack instrumentation above and (b) real sessions (production
deploy). Populate the per-type ack-rate table + the ≥1 flagged type here once both exist. No rates invented.
