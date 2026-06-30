---
baseline_commit: "a997b6c"
---

# Story 4-13: Fatigue Intervention Fires Once Per Session — integration test

**Status:** done — *no code change required; task was mis-tracked as Partial (see Outcome).*

---

## Story

As Dev 4,
I want an end-to-end test proving a fatigue intervention fires the first time but is **blocked on the
second** `fatigue_detected` in the same session, driven through the real compiled LangGraph
(`dispatch_event`),
so that the Sprint 3 `fatigue_once` task moves Partial → Completed (implementation exists; the
once-per-session integration test is the missing piece its AC requires).

---

## Context (verified — implementation already done)

- Guard `_can_intervene_fatigue(session_id)` (`graph.py:129-136`) returns
  `not bool(redis.exists("tutor_fatigue_fired:{sid}"))` — allowed only if the flag is absent.
- `intervening_node` (`graph.py:184-185`) does `redis.set("tutor_fatigue_fired:{sid}", "1", ex=_STATE_TTL)`
  for `intervention_type == "fatigue"`.
- `route_from_teaching` (`graph.py:253-257`): `fatigue_detected` → `"intervening"` if the guard passes,
  else stays `"teaching"`. (The fatigue gate does NOT consult cooldown — only the fired-flag.)
- **Already covered:** `test_tutor_graph.py::test_fatigue_detected_sets_fatigue_fired_flag` (a single
  `fatigue_detected` sets the flag) and the dispatch's intervention_type derivation.
- **Missing (this task):** an integration test chaining 2 `fatigue_detected` dispatches: #1 reaches
  INTERVENING and sets the flag; #2 is blocked (stays TEACHING; the flag is not set a second time).

No production code change — test only.

---

## Acceptance Criteria

- **AC 1:** A first `fatigue_detected` (from TEACHING, flag absent) yields `current_state == INTERVENING`
  and sets `tutor_fatigue_fired:{sid}`.
- **AC 2:** A second `fatigue_detected` (flag now present) is **blocked**: result stays `TEACHING` and the
  fatigue flag is **not** set a second time (the 2nd never reaches `intervening_node`).
- **AC 3:** Test drives the real `dispatch_event` (real compiled graph), Redis mocked only; full suite green.

---

## Tasks / Subtasks

- [ ] 1.1 Add a `_fatigue_redis()` stateful mock to `test_tutor_graph.py`: tracks `tutor_state` (get/set)
  and the fatigue flag (`set` on the `tutor_fatigue_fired:` key flips it on + counts the set; `exists`
  returns 1 once set). Returns `(redis, store)`.
- [ ] 1.2 Add `test_fatigue_fires_once_then_blocked`: 1st dispatch asserts INTERVENING + flag set
  (`fatigue_set_count == 1`); reset state→TEACHING; 2nd dispatch asserts TEACHING + `fatigue_set_count`
  still 1.
- [ ] 1.3 Run the file + full regression.

---

## Dev Notes

```python
def _fatigue_redis(initial_state: str = "TEACHING"):
    """Stateful redis tracking tutor_state + the once-per-session fatigue flag. The fatigue gate keys off
    exists(tutor_fatigue_fired:{sid}); cooldown is irrelevant to it. Returns (redis, store) so the test
    can reset state between dispatches."""
    store = {"state": initial_state, "fatigue_fired": False, "fatigue_set_count": 0}
    redis = AsyncMock()

    async def _get(key: str):
        if key.startswith("tutor_state:"):
            return store["state"]
        return None

    async def _set(key: str, value, **_kw):
        if key.startswith("tutor_state:"):
            store["state"] = value
        elif key.startswith("tutor_fatigue_fired:"):
            store["fatigue_fired"] = True
            store["fatigue_set_count"] += 1

    async def _exists(key: str):
        if key.startswith("tutor_fatigue_fired:"):
            return 1 if store["fatigue_fired"] else 0
        return 0  # cooldown etc. never active — isolate the fatigue gate

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis.exists = AsyncMock(side_effect=_exists)
    return redis, store
```

```python
@pytest.mark.unit
async def test_fatigue_fires_once_then_blocked(mocker) -> None:
    """s3-7: the 1st fatigue_detected fires (sets the fired flag); the 2nd is blocked by the
    once-per-session guard. No cooldown involved — the fired-flag is the sole gate."""
    _patch_settings(mocker)
    redis, store = _fatigue_redis("TEACHING")
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    sid = "s-fatigue-once"

    first = await dispatch_event(sid, "fatigue_detected")
    assert first["current_state"] == TutorState.INTERVENING
    assert store["fatigue_fired"] is True
    assert store["fatigue_set_count"] == 1

    store["state"] = "TEACHING"  # student resumed teaching; CES monitoring active again
    second = await dispatch_event(sid, "fatigue_detected")
    assert second["current_state"] == TutorState.TEACHING  # blocked — fatigue already fired
    assert store["fatigue_set_count"] == 1  # 2nd never reached intervening_node — flag not re-set
```

Run: `cd apps/api && ../../.venv/Scripts/python.exe -m pytest tests/test_tutor_graph.py -p no:cacheprovider -o filterwarnings=ignore -q` then the full suite (ignore `tests/unit/test_lesson_schema.py` — pre-existing missing `jsonschema`).

### Out of scope

- The single-dispatch flag-set is already covered by `test_fatigue_detected_sets_fatigue_fired_flag`; this
  story adds only the once-per-session (2nd blocked) sequence.

---

## Outcome (2026-06-30) — the test already existed; no code change

While implementing, the integration test the tracker called "missing" was found to **already exist on
`main`**: `test_tutor_graph.py::test_fatigue_fires_once_then_blocked` (landed earlier, alongside the s2-1
`full_state_machine` fatigue tests, but `fatigue_once` was never reconciled from Partial). It fully covers
both ACs and is, if anything, more realistic than this story's proposed version:

```text
r1 = dispatch_event(sid, "fatigue_detected")     → INTERVENING   # fires once (sets tutor_fatigue_fired)
back = dispatch_event(sid, "intervention_complete") → TEACHING    # real resume transition
r2 = dispatch_event(sid, "fatigue_detected")     → TEACHING       # BLOCKED — flag already present
```

It uses the real `intervention_complete` event to return to TEACHING (rather than forcing the state), so
the second `fatigue_detected` genuinely re-enters `route_from_teaching → _can_intervene_fatigue`. `r2 ==
TEACHING` proves the guard blocked it (it would be `INTERVENING` if the guard had passed). Combined with
`test_fatigue_detected_sets_fatigue_fired_flag` (asserts the flag write), AC1 + AC2 are fully met.

**Action taken:** verified the existing test (passes; hand-traced as sound — not a false-green), discarded
the redundant duplicate that would have collided on the same function name, and corrected the tracker
(`fatigue_once` Partial → Completed). No production or test code changed.

**Optional follow-up (not done — gold-plating):** the existing test could additionally assert the flag was
set in r1, but `test_fatigue_detected_sets_fatigue_fired_flag` already covers that write.
