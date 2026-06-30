---
baseline_commit: "bd6636b"
---

# Story 4-12: Max 3 Distraction Interventions Per Session — integration test

**Status:** done

---

## Story

As Dev 4,
I want an end-to-end test proving the first three distraction interventions fire but the **fourth is
blocked** by the per-session cap, driven through the real compiled LangGraph (`dispatch_event`),
so that the Sprint 3 `max_distraction_cap` task moves from Partial → Completed (implementation exists;
the integration test is the missing piece its AC requires).

---

## Context (verified — implementation already done)

- Guard `_can_intervene_distraction(session_id)` (`graph.py:106`) returns `count < settings.max_distraction_per_session`
  (default 3) and `False` if cooldown is active.
- `intervening_node` (`graph.py:180-182`) does `redis.incr("tutor_distraction_count:{sid}")` + `expire`
  for `intervention_type == "distraction"`.
- `route_from_teaching` (`graph.py:246-251`): `distraction_detected` → `"intervening"` if the guard passes,
  else stays `"teaching"`.
- **Already covered:** the guard's unit boundary — `test_websocket_session.py` C-group (`test_c2` count=1 →
  allow, `test_c3` count=3 → block) and `test_tutor_graph.py::test_distraction_detected_increments_count`.
- **Missing (this task):** an integration test chaining 4 `distraction_detected` dispatches through the
  real FSM: #1–#3 reach INTERVENING and increment the counter; #4 is blocked (stays TEACHING, no incr).

No production code change — test only.

---

## Acceptance Criteria

- **AC 1:** Driving `distraction_detected` three times (each from TEACHING, cooldown NOT active) yields
  `current_state == INTERVENING` each time and increments `tutor_distraction_count` to 1, 2, 3.
- **AC 2:** A fourth `distraction_detected` (count now 3 == max) is **blocked** by the cap: result stays
  `TEACHING` and the counter is **not** incremented past 3 (the 4th never reaches `intervening_node`).
- **AC 3:** The cap — not cooldown — is the gate: the test keeps `exists` (cooldown) at 0 throughout, so
  only the count guard can block.
- **AC 4:** Test drives the real `dispatch_event` (real compiled graph), Redis mocked only; full suite green.

---

## Tasks / Subtasks

- [ ] 1.1 Add a `_cap_redis()` stateful mock to `test_tutor_graph.py`: tracks `tutor_state` (get/set) and
  the distraction count (`incr` increments an int; `get` returns it as a string); `exists` always 0.
- [ ] 1.2 Add `test_max_distraction_cap_blocks_fourth`: loop 3 firings (reset state→TEACHING before each,
  simulating resume to monitoring), assert INTERVENING + count == n; then a 4th asserts TEACHING + count
  still 3.
- [ ] 1.3 Run the file + full regression.

---

## Dev Notes

```python
def _cap_redis(initial_state: str = "TEACHING"):
    """Stateful redis tracking tutor_state + distraction count; cooldown never active (exists=0) so the
    distraction CAP is the only gate. Returns (redis, store) so the test can reset state between dispatches."""
    store = {"state": initial_state, "count": 0}
    redis = AsyncMock()

    async def _get(key: str):
        if key.startswith("tutor_state:"):
            return store["state"]
        if key.startswith("tutor_distraction_count:"):
            return str(store["count"])
        return None

    async def _set(key: str, value, **_kw):
        if key.startswith("tutor_state:"):
            store["state"] = value

    async def _incr(key: str):
        if key.startswith("tutor_distraction_count:"):
            store["count"] += 1
            return store["count"]

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis.incr = AsyncMock(side_effect=_incr)
    redis.exists = AsyncMock(return_value=0)  # never in cooldown — isolate the cap
    return redis, store
```

```python
@pytest.mark.unit
async def test_max_distraction_cap_blocks_fourth(mocker) -> None:
    """s3-6: interventions 1–3 fire; the 4th is blocked by the cap (count < max=3). Cooldown is never
    active, so the CAP is the sole gate."""
    _patch_settings(mocker, max_distraction=3)
    redis, store = _cap_redis("TEACHING")
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    from app.modules.tutor.state_machine.graph import dispatch_event

    sid = "s-cap"
    for n in (1, 2, 3):
        store["state"] = "TEACHING"  # student resumed teaching; CES monitoring active again
        result = await dispatch_event(sid, "distraction_detected")
        assert result["current_state"] == TutorState.INTERVENING, f"intervention {n} should fire"
        assert store["count"] == n

    store["state"] = "TEACHING"
    blocked = await dispatch_event(sid, "distraction_detected")
    assert blocked["current_state"] == TutorState.TEACHING  # cap reached
    assert store["count"] == 3  # 4th never reached intervening_node — no incr
```

Run: `cd apps/api && ../../.venv/Scripts/python.exe -m pytest tests/test_tutor_graph.py -p no:cacheprovider -o filterwarnings=ignore -q` then the full suite (ignore `tests/unit/test_lesson_schema.py` — pre-existing missing `jsonschema`).

### Out of scope

- Cooldown enforcement (separate Completed task). The count guard's per-call boundary is already unit-tested
  (C-group) — this story adds only the end-to-end cap sequence.

---

## Review outcome (adversarial false-green review, 2026-06-30)

**Verdict: SHIP.** The reviewer hand-traced all 4 dispatches and confirmed the test genuinely validates the
cap rather than passing for the wrong reason:
- **Cap is the sole gate:** with `exists=0`, the cooldown branch is disabled, so only `count < max(3)` can
  block. Block at `count==3` (4th attempt) is correct for "max 3 per session" — no off-by-one.
- **Not a false-green:** the per-iteration `store["state"]="TEACHING"` reset is **load-bearing** — without it,
  firings 2+ would route via `route_from_intervening` and skip the guard entirely; the reset forces every
  firing through `route_from_teaching → guard → intervening_node`. The dual assertion (`current_state==TEACHING`
  AND `count==3`) on the 4th dispatch cannot both hold if the 4th had fired (`intervening_node` would incr to 4).
- **Adds real coverage:** complements the existing single-dispatch boundary tests
  (`test_distraction_blocked_by_max_count_stays_teaching` count==3→TEACHING; `test_distraction_allowed_just_below_max`
  count==2→INTERVENING) with the chained "exactly 3 fire" sequence.
- **No unmodeled-Redis dependence, not flaky.**

**Applied:** the one LOW finding — renamed the test session id `s-cap` → `s-cap-4th` to avoid a cosmetic
collision with another test's id (no correctness impact; each test has an isolated mock Redis).
