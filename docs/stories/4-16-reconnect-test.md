---
baseline_commit: "b295ca9"
---

# Story 4-16: Session Reconnect Restores Correctly From All 7 States

**Status:** done (unit portion) — task scored **Partial** (live network-fault simulation pending; see Review)

---

## Story

As Dev 4,
I want a test proving a WebSocket reconnect restores the live tutor state **from each of the 7 FSM
states** (read from Redis, pushed to the client as a `state_change` sync, with no reset),
so that the Sprint 4 `reconnect_test` AC — "reconnect from each of the 7 states tested; state is always
correctly restored from Redis" — is satisfied.

---

## Context (verified)

- The reconnect-restore path exists from s2-4: `connect()` → `_restore_or_init_session(session_id)`
  (`websocket.py:176`) does `get_redis().get(f"tutor_state:{session_id}")`; if present, `connect()` sends
  the **frozen `state_change`** message with `from_state == to_state` (a sync, not a transition) and does
  **not** reset the session.
- **Contract note:** the tracker text says "receives `state_sync`", but `state_sync` is NOT in the frozen
  `ws.ts`. The reconnect sync reuses the frozen `state_change` (decided in s2-4). The AC's intent — "state
  correctly restored from Redis" — is met by the `state_change`(from==to) sync. We keep the frozen contract.
- The 7 states (`TutorState`, `graph.py:75-82`): `IDLE, TEACHING, INTERVENING, CHECKING_IN, QUIZZING,
  TEACH_BACK, SESSION_END`.
- **Existing F-group coverage** (`test_websocket_session.py`): F1 (QUIZZING), F5 (TEACH_BACK, bytes), F6
  (send-failure), F2 (new session → no sync), F3 (read-failure → degrade). **Missing:** a systematic test
  over **all 7** states — exactly what the AC asks for.

---

## Acceptance Criteria

- **AC 1:** For **each** of the 7 `TutorState` values, a reconnect (that state present at
  `tutor_state:{sid}`) makes `connect()` send exactly
  `{"type":"state_change","payload":{"session_id":sid,"from_state":S,"to_state":S}}` and **not** reset
  (`redis.set` not called).
- **AC 2:** The test asserts the state was **read from Redis** — `get_redis().get("tutor_state:{sid}")` was
  awaited — so "restored from Redis" is proven, not assumed.
- **AC 3:** Full suite green; no production code change (restore logic already shipped in s2-4).

---

## Tasks / Subtasks

- [ ] 1.1 Add `test_f7_reconnect_restores_each_of_7_states` (parametrized over the 7 states) to the F-group
  in `apps/api/tests/test_websocket_session.py`.
- [ ] 1.2 Run the file + full regression.

---

## Dev Notes

```python
@pytest.mark.unit
@pytest.mark.parametrize(
    "state",
    ["IDLE", "TEACHING", "INTERVENING", "CHECKING_IN", "QUIZZING", "TEACH_BACK", "SESSION_END"],
)
async def test_f7_reconnect_restores_each_of_7_states(mocker, state):
    """AC: a reconnect restores the live tutor state from Redis for ALL 7 FSM states — pushes a
    state_change sync (from == to) and does not reset."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=state)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    sid = f"sess-{state}"
    await ConnectionManager().connect(ws, sid)

    # Restored FROM Redis (the tutor_state key was read).
    mock_redis.get.assert_awaited_once_with(f"tutor_state:{sid}")
    # Synced to the client via the frozen state_change (from == to), and NOT reset.
    ws.send_json.assert_called_once_with(
        {"type": "state_change", "payload": {"session_id": sid, "from_state": state, "to_state": state}}
    )
    mock_redis.set.assert_not_called()
```

Use a fresh `ConnectionManager()` per param to avoid registry leakage (matches F1/F2).

### Out of scope / flagged (follow-up — needs live infra)

- **Live network-fault simulation** (the description's `toxiproxy` / manual interrupt: drop a real socket
  mid-session and reconnect against the running API) is an end-to-end integration check that needs a live
  API + Redis (ideally the India-region deploy — Sprint-3 prerequisite). The 7-state restore logic it would
  exercise is fully covered here at the unit level; the live fault-injection run is a follow-up enhancement,
  not required by the AC's literal wording ("state correctly restored from Redis").
- "Without data loss" beyond the FSM state name (e.g. `segment_index` / player position) is a known s2-4
  follow-up — the reconnect sync carries the FSM state only.

---

## Review outcome (adversarial, 2026-06-30) — SHIP test; score Partial

**Test verified sound (mutation-tested).** The reviewer drove the real `connect()` / `_restore_or_init_session`
(only Redis mocked) and proved non-vacuity by mutation: changing the sent `to_state` → all 7 params FAIL;
injecting a reset `redis.set` on the restore path → all 7 FAIL; restored code → 7 pass. So the assertions
genuinely catch a wrong `from/to`, a missing Redis read, and an erroneous reset. `assert_awaited_once_with`
is correct (restore reads `tutor_state` exactly once and returns before `_init`). The 7 params exactly match
the `TutorState` enum; the `state_change`(from==to) assertion is on-contract (`state_sync` isn't in ws.ts).
f7 adds real coverage over F1/F5 (IDLE/INTERVENING/CHECKING_IN/SESSION_END + the explicit Redis-read assert).

**Status → Partial (not Completed).** The AC *sentence* ("reconnect from each of the 7 states; state correctly
restored from Redis") is fully met, but the task *title/body* — "under poor network conditions", toxiproxy /
mid-session drop, "without data loss" — is not exercised by a unit test. For consistency with how
`ws_load_test` was scored (harness done, live run pending → Partial), this lands as **Partial**: the
7-state restore-from-Redis is proven and shippable; the **live network-fault simulation** (toxiproxy against
a running API) and **data-loss-beyond-FSM-state** (`segment_index`/player position) remain — both gated on a
live server / future work.

**Flagged (kept open):** SESSION_END (terminal) restore is locked in without a guard against re-driving a
dead session (s2-4 follow-up); stale "`state_sync`" wording in the tracker description reworded to
`state_change`.
