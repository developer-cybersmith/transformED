# Sprint 4 — CES Calibration Notes
**Author:** Dev 3 (tannmayygupta)  
**Date:** 2026-08-29  
**Supabase project:** CSS_HIE (`xjypglfmjunmlccbhjgn`)  
**Data snapshot:** 117 sessions, 2 users, collected 2026-08-12 → 2026-08-19

---

## 1. Data Inventory

| Table | Row count | Usable for calibration |
|---|---|---|
| sessions | 117 | 4 completed (ended_at ≠ NULL) |
| quiz_attempts | 55 | Yes — across 11 distinct sessions |
| teachback_attempts | 2 | Minimal — both from 1 session |
| session_events | 58 | Partial — intervention + tab_switch only |
| learner_dna | — | Not queried — onboarding not focus here |

---

## 2. Critical Bug: `ces_final` is Always NULL

**All 4 completed sessions have `ces_final = NULL`.** This blocks any CES calibration.

### Root cause

There are **two separate code paths** for ending a session:

| Path | Writer | What it writes |
|---|---|---|
| `POST /api/assessment/sessions/{id}/end` | `assessment/service.py:257` | `ended_at` only |
| Tutor FSM → SESSION_END state | `tutor/state_machine/graph.py:758` | `ces_final` + `ended_at` |

The assessment endpoint is being called (all 4 sessions have `ended_at`), but the tutor FSM's SESSION_END transition is never completing — either the WebSocket is dropping before SESSION_END fires, or the FSM never reaches that state in these short test sessions.

Even when `_finalize_session` does run, it reads Redis `ces_history`. If no CES updates were pushed via WebSocket during the session, `ces_history` is empty → `ces_final = None` → stored as NULL. Same result.

**Owner:** Dev 4 (WebSocket handlers, Redis buffer, SESSION_END trigger).  
**Action before next session run:** Confirm the SESSION_END WebSocket message is being sent and received. Log `ces_history` length at finalize time.

---

## 3. Quiz Signal — Usable Data

### Per-session accuracy

| session_id (truncated) | attempts | accuracy | avg response (ms) |
|---|---|---|---|
| a0936535 | 20 | **95%** | 19,161 (deliberate) |
| 9d354d23 | 6 | 50% | 3,021 (fast) |
| ef67d6b8 | 4 | 50% | 8,949 |
| 1caaa2a4 | 4 | 50% | 19,738 |
| 4d25aa2b | 4 | 50% | 8,247 |
| 1af8fc45 | 4 | 50% | 3,178 |
| 15cef4b2 | 4 | **25%** | 4,364 |
| 002c64bf | 3 | 33% | 3,027 |
| 89338fb8 | 2 | 100% | 3,119 |
| a5c4119d | 2 | 100% | 5,775 |
| ef03c4d8 | 2 | 100% | 2,924 |
| **Aggregate** | **55** | **69%** | — |

### Observations

- **Overall quiz accuracy is 69%.** This is test-session data from developers, not real students. Expect lower accuracy (50–60%) from actual students unfamiliar with content.
- **Session `a0936535` is an outlier**: 20 attempts, 95% accuracy, 19s avg response. This is the only session with teachback data. It is a full walkthrough session — usable as a positive CES exemplar once ces_final is fixed.
- **Sessions with 2 attempts at 100%**: too short to draw conclusions — likely abandoned early.
- **Sessions with 4 attempts at 50%**: clustered — this is likely the default quiz-per-segment count. 50% accuracy consistently suggests either moderately difficult content or rushed answering.
- **Response time range: 3s–20s.** The CES formula uses `quiz_accuracy` (not response time) directly, but extreme response times (< 1s) could indicate random clicking. Min floor of 500ms should be applied in the frontend before submitting.

### CES formula implication

`quiz_accuracy × 0.35` at 69% → contributes **24.2 points** to CES.  
At the CES trigger threshold of 50, this means the remaining 4 signals must contribute ≥ 25.8 points. With behavioral + head_pose + blink all at zero (signals not being received), CES will always fall below 50 → perpetual intervention loop.

---

## 4. Teachback Signal — Insufficient

Only **2 teachback attempts**, both from session `a0936535`:
- Score: 92 (pass)
- Score: 73 (pass)

Not enough to calibrate `teachback_score × 0.25`. Both scores were above the implicit pass threshold. Cannot determine where the distribution sits for real students.

---

## 5. Behavioral Events — Intervention Rate

| event_type | total | distinct sessions |
|---|---|---|
| intervention_triggered | 26 | 14 |
| tab_switch | 26 | 15 |
| jargon_hover | 6 | 3 |

### Observations

- **1:1 ratio of tab_switch to intervention_triggered** strongly suggests tab_switch events are the primary CES trigger. If each tab_switch drops behavioral score enough to push CES below 50, the system is over-sensitive.
- 26 interventions across 14 sessions = ~1.9 interventions per session average. The CLAUDE.md rule is **max 3 per session**. We're near that cap on almost every session.
- No `quiz_fail`, `segment_complete`, `lesson_end`, or any other event types exist in the DB. This means the session event log is only capturing attention/intervention events — quiz results flow through `quiz_attempts`, not `session_events`.

### CES formula implication

If behavioral signal is entirely absent (only attention signals arriving sporadically), then:
```
CES ≈ quiz_accuracy×0.35 + 0 + head_pose×0.12 + blink×0.08
```
Maximum possible CES = 0.35 + 0.12 + 0.08 = **0.55 × 100 = 55** if all three at perfect score.

A student with 70% quiz accuracy and perfect attention signals → CES ≈ 0.35×70 + 0.12×100 + 0.08×100 = 24.5 + 12 + 8 = **44.5** → below the 50 threshold → perpetual intervention.

**This explains the high intervention rate.** The behavioral component (weight 0.20) is not being sent from the frontend or is not reaching the CES formula. Without it, almost any student will trigger interventions.

---

## 6. Session Lifecycle Bugs

### Bug A: `ces_final` never written (CRITICAL)

Described in §2. Blocks all CES calibration. Dev 4 must investigate SESSION_END trigger.

### Bug B: Duplicate session creation

4 cases of sessions created at identical millisecond timestamps for the same user/lesson:

| duplicate pair timestamp | sessions |
|---|---|
| 2026-08-14 13:14:20.608 | 2 |
| 2026-08-12 13:12:39.808 | 2 |
| 2026-08-12 12:55:28.480 | 2 |
| 2026-08-12 10:47:36.414 | 2 |

**Likely cause:** React StrictMode double-renders `useEffect` in dev mode, causing two concurrent `POST /api/sessions` calls. The `(chapter_id, tier)` idempotency constraint (flagged as D45 in `docs/DEFECT-REGISTER.md`) also applies here — there is no UNIQUE constraint on `(user_id, lesson_id, started_at)` so both inserts succeed.

**Impact:** Quiz attempts may split across the two duplicate session IDs, fragmenting the signal. Low severity for calibration but should be fixed before real-student data collection.

---

## 7. What We Cannot Calibrate Yet

| Signal | Status |
|---|---|
| `quiz_accuracy × 0.35` | Partial — 69% aggregate, but only developer data |
| `teachback_score × 0.25` | Blocked — 2 samples, no distribution |
| `behavioral × 0.20` | Blocked — signal not reaching formula |
| `head_pose × 0.12` | Blocked — no attention data in DB |
| `blink × 0.08` | Blocked — no attention data in DB |
| **CES threshold (50)** | Unvalidatable — ces_final always NULL |

---

## 8. Prerequisite Fixes Before 20-Session Run

Before running 20 calibration sessions, these must be resolved:

1. **Dev 4: Fix SESSION_END → `_finalize_session` path.** Confirm ces_final is written after a normal lesson completion. Add a log line at `_finalize_session` entry showing `ces_history` length.

2. **Dev 2/Dev 4: Confirm behavioral signal WebSocket messages are being sent.** The CES formula needs `behavioral` score updates from the frontend. If the WebSocket message type for behavioral score isn't being emitted, behavioral weight is dead.

3. **Dev 3 (this task): Verify CES update endpoint is wired.** Check if `POST /api/assessment/sessions/{id}/ces` or equivalent is being called during sessions to push intermediate CES values into Redis.

4. **Minor: Fix duplicate session creation.** Either debounce the session start call on the frontend, or add a DB-level unique constraint (new migration) on `(user_id, lesson_id)` where `ended_at IS NULL`.

---

## 9. Calibration Baseline (Provisional — Developer Data Only)

These numbers are from 2 users running internal tests. Treat as directional only.

| Metric | Observed |
|---|---|
| Quiz accuracy (aggregate) | 69% |
| Avg quiz response time | 3–20s (high variance) |
| Teachback completion rate | ~10% of sessions that have quiz data |
| Teachback scores | 73, 92 (both pass) |
| Intervention rate | ~1.9 per session with data |
| Typical session duration | 2.4–2.9 min (very short — likely dev testing, not full lessons) |
| ces_final | NULL on all sessions — formula output unobservable |

**Recommended CES threshold for initial real-student calibration:** Keep at 50 but do not trigger interventions if `behavioral` score has not been received (is NULL/unknown). A "partial signal" mode prevents intervention spam when 2 of 5 signals are absent.
