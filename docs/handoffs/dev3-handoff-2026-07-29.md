# Dev 3 handoff — 2026-07-29

**From:** Dev 1 (infra / content pipeline / providers)
**To:** Dev 3 (quiz API, teach-back scorer, CES, Learner DNA, session reports, analytics)

---

## TL;DR

1. **A demo blocker lives in your module, and it is not your fault.** Nothing anywhere creates
   a `sessions` row, so quiz and teach-back 404 for every student. I've written the story and
   can implement it, but it lands in `assessment/` — **your call whether I proceed or you take it.**
2. **CI has failed 60 runs in a row and your 22 ruff errors are the first thing it hits.**
   Not "will start gating" — it's been dead this whole time, and this is the single fastest
   unblock available to the whole team. `ruff check --fix` handles most of it.
3. `assessment/service.py` has 22 mypy errors — the only substantive static-analysis work in
   the repo. Everything else is mechanical.

Nothing here needs a reply today except item 1. Item 2 needs about ten minutes.

---

## 1. THE BLOCKER — no session is ever created (register ID: D18)

### What happens

A student opens a lesson, answers a quiz question, and gets **404**. Every time, every student.
The demo cannot complete.

### Why

`app/modules/assessment/service.py:175`:

```python
session_row = single_row(session_resp)
if session_row is None:
    raise HTTPException(404, detail=f"Session {session_id!r} not found.")
```

That check is correct. The problem is upstream of it — **nothing creates the row**:

- All **7** `table("sessions")` references in `apps/api` are `.select(...)`. Zero writers.
- `apps/web` never inserts it either. I checked specifically, because "no writers in the API"
  would have been a misleading finding if the frontend wrote it directly.
- `apps/web/src/stores/player.machine.ts:142` invents one: `sessionId: crypto.randomUUID()`.

So the client sends a UUID that has never existed in the database, and your ownership check
correctly rejects it.

### Why no test caught it

This is the part worth reading, because it isn't about anyone being careless:

> **Your tests seed the session row in fixtures. Dev 2's tests mock the POST. Both suites are
> green. The product is broken.**

Each side tested its own half against its own assumption. Nothing ever reconciled them. We
found the same pattern behind 12 of 17 defects analysed this week — it's written up as RC-1 in
`docs/DEFECT-REGISTER.md`. It traces back to CLAUDE.md's Week-1 anti-deadlock rule ("each dev
mocks the other's interface"), which was correct at the time and was never given an expiry.

### The fix

The schema shows server-side minting was always the design:

```sql
session_id  uuid PRIMARY KEY DEFAULT gen_random_uuid()
user_id     uuid NOT NULL REFERENCES public.users(id)
lesson_id   uuid NOT NULL REFERENCES public.lessons(lesson_id)
started_at  timestamptz NOT NULL DEFAULT now()
```

A client-chosen UUID cannot satisfy those foreign keys or make `started_at` mean anything.

Proposed: **`POST /api/assessment/sessions`** taking `{lesson_id}`, deriving `user_id` from the
verified JWT, returning the database-generated `session_id`. Full ACs in
`docs/stories/2-35-session-lifecycle-endpoint.md`.

### ⚠️ Your decision — this lands in your module

`sessions` is read by `assessment` and `analytics`. Both are yours, so a `sessions` writer
belongs in `assessment/`. CLAUDE.md §5.4 says modules never reach into another module's tables,
so me implementing this is a **deliberate ownership crossing**, not an oversight.

**Three options — your call:**

| | |
|---|---|
| **A** | You take Story 2-35. Correct ownership. Slower if you're mid-sprint. |
| **B** | I implement it, you review before merge. Unblocks the demo fastest. |
| **C** | I implement, you take it over later. Worst of both — I'd rather not. |

I've written the story but **not the code**. Tell me which and I'll act.

### One thing I deliberately did *not* do

The tempting shortcut is to upsert the row inside `submit_quiz` when it's missing. That kills
the 404 without fixing anything: `started_at` becomes the time of the first answer instead of
the lesson start, and any client-chosen UUID silently becomes a valid session. Story 2-35's
**AC-4** exists specifically to forbid it — an unminted id must still 404.

Also worth knowing: `ended_at` is **not** in scope. Session termination belongs with Dev 4's
WebSocket disconnect handling. Sessions currently have no close path at all, so
`analytics`'s duration and CES-final logic has never had a real `ended_at` to work with.

---

## 2. ⚠️ CI has been dead for weeks, and your 22 ruff errors are the first thing it hits

**Correction to what I sent earlier today.** I told you CI was "about to start running tests it
never ran" and that 19 of your tests would begin blocking merges. That framing was wrong, and
the real picture asks something much smaller of you.

### CI has failed 60 of its last 60 runs. Zero successes.

I checked the actual run history rather than reasoning from the config. Every merge to `main`
since at least 2026-07-27 — #104, #106, #108, #109 — went in over a red pipeline.

The API job dies here:

```
Run ruff check .
Found 31 errors.
##[error]Process completed with exit code 1.
```

`ruff check` is **step 5 of 9**. The test step is step 8. So it isn't that CI skipped the root
`tests/` directory — **CI has never reached a test step at all.** Neither yours nor mine.

(The web job died even earlier, at `setup-node`, on a bad lockfile path. That one was entirely
mine and is fixed in PR #110.)

### 🙏 The actual ask: your 22 ruff errors

Of those 31 errors, **22 are in your files** and 9 are Dev 4's. They are the only thing standing
between this repo and its first green CI run in weeks.

| File | ruff |
|---|---|
| `tests/test_session_report_endpoint.py` | 8 |
| `tests/test_reassessment_flag.py` | 5 |
| `app/modules/assessment/service.py` | 3 |
| `app/modules/assessment/router.py` | 3 |
| `tests/test_onboarding_content.py` | 2 |
| `app/modules/assessment/dna_fusion.py` | 1 |

Nearly all are `E501`, `I001`, `W293`. `ruff check --fix .` then `ruff format .` clears most in
one pass. **This is the highest-leverage ten minutes anyone on the team can spend today.**

### Your 19 test failures do NOT gate. Deliberately.

I split the step rather than pointing it at everything:

| Step | Scope | Gates? | Measured today |
|---|---|---|---|
| Unit tests | `tests/unit` + `tests/integration` | **yes** | 743 passed, 1 skipped |
| Full suite | `tests` | **no** (`continue-on-error`) | 22 failed, 1435 passed |

So your `test_dna_growth.py` (18) and `test_dna_fusion.py` (1) become **visible without
blocking anyone**, including you. `-x` is gone either way, so CI now enumerates every failure
instead of stopping at the first.

I'm not going to hand three colleagues a red `main` over failures I didn't introduce, and a
gate everyone routes around is worse than no gate — it teaches the team to ignore it. That
compromise is registered as **D24** with an explicit trigger to make it gate: when the 22 reach
zero. It's a tracked debt with a condition, not a quiet weakening.

I still haven't looked into *why* those 19 fail — your files, and guessing at intent would be
worse than saying so. `xfail` with a comment is a perfectly good answer if they're expected-red.

**One piece of good news:** `tests/test_onboarding_content.py` was failing 10 tests earlier
today and now passes. I removed two stale `openai` MagicMock stubs from `conftest.py` (they
predated `openai` becoming a hard dependency) and those went green as a side effect.

---

## 3. Static analysis — 22 mypy errors, all in one file

`app/modules/assessment/service.py` carries **22 of the repo's 24** mypy errors. They're all
the same shape:

```
error: Item "int" of "bool | str | int | float | Sequence[JSON] | Mapping[str, JSON] | None"
       has no attribute "get"  [union-attr]
```

Indexing a `JSON` union without narrowing first. It needs a real fix — a formatter won't touch
it — and it's the only substantive static work left in the repo. Everything else is `E501`,
`I001` and `W293`.

**Ruff is the urgent half — see §2 for the file-by-file list.** It's mechanical, and it's what
CI dies on before it reaches anything else. The mypy work below can wait; the ruff work
shouldn't.

I cleared Dev 1's 47 already (PRs #103, #104) — repo-wide went 78 → 31. **I deliberately did
not touch yours:** a lint-only edit to your files risks conflicting with work you have in
flight, and the numbers are more useful to you as a list than as a surprise diff.

---

## 4. Context you may want

`docs/DEFECT-REGISTER.md` is new and is now the authoritative record of known defects and the
decisions about them. Two findings that touch you:

- **The $3.00/lesson cost baselines are wrong.** A duplication bug inflated real TTS spend
  roughly 4×, so every existing calibration was measured against bad numbers. If any of your
  analytics or reporting depends on those figures, treat them as unverified.
- **CES-final has never run against a real `ended_at`,** because sessions are never closed.

Nothing to action — just so you're not surprised.

---

## What I need from you

**Two things:**

1. **Option A, B or C on Story 2-35** (§1) — who implements the session endpoint. This is the
   demo blocker, so it's the one I'd like today.
2. **Your 22 ruff errors (§2)** — about ten minutes, and it's the larger half of what's kept CI
   red for weeks.

Everything else is FYI and yours to schedule.

Happy to pair on the mypy union-narrowing if useful — I did the same class of fix in
`content/router.py` this week and can share the pattern.
