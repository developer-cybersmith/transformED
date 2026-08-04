# Dev 4 handoff — 2026-07-29

**From:** Dev 1 (infra / content pipeline / providers)
**To:** Dev 4 (WebSocket handlers, JWT middleware, 7-state tutor, Redis buffer, interventions)

---

## TL;DR

1. **`lesson_ready` never reaches any client.** New bug, verified today, and the publish side
   is **mine**. Needs a joint decision on the routing key — it's the only item here I need an
   answer on.
2. **I owe you a correction.** I previously flagged that the 16× duplication bug class exists
   in your tutor graph. **I was wrong — it does not.** Details below, because the reason
   matters.
3. **CI has failed 60 runs in a row.** Your 9 ruff errors are part of what it dies on, before
   it reaches a single test. Roughly a five-minute fix, and it unblocks everyone.
4. Sessions are never closed — `ended_at` is always NULL, and that's WebSocket lifecycle.

---

## 1. CORRECTION — the `{**state}` class is *not* live in your graph

On 2026-07-28 I handed off that `app/modules/tutor/state_machine/graph.py` carries the same
defect that caused our 16× quiz duplication. **That was wrong, and I want to correct it before
you spend time on it.**

The six sites do exist:

```python
graph.py:156  return {**state, "current_state": TutorState.IDLE}
graph.py:164  return {**state, "current_state": TutorState.TEACHING, "in_teachback": False}
graph.py:211  return {**state, "current_state": TutorState.CHECKING_IN}
graph.py:236  return {**state, "current_state": TutorState.QUIZZING}
graph.py:244  return {**state, "current_state": TutorState.TEACH_BACK, "in_teachback": True}
graph.py:252  return {**state, "current_state": TutorState.SESSION_END}
```

**But your state has no reducer channels.** I grepped for `operator.add`, `Annotated[` and
`add_messages` across `state_machine/` — nothing. Without a concatenating reducer, LangGraph's
default `LastValue` channel simply overwrites, so spreading state is a no-op.

Our bug needed both halves: the spread **and** six `Annotated[list, operator.add]` channels.
You have one half, which is harmless.

**What is worth knowing:** it's a loaded gun with no round in it. The day anyone adds a single
`operator.add` channel to `TutorState` — a message history, an accumulated intervention log,
anything list-shaped — all six sites become duplication bugs simultaneously, silently. Our
version reached 18 sites before anyone noticed, and cost ~4× on real TTS spend.

Cheap insurance if you want it: `apps/api/tests/unit/test_node_return_shape.py` is an AST scan
we wrote for exactly this. Pointing it at `modules/tutor/` is a small change and would fail the
moment the combination becomes dangerous. Entirely your call — there is **no bug to fix today**.

Apologies for the false alarm. I'd rather correct it than let you chase it.

---

## 2. NEW BUG — `lesson_ready` never reaches the client (register ID: D23)

Found while verifying item 1. **Verified by reading both ends.** The publish side is mine, the
routing side is yours, which is exactly why neither of us saw it.

### The mechanism

`app/workers/jobs/content_pipeline.py:81` (my file):

```python
session_id: str = lesson_row.get("session_id") or lesson_id
```

**`lessons` has no `session_id` column.** I checked its `CREATE TABLE` — zero matches. So
`.get("session_id")` is *always* `None`, the fallback *always* fires, and the pipeline publishes
to:

```
lesson_ready:{lesson_id}
```

Your side, `app/core/websocket.py:67-74`, registers connections under the **client-supplied**
`session_id` — which today is `crypto.randomUUID()` from `player.machine.ts:142`:

```python
async def connect(self, websocket: WebSocket, session_id: str) -> None:
    self._connections[session_id].append(websocket)
```

**The two keys can never match.** The `lesson_ready` push is published to a channel nobody is
subscribed to. The comment on my line 79 even says *"falls back to lesson_id until…"* — the
fallback became permanent and nothing flagged it.

### Why no test caught it

Same reason as everything else this week: my worker tests assert the publish happened; your WS
tests assert routing works given a session_id. Both green. Nothing reconciles the key. It's
written up as RC-1 in `docs/DEFECT-REGISTER.md` — 12 of 17 defects share this shape.

### ⚠️ The decision I need from you

There's a genuine design question underneath, and I don't think either of us should answer it
alone:

**A lesson is generated once but can be watched in many sessions.** So *what should the
`lesson_ready` push be keyed by?*

| | Approach | Trade-off |
|---|---|---|
| **A** | Key by **`lesson_id`**; WS subscribes per lesson it's waiting on | Matches what the pipeline already does. Natural — generation is a property of the lesson, not of a viewer. Needs a WS subscribe-by-lesson path. |
| **B** | Key by **`session_id`**; client passes it when triggering generation, stored on `lesson_jobs` | Keeps one routing key everywhere. Needs a schema change (`lesson_jobs.session_id`) → §16 four-dev gate. |
| **C** | Publish to **both** | No schema change, works immediately, but two keys for one event is the kind of thing that rots. |

**I lean A** — generation completion genuinely is a lesson-scoped event, and B makes a
generation job care about a viewer, which feels backwards. But routing is your domain and you
may have a reason I can't see.

Related: **Story 2-35** (in Dev 3's handoff) makes the backend mint `session_id` instead of the
client inventing it. That fixes session *identity*, but **not this** — the pipeline still has no
way to learn which session is watching. Worth deciding both together.

---

## 3. Sessions are never closed — `ended_at` is always NULL

Nothing anywhere writes the `sessions` table at all (that's D18 — see Dev 3's handoff; quiz and
teach-back currently 404 for every student). Story 2-35 adds session *creation*.

**Session termination is yours** — it belongs with WebSocket disconnect. Consequences today:

- `sessions.ended_at` is always NULL, so Dev 3's session duration and CES-final logic have never run
  against a real end time.
- A dropped connection is indistinguishable from an in-progress session.

Not urgent this week, but it should land before Sprint 3 real students, and it pairs naturally
with whatever you decide in §2.

---

## 4. ⚠️ CI has been dead for weeks — and 9 of the errors are yours

**Correction to what I sent earlier today.** I told you CI was "about to run tests it has never
run" and that 3 of your tests would start gating merges. Wrong framing, and the real ask is
smaller and more urgent.

### CI has failed 60 of its last 60 runs. Zero successes.

I checked the run history instead of reasoning from the config. Every merge to `main` since at
least 2026-07-27 — #104, #106, #108, #109 — went in over a red pipeline.

The API job dies here:

```
Run ruff check .
Found 31 errors.
##[error]Process completed with exit code 1.
```

`ruff check` is **step 5 of 9**; the test step is step 8. So it isn't that CI skipped the root
`tests/` directory — **CI has never reached a test step at all.**

(The web job died even earlier, at `setup-node`, on a lockfile path I got wrong. Entirely mine,
fixed in PR #110.)

### 🙏 The ask: your 9 ruff errors

22 of the 31 are Dev 3's, **9 are yours.** Together they're the only thing between this repo and
its first green run in weeks.

| File | ruff | mypy |
|---|---|---|
| `tests/test_tutor_service.py` | 3 | — |
| `app/modules/tutor/state_machine/graph.py` | 2 | 1 |
| `app/modules/tutor/service.py` | 2 | — |
| `tests/test_websocket_session.py` | 1 | — |
| `app/core/websocket.py` | 1 | **4** |

All `E501`/`I001`/`W293`-class. `ruff check --fix .` then `ruff format .` clears nearly all of
it. The 5 mypy errors are separate and not urgent — `mypy` runs *after* `ruff`, so it isn't
what's blocking today.

I cleared Dev 1's 47 already (repo-wide 78 → 31) and **deliberately left yours alone** — a
lint-only edit to your files risks conflicting with work you have in flight.

### Your 3 test failures do NOT gate. Deliberately.

I split the step rather than pointing it at everything:

| Step | Scope | Gates? | Measured today |
|---|---|---|---|
| Unit tests | `tests/unit` + `tests/integration` | **yes** | 743 passed, 1 skipped |
| Full suite | `tests` | **no** (`continue-on-error`) | 22 failed, 1435 passed |

Your 3 in `tests/test_tutor_service.py` become **visible without blocking anyone.** `-x` is gone
either way, so CI now enumerates every failure rather than stopping at the first.

I'm not handing three colleagues a red `main` over failures I didn't introduce — and a gate
everyone routes around is worse than no gate, because it trains the team to ignore it. Which is
demonstrably what happened here. Registered as **D24**, with an explicit trigger to make it
gate: when the 22 reach zero.

Still haven't investigated *why* those 3 fail — your files, and guessing at intent would be
worse than saying so. `xfail` with a comment is a fine answer if they're expected-red.

---

## 5. Context you may want

`docs/DEFECT-REGISTER.md` is new — the authoritative record of known defects and the decisions
about them, with an enforcement column (a test, a CI gate, or the word DISCIPLINE). Two entries
touch you indirectly:

- **A Redis blip is currently a full pipeline outage.** `redis.TimeoutError` is not Python's
  builtin `TimeoutError`, so it falls through our retry classification and is fatal. **That one
  is mine to fix** (`core/retry.py` + the provider call sites) — listed only so you know it's
  known and owned.
- **The 7-state tutor's intervention messages are pre-generated at build time**, and the
  pipeline that generates them had a duplication bug until this morning. If you saw repeated
  intervention text in a lesson package, that's why. Fixed.

---

## What I need from you

**Two things:**

1. **An answer: A, B or C in §2** — the `lesson_ready` routing key. I'll implement whichever you
   pick on the publish side; it's my file and a small change once the contract is decided.
2. **Your 9 ruff errors (§4)** — roughly five minutes, and it's half of what's keeping CI red
   for all four of us.

Everything else is FYI and yours to schedule.
