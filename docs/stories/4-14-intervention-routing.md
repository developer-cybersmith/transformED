---
baseline_commit: "b4e008d"
---

# Story 4-14: Intervention Routing — each type → its own pre-generated message

**Status:** done

---

## Story

As Dev 4,
I want a test proving each intervention type routes to its OWN distinct pre-generated message from the
lesson package, and the stale `encouragement` type reconciled to the frozen contract,
so that the Sprint 3 `intervention_routing` task is complete and the tracker/code stop referencing a
type that does not exist.

---

## Context (verified)

Routing is **already implemented**:
- `_EVENT_INTERVENTION_TYPE` (`graph.py:65-69`) maps `distraction_detected→distraction`,
  `fatigue_detected→fatigue`, `teachback_failed→confusion`.
- `dispatch_event` (`graph.py:460`) derives `intervention_type` from that map (or an explicit payload).
- `intervening_node` (`graph.py:194-196`) selects `messages.get(intervention_type)[0]` from the event
  payload's `intervention_messages`.

**Coverage today:** fatigue (`test_intervention_message_selected_from_payload`) and confusion
(`test_intervention_message_selected_for_confusion`) each have a selection test. **Distraction message
selection is NOT tested** (only its counter), and there is **no single test proving all three route to
DISTINCT messages** (no cross-talk).

### Design decision — the third type is `confusion`, NOT `encouragement` (decisive)

The tracker text says intervention types are `distraction | fatigue | encouragement`. **`encouragement`
does not exist in any frozen contract:**
- `packages/shared/types/ws.ts:20` — `InterventionType = 'distraction' | 'confusion' | 'fatigue'`
- `packages/shared/lesson_package.schema.json:200` — `SegmentInterventions.required = [distraction, confusion, fatigue]`

The implementation already uses the correct three (`distraction | confusion | fatigue`). The tracker text
predates the schema freeze. **Resolution:** the third type is **`confusion`**; reconcile the phantom
`encouragement` out of the Dev-4 surfaces. The frozen contract outranks the tracker wording.

`encouragement` lingers in three places:
1. `apps/api/app/modules/tutor/router.py:35` — a **comment** on `InterventionRequest.intervention_type`
   (a free-form `str` admin field). Fix the comment to the frozen types.
2. `scripts/check_dev4_progress.py:282` — the auto-check heuristic greps for `"encouragement"`. Fix to
   `"confusion"` so it matches reality.
3. `apps/api/app/modules/content/pipeline/graph.py:249` — Dev 1's TODO comment. **Out of scope**
   (one-discipline rule — Dev 1's module); flag only.

---

## Acceptance Criteria

- **AC 1:** A test drives all three intervention-triggering events and asserts each lands in INTERVENING
  with `intervention_type` ∈ {distraction, confusion, fatigue} and `intervention_message` equal to **that
  type's own** `[0]` message from a shared package — the three expected messages are distinct (proves no
  cross-talk / correct routing). Covers the previously-untested distraction selection.
- **AC 2:** No type named `encouragement` remains in Dev-4-owned code/tooling: `tutor/router.py` comment
  and `check_dev4_progress.py` heuristic both use the frozen `distraction | confusion | fatigue`.
- **AC 3:** No production routing-logic change (the routing already matches the frozen contract); full
  suite green.

---

## Tasks / Subtasks

- [ ] 1.1 Add `test_intervention_routes_each_type_to_its_own_message` (parametrized over the 3 types) to
  `test_tutor_graph.py`.
- [ ] 1.2 `tutor/router.py:35` — comment `encouragement` → `confusion` (frozen types).
- [ ] 1.3 `scripts/check_dev4_progress.py:282` — heuristic string `"encouragement"` → `"confusion"`.
- [ ] 1.4 Run the file + full regression.

---

## Dev Notes

### Routing test (per-type state: distraction/fatigue fire from TEACHING, confusion from TEACH_BACK)

```python
@pytest.mark.unit
@pytest.mark.parametrize(
    "event,state,exp_type,exp_msg",
    [
        ("distraction_detected", "TEACHING", "distraction", "D0"),
        ("fatigue_detected", "TEACHING", "fatigue", "F0"),
        ("teachback_failed", "TEACH_BACK", "confusion", "C0"),
    ],
)
async def test_intervention_routes_each_type_to_its_own_message(mocker, event, state, exp_type, exp_msg):
    """s3-8: each triggering event routes to its OWN intervention type and selects that type's distinct
    message[0] from the shared package (D0/F0/C0 are distinct → proves no cross-talk)."""
    _patch_settings(mocker)
    sid = f"s-route-{exp_type}"
    # count="0" + exists=0 so the distraction cap / cooldown / fatigue-once guards all allow the fire.
    redis = _keyed_redis(sid, state=state, count="0", exists=0)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    payload = {
        "intervention_messages": {
            "distraction": ["D0", "D1", "D2"],
            "confusion": ["C0", "C1", "C2"],
            "fatigue": ["F0", "F1", "F2"],
        }
    }
    result = await dispatch_event(sid, event, payload=payload)

    assert result["current_state"] == TutorState.INTERVENING
    assert result["intervention_type"] == exp_type
    assert result["intervention_message"] == exp_msg
```

### router.py comment

```python
intervention_type: str  # distraction | confusion | fatigue (+ admin prompt types: quiz_prompt | teachback_prompt)
```

### Out of scope / flagged

- Message **rotation** (always `[0]`) — deferred (cheap follow-up; rotate distraction by its count).
- Dev 1's `content/pipeline/graph.py:249` TODO still says "encouragement" — flag for Dev 1 to align the
  generated `intervention_messages` to the frozen `confusion` key.
- The admin `InterventionRequest` is a free-form `str`; this story only fixes its comment, not validation.

---

## Review outcome (adversarial, 2026-06-30) — SHIP

Hand-traced all 3 params through `dispatch_event → _EVENT_INTERVENTION_TYPE → route → intervening_node`:
- distraction (TEACHING, guard passes count 0<3 / no cooldown) → type `distraction` → `D0`
- fatigue (TEACHING, fatigue flag absent) → type `fatigue` → `F0`
- confusion (TEACH_BACK, `teachback_failed` → intervening, no guard on that edge) → type `confusion` → `C0`

**Not a false-green:** D0/F0/C0 are distinct, so a cross-wire (wrong type→message) fails the assertion; the
`intervention_type` and `intervention_message` assertions are **complementary** — the former pins the
derivation stage, the latter the selection stage. Every param reaches INTERVENING for the right reason.

**Reconciliation verified correct + complete:** `ws.ts InterventionType` and `SegmentInterventions`
(`additionalProperties:false`) both = `distraction|confusion|fatigue` — no `encouragement`. The reviewer
executed the `check_dev4_progress.py` glob live: `"distraction"`+`"fatigue"`+`"confusion"` all co-occur in
`graph.py` (`_EVENT_INTERVENTION_TYPE`), so the heuristic now passes — and the *old* `"encouragement"`
heuristic was a stale false-negative this change fixes. `graph.py` routing logic unchanged (empty diff);
Dev 1's `content/pipeline/graph.py` untouched.

**MED (flagged, NOT fixed — pre-existing, out of scope):** `InterventionRequest.intervention_type` is an
unvalidated free-form `str`, so an admin could still POST `"encouragement"`. Not introduced by this diff;
recommend a follow-up to constrain it with `Literal["distraction","confusion","fatigue", ...]`.
