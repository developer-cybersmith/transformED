# Dev 4 — Lesson Delivery handoff

**Sprint goal:** one student, one complete lesson, generated from one real book.
**Your phases:** **L5** (CES, with Dev 3) · **L7** (interventions fire *and recover*)
**Master doc:** `docs/LESSON-DELIVERY-TRACKER.md`

> **Naming, once.** This sprint is often called "video generation". What we ship is the **narrated
> interactive lesson**; a compiled MP4 is re-watch-only and out of scope. Your tutor machine and
> interventions only exist in the interactive mode — see the tracker §0.

---

## Your one-line status

**The FSM is the best-built thing in this sprint** — all 7 states real, all 5 guard rules
implemented. It also contains one defect that will silently disable CES for a whole session the
first time an intervention fires, and that must land **before** Dev 2's MediaPipe work, not after.

---

## What is already right — credit where due

| Guard (CLAUDE.md §10) | Where | State |
|---|---|---|
| CES monitored only in TEACHING | `service.py:325` + `route_from_teaching` | enforced |
| 2-minute cooldown | `_can_intervene_distraction:113`, set at `intervening_node:199` | enforced |
| Max 3 distractions/session | `_can_intervene_distraction:123` vs `max_distraction_per_session` | enforced |
| Fatigue fires once | `_can_intervene_fatigue:128`, flag at `:195` | enforced (but see deviation 1) |
| Never interrupt TEACH_BACK | `route_from_teach_back:306` | enforced |
| Trigger rule | `service.py:321-332` — two consecutive sub-threshold, cooldown, TEACHING guard | matches §11 |

Weights are genuinely env-tunable with a sum-to-1.0 validator (`config.py:219-241`).

---

## Deviation 1 — `INTERVENING` is a one-way trap ⚠️ **fix before L6**

`route_from_intervening` (`state_machine/graph.py:337`) leaves INTERVENING **only** on
`intervention_complete`. That event is **dispatched by nothing**:

- absent from `_CLIENT_DRIVABLE_EVENTS` (`service.py:196`)
- absent from `_TUTOR_CLIENT_EVENTS` (`websocket.py:43`)
- absent from `wireTypes.ts:19-27`
- absent from every server path
- **there is no timeout**

**Consequence:** the first intervention that ever fires puts the session in INTERVENING permanently.
CES monitoring is TEACHING-gated, so it goes dead. `segment_complete` no-ops. The student's lesson
continues with the tutor silently switched off — and nothing logs a failure.

**It is unreachable today only because MediaPipe does not exist.** The moment Dev 2 ships L6, this
becomes reachable on the first distraction. **Land the fix before that, not after.**

**The alignment:** make `intervention_complete` reachable (client dismisses the intervention → WS
event → dispatch), **or** add a timeout that returns to TEACHING. Either is fine; silence is not.

---

## Deviation 2 — `behavioral_score` has no producer anywhere

`_parse_signal` (`service.py:54-100`) **hard-requires** `behavioral_score` via `_require_float` and
raises `ValueError` if absent. But there is **no definition, no computation, no spec** for it in
either app. Dev 2 cannot invent it; you own the signal contract.

**Two decisions only you can make:**

1. **Define `behavioral_score`** — what is it, what range, computed where? (Tab focus? Interaction
   recency? Scrub events?) CLAUDE.md §11 gives it 0.20 weight and no definition.
2. **Decide whether partial signals are valid.** Today all three of `behavioral_score`,
   `head_pose_score`, `blink_rate` are mandatory, so **Dev 2 cannot ship head-pose first and blink
   later** — the server rejects the frame. If you want incremental delivery from L6, relax
   `_parse_signal` to accept a partial signal and redistribute, the way `quiz_accuracy` already is.

---

## Deviation 3 — the CES formula exists twice and disagrees

Yours (`tutor/service.py:106-136`) is the live one. Dev 3's (`assessment/ces.py:19-87`) has **zero
importers** and disagrees with yours by a fixed **1.875×** whenever `quiz_accuracy is None`.

**At 0.9 attention, with `ces_threshold = 50`: his returns 48.00 (INTERVENE), yours returns 90.00
(fine).** Same inputs.

Yours matches CLAUDE.md §11's documented redistribution, so it is likely the survivor — but agree it
explicitly with Dev 3 rather than by attrition. **SYNC-A in the tracker.**

---

## Deviation 4 — smaller, but they will bite

| # | Issue | Where |
|---|---|---|
| a | Both tutor router endpoints return **501** | `modules/tutor/router.py:58`, `:77` — and their `TODO (Sprint 2)` comments carry **no `D-nn`**, which binding rule 5 forbids |
| b | Every FSM node returns `{**state, ...}` — the pattern CLAUDE.md bans repo-wide | `state_machine/graph.py` :156, :164, :211, :240, :248, :256 |
| c | The guard for (b) **does not scan your file** | `test_node_return_shape.py:33` scans only `app/modules/content/pipeline` |

(b) is not currently harmful — `TutorMachineState` declares no `operator.add` channels — but it is
`FIXED-UNGUARDED`, and it is exactly how the content pipeline went from one site to eighteen.
Widening the guard to your path is a two-line change and worth doing while you are in there.

---

## Live behaviour today, for reference

Socket opens → `tutor_state = IDLE` → client sends `session_start` → **IDLE → TEACHING** → each
segment boundary sends `segment_complete` → **TEACHING → CHECKING_IN** → nothing ever sends
`checkin_complete`, but `route_from_checking_in:298` falls through to `teaching`, so the next
boundary bounces it back.

**The machine oscillates TEACHING ↔ CHECKING_IN for the whole lesson and never reaches
SESSION_END** (`lesson_complete` is never sent). Worth deciding whether that matters for L8's
session report.

---

## What you owe others

| To | What |
|---|---|
| **Dev 2** | The `behavioral_score` definition, the agreed signal scale, and a decision on partial signals |
| **Dev 3** | Agreement on which CES implementation survives |
| **Dev 1** | Confirmation that `lesson_ready` reaches a real client during the L1 run (Phase 6.5 AC10) |

## What you're waiting on

- **Dev 2** — real attention frames (blocked on MediaPipe, which is blocked on your two decisions)
- **Dev 3** — CES ownership agreement

---

## Scale & Load (contract-mandated)

- **Unit of work:** one attention frame per tick, per session. State the expected tick rate.
- **Fixed budgets vs variable input:** max 3 distraction interventions/session and a 2-minute
  cooldown are both real — say what happens on a 90-minute session that hits the cap at minute 10.
- **Scope:** per session (Redis keys are `{session_id}`-scoped) — confirm nothing is per-instance.
- **Unbounded:** the CES history list per session — is it capped? A long session appends forever.
- **Inherited caps:** the 2-minute cooldown and 3-intervention cap were sized before any real CES
  data existed. Re-derive once L6 produces real signals.
- **Concurrency:** two tabs on one session both dispatch events into one FSM keyed by `session_id`.
  Is that safe, or does it double-transition?
