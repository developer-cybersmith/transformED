---
id: "S3-42"
title: "CES breakdown accuracy — behavioral/head_pose/blink from Redis history (D72)"
status: "Done"
sprint: 3
story_points: 3
owner: Dev3
priority: P1
defect_ref: D72
depends_on: ["S3-34"]
branch: "sprint3/s3-42-ces-breakdown-accuracy"
migration: "NO"
---

# Story S3-42 — CES Breakdown Accuracy: behavioral/head_pose/blink from Redis History (D72)

## Context

**Defect D72 (now CLOSED):** `get_session_report` in `apps/api/app/modules/assessment/service.py`
hardcoded `"behavioral": 0.0`, `"head_pose": 0.0`, `"blink": 0.0` in the `ces_breakdown` dict.
This meant the reported `ces_breakdown` was always wrong for any session with attention signals:
the five component values never summed to `ces_score`, and behavioral/head_pose/blink were
always zero regardless of actual attention quality.

**Root cause:** `process_attention_signal` in `apps/api/app/modules/tutor/service.py` stored only
the composite CES value in Redis (`session:{session_id}:ces_history`). The three individual signal
components (`behavioral_score`, `head_pose_score`, `blink_rate`) were never persisted separately,
so `get_session_report` had nothing to read and fell back to the hardcoded zeros.

**Dependency on S3-34:** The Redis key structure (`session:{sid}:ces_history`, `_CES_HISTORY_MAX`,
`_CES_WINDOW_TTL`) was established by S3-34. This story adds three parallel lists on the same
pattern; S3-34 must be merged first.

**Decisions covered:** D3 (per-signal Redis history lists in process_attention_signal;
ces_breakdown reads from those lists), D2 (ces_breakdown weighted contributions use
`settings.ces_weight_*` env vars, matching the real-time formula).

## User Story

**As a** student viewing my session report after a lesson,
**I want** the `ces_breakdown` to show my actual behavioral, head_pose, and blink attention
contributions drawn from the real signals captured during my session,
**so that** the breakdown reflects my true engagement and the five component values sum to
my actual CES score rather than showing zeros for three of the five components.

**As the** system computing a session report,
**I want** `get_session_report` to read per-signal Redis history lists written by
`process_attention_signal` and compute weighted contributions using `settings.ces_weight_*`,
**so that** `ces_breakdown` is accurate for every session that received attention signals and
correctly returns 0.0 only for sessions with no captured signals (not as a hardcoded default).

## Acceptance Criteria

### AC 1 — Per-signal Redis history keys are populated by process_attention_signal

After each call to `process_attention_signal`, Redis contains three new entries alongside the
existing `ces_history` write:

- `session:{session_id}:behavioral_history` — contains the `behavioral_score` float
- `session:{session_id}:head_pose_history` — contains the `head_pose_score` float
- `session:{session_id}:blink_history` — contains the `blink_rate` float

Each list is written via `lpush` (newest entry at index 0) and each key carries the same
`_CES_WINDOW_TTL` = 86400 s TTL as `ces_history`.

**Exact assertion:** Calling `process_attention_signal("sess-001", signal)` with
`behavioral_score=0.6, head_pose_score=0.5, blink_rate=0.4` causes `lpush` to be called
with a key containing `"behavioral_history"`, a key containing `"head_pose_history"`, and a
key containing `"blink_history"`.

### AC 2 — Histories are bounded to _CES_HISTORY_MAX entries (lpush + ltrim pattern)

Each per-signal history list is trimmed to `_CES_HISTORY_MAX` (= 10) entries after each push,
matching the `ces_history` pattern exactly. Index 0 is the most-recent value; no more than 10
entries survive. The `ltrim` end argument equals `_CES_HISTORY_MAX - 1` (= 9).

**Exact assertion:** After `process_attention_signal` runs, `ltrim(behavioral_history_key, 0, 9)`
is called. Trim end = `_CES_HISTORY_MAX - 1`.

### AC 3 — get_session_report reads signal histories and computes weighted contributions

`get_session_report` accepts a `redis` parameter (keyword-only, default `None`). When `redis`
is provided:

- It reads `session:{session_id}:behavioral_history` via `lrange(key, 0, -1)`
- It reads `session:{session_id}:head_pose_history` via `lrange(key, 0, -1)`
- It reads `session:{session_id}:blink_history` via `lrange(key, 0, -1)`
- It computes contributions: `avg(values) * settings.ces_weight_<signal> * 100`

**Exact formula (default weights):**
```
behavioral_contribution  = mean(behavioral_history_values)  * 0.20 * 100
head_pose_contribution   = mean(head_pose_history_values)   * 0.12 * 100
blink_contribution       = mean(blink_history_values)       * 0.08 * 100
```

**Exact assertion:** With `behavioral_history = [0.8, 0.6]`, `mean = 0.7`,
`behavioral_contribution = round(0.7 * 0.20 * 100, 4) = 14.0`.
With `head_pose_history = [0.5]`, `mean = 0.5`,
`head_pose_contribution = round(0.5 * 0.12 * 100, 4) = 6.0`.
With `blink_history = [0.4, 0.4, 0.4]`, `mean = 0.4`,
`blink_contribution = round(0.4 * 0.08 * 100, 4) = 3.2`.

### AC 4 — Empty signal history yields 0.0 contribution (not an error)

When Redis lists are empty (no attention signals recorded, or TTL expired), all three
contributions are `0.0`. No exception is raised; no error is logged at ERROR level.

**Exact assertion:** With `lrange` returning `[]` for all three keys,
`ces_breakdown["behavioral"] == 0.0`, `ces_breakdown["head_pose"] == 0.0`,
`ces_breakdown["blink"] == 0.0`. Function does not raise `ZeroDivisionError`.

When `redis=None` (not injected), same 0.0 result — fail-open behaviour.

### AC 5 — Contributions use settings.ces_weight_* (not hardcoded floats)

The `get_session_report` source references `settings.ces_weight_behavioral`,
`settings.ces_weight_head_pose`, and `settings.ces_weight_blink` — never hardcoded values
`0.20`, `0.12`, `0.08`.

**Exact assertion (source inspection):** `inspect.getsource(get_session_report)` contains the
strings `"ces_weight_behavioral"`, `"ces_weight_head_pose"`, `"ces_weight_blink"`.

### AC 6 — CI guard: no hardcoded 0.0 for behavioral/head_pose/blink in get_session_report

A source-inspection CI guard (in `test_s3_42_ces_breakdown_accuracy.py`) asserts that the
string `'"behavioral": 0.0'` does NOT appear in `get_session_report`'s source. Same guard
for `'"head_pose": 0.0'` and `'"blink": 0.0'`. This prevents re-introduction of the deferred
Sprint 2 hardcoded values.

**Exact assertion:** `'"behavioral": 0.0' not in inspect.getsource(get_session_report)` passes.

### AC 7 — D72 in DEFECT-REGISTER.md updated to FIXED with guard test name

`docs/DEFECT-REGISTER.md` entry for D72 is updated to CLOSED status and names the CI guard
test `test_ces_breakdown_no_hardcoded_zero_for_behavioral` as the enforcement mechanism.

**Exact assertion:** The string `"test_ces_breakdown_no_hardcoded_zero_for_behavioral"` appears
in `docs/DEFECT-REGISTER.md`.

## Tasks / Subtasks

### Task 1 — Story file (story-first gate)
- [x] 1.1 Create `docs/stories/S3-42-ces-breakdown-accuracy-behavioral-head-p.md`
- [x] 1.2 Commit story-only to `sprint3/s3-42-ces-breakdown-accuracy`
- [x] 1.3 Push to remote before any implementation

### Task 2 — RED phase (failing tests)
- [x] 2.1 Create `apps/api/tests/test_s3_42_ces_breakdown_accuracy.py`
- [x] 2.2 Test AC 1 — source guard: `behavioral_history` in `process_attention_signal` source
- [x] 2.3 Test AC 1 — runtime: `process_attention_signal` lpushes all 3 component keys
- [x] 2.4 Test AC 2 — runtime: `ltrim` end = `_CES_HISTORY_MAX - 1` for behavioral_history
- [x] 2.5 Test AC 3 — source guard: `get_session_report` has `redis` parameter
- [x] 2.6 Test AC 3 — source guard: source reads `behavioral_history`, `head_pose_history`, `blink_history`
- [x] 2.7 Test AC 4 — source guard: empty lrange is handled safely
- [x] 2.8 Test AC 5 — source guard: `ces_weight_behavioral/head_pose/blink` in source
- [x] 2.9 Test AC 6 — CI guard: `'"behavioral": 0.0'` not in source
- [x] 2.10 Confirm all tests FAIL before implementation

### Task 3 — GREEN phase (implementation)
- [x] 3.1 `apps/api/app/modules/tutor/service.py`: add lpush/ltrim/expire for
          `behavioral_history`, `head_pose_history`, `blink_history` in `process_attention_signal`
- [x] 3.2 `apps/api/app/modules/assessment/service.py`: add `redis: Any = None` parameter
          to `get_session_report`; implement `_signal_avg()` closure; compute weighted contributions
- [x] 3.3 `apps/api/app/modules/assessment/router.py`: update `get_session_report_endpoint`
          to pass `redis=get_redis()` to `get_session_report`
- [x] 3.4 Remove the three hardcoded `0.0` lines and the "Sprint 2 deferred" comment
- [x] 3.5 Confirm all AC tests PASS

### Task 4 — REFACTOR + validation
- [x] 4.1 `ruff check .` — zero new errors repo-wide
- [x] 4.2 `ruff format --check` — zero format violations
- [x] 4.3 Full Dev 3 regression suite GREEN
- [x] 4.4 Confirm existing `test_session_report_endpoint.py` tests pass (no regressions)

### Task 5 — Register update
- [x] 5.1 Update D72 in `docs/DEFECT-REGISTER.md` to CLOSED/FIXED with guard test name

### Task 6 — 6-agent adversarial review
- [x] 6.1 Layer 1 — Story Quality
- [x] 6.2 Layer 2 — Blind Hunter (Security)
- [x] 6.3 Layer 3 — Test Coverage
- [x] 6.4 Layer 4 — AC Completeness
- [x] 6.5 Layer 5 — Process Integrity
- [x] 6.6 Layer 6 — Scale & Load

### Task 7 — Commit + push
- [x] 7.1 Final implementation commit on `sprint3/s3-42-ces-breakdown-accuracy`
- [x] 7.2 Push to remote
- [x] 7.3 Update `docs/dev3-assessment-tracker.md`

## Scale & Load

### Q1 — What is ONE unit of work, and what is its range?

One unit of work on the write path is a single call to `process_attention_signal`, which adds
one float to each of three Redis lists via `lpush`. Attention signals arrive every ~5 seconds
while the tutor FSM is in TEACHING state.

- **Min:** 0 lpush calls per session (lesson never enters TEACHING; student disconnects
  immediately). All three history lists remain empty. `get_session_report` returns `0.0`
  for all three contributions — correct behaviour.
- **Typical:** ~360 windows for a 30-minute lesson (~1,800 s / 5 s/window).
  After `ltrim`, each list holds exactly `min(360, 10) = 10` entries.
- **Largest measured:** ~720 windows for a 60-minute session. Same result: 10 entries post-trim.
- **Beyond the bound:** `_CES_HISTORY_MAX = 10` hard-caps every list regardless of session
  length. A 4-hour session produces the same 10-entry lists as a 30-minute session. No growth.

One unit of work on the read path is three `lrange` calls in `get_session_report`. Each
`lrange(key, 0, -1)` reads at most `_CES_HISTORY_MAX = 10` entries (the trim enforces this).

### Q2 — Which budgets are FIXED while the input VARIES — and what happens past them?

| Budget | Value | Scope | Past the limit |
|--------|-------|-------|----------------|
| Per-signal list length | `_CES_HISTORY_MAX = 10` entries | Per session, per signal component | `ltrim` enforces: the 11th entry pushes the oldest off. Never grows beyond 10. Explicit ordered eviction, not silent truncation. |
| Redis TTL | `_CES_WINDOW_TTL = 86400` s (24 h) | Per session key | After 24 h, Redis evicts. `lrange` returns `[]`. `_signal_avg` returns `0.0` — fail-open. Caller is informed via the `0.0` contribution value. |
| Floats per read | 10 floats per lrange call | Per lrange call | Bounded by ltrim above — `lrange(0, -1)` reads at most 10. Cannot grow. |

No silent truncation: `ltrim` is an explicit, ordered eviction (keep newest 10). The average
over 10 windows is a valid representative sample of recent engagement quality.

### Q3 — What is the SCOPE of every limit?

| Limit | Scope | Justification |
|-------|-------|---------------|
| `_CES_HISTORY_MAX = 10` | Per session (Redis key is `session:{sid}:*`) | Each session has its own three lists, completely isolated. Concurrent sessions do not share keys. |
| `_CES_WINDOW_TTL = 86400` | Per session key | Key expires 24 h after last write. Not shared across sessions or instances. |
| Redis itself | Per deployment (single Railway Redis instance) | `get_redis()` connects to `REDIS_URL` — one shared store. Each session's lists are independent and bounded (30 bytes x 10 entries = 300 bytes per list, 900 bytes per session for all three). |

Worker-count independence: Railway can run multiple FastAPI workers; all share the same Redis.
`lpush` is atomic; concurrent signals to the same session from different workers interleave
safely (both push, ltrim enforces the bound on whichever runs last).

### Q4 — Which reads and writes are UNBOUNDED?

None introduced by this story.

- **Writes:** `lpush` + `ltrim` + `expire` — three atomic Redis operations per signal component.
  `ltrim` enforces the 10-entry cap.
- **Reads:** `lrange(key, 0, -1)` — reads all entries. Because `ltrim` has already bounded the
  list to 10 entries, `lrange(0, -1)` reads at most 10 values. Not a full-table scan.
- **Existing `get_session_report` DB reads:** Not changed by this story. The `quiz_attempts`
  and `teachback_attempts` reads carry `.execute()` without `.limit()` — these are bounded by
  session scope (a session cannot have more quiz_attempts than the number of quiz questions in
  the lesson). This is a pre-existing constraint, not new to this story.

### Q5 — Which caps were INHERITED from an earlier design, and have they been re-derived?

`_CES_HISTORY_MAX = 10` was established by S3-34 for `ces_history`. This story inherits that
cap for the three new per-signal lists on the same pattern.

Re-derivation for this use: the average over the last 10 windows = last 50 seconds of TEACHING
data. This is sufficient for the breakdown: 50 s is recency-relevant (2x the 2-window
intervention trigger period) and avoids unbounded growth. The inherited cap is valid.

`_CES_WINDOW_TTL = 86400` s likewise inherited from S3-34. Valid: session data is only
meaningful within 24 h; stale signal history after 24 h should produce 0.0 (fail-open), which
is what the empty-list path produces.

### Q6 — Is every check-then-act sequence safe under CONCURRENT requests?

No check-then-act sequences are introduced by this story.

- `lpush` is atomic. Two concurrent `process_attention_signal` calls for the same session will
  both push their values; `ltrim` on each will atomically trim to 10. The ordering of concurrent
  trims does not matter: both trim to the same bound, and the result is always at most 10 entries.
  No lost updates; no overcounting.
- `lrange` in `get_session_report` is read-only. Concurrent reads are safe.
- No EXISTS + SET pattern. No SELECT + INSERT pattern. Pure append + trim + average.

## Security

### Authentication and ownership

`get_session_report` is called from `GET /api/assessment/session/{id}/report`, which is
JWT-protected. The existing ownership check (`session.user_id == current_user["sub"]`) runs
before any Redis read in this story. An attacker cannot read another user's signal histories
by guessing a `session_id` — the SEC-006 404 oracle guard returns the same error for
non-existent and wrong-user sessions.

### Redis key namespacing

Per-signal history keys are `session:{session_id}:behavioral_history`, `head_pose_history`,
`blink_history`. The `session_id` is a server-minted UUIDv4 from the `sessions` table. It is
not predictable by a client. No client can set arbitrary Redis keys through the signal path.

### Information disclosure

Raw webcam video never reaches the server (CLAUDE.md §18). The Redis lists store floats
(0-1 normalised scores). `ces_breakdown` values in the session report are floats on the 0-100
scale (engagement contribution). No clinical or biometric data is exposed.

### No new attack surface

No new HTTP endpoints. No new DB tables. No new migrations. Only two existing functions
modified. `_signal_avg` wraps every Redis call in `try/except Exception` — Redis errors log
at WARNING and return `0.0` (fail-open). A Redis outage never causes a 500 on the report
endpoint.

## Test Requirements

All tests live in `apps/api/tests/test_s3_42_ces_breakdown_accuracy.py` and are
`@pytest.mark.unit` (no real Redis, no real DB).

| Test name | AC | Type |
|-----------|-----|------|
| `test_ces_breakdown_no_hardcoded_zero_for_behavioral` | AC 6 | Source inspection CI guard |
| `test_process_attention_signal_source_contains_behavioral_history` | AC 1 | Source inspection |
| `test_process_attention_signal_source_contains_head_pose_and_blink_history` | AC 1 | Source inspection |
| `test_process_attention_signal_uses_lpush_for_signal_histories` | AC 2 | Source inspection |
| `test_process_attention_signal_lpushes_all_three_components` | AC 1 | Runtime (mocked Redis) |
| `test_process_attention_signal_trims_behavioral_history_to_max` | AC 2 | Runtime (mocked Redis) |
| `test_get_session_report_signature_accepts_redis` | AC 3 | Source inspection |
| `test_get_session_report_source_reads_behavioral_history` | AC 3 | Source inspection |
| `test_get_session_report_handles_empty_signal_history` | AC 4 | Source inspection |
| `test_ces_breakdown_uses_settings_weights_not_hardcoded` | AC 5 | Source inspection |

**Regression tests** (no changes required, must remain GREEN):
- `apps/api/tests/test_session_report_endpoint.py` — full existing suite (AC 7-14 from Sprint 2).
  In particular, `test_get_report_ces_breakdown_attention_zero_when_no_redis` must pass
  (asserts zero-when-no-redis-data, which is correct for the right reason).

## Decision References

| Decision | Description | This story |
|----------|-------------|------------|
| D2 | Redistribute weights when teachback=None | Not in this story scope. Redistribution lives in `compute_ces`; `ces_breakdown` uses raw averages x weights, not the redistributed formula. |
| D3 | Per-signal Redis history lists in `process_attention_signal`; `ces_breakdown` reads from those lists | Implemented as lpush/ltrim/lrange for `behavioral_history`, `head_pose_history`, `blink_history`. Implementation uses lists, not hashes. |

## Dependencies

**S3-34** (must be merged first): Establishes `session:{sid}:ces_history`, `_CES_HISTORY_MAX`,
`_CES_WINDOW_TTL`, `process_attention_signal`, and the Redis key pattern this story extends.

## Migration

**NO** — This story modifies Redis write/read behaviour only. No new Supabase tables, columns,
or constraints. `supabase/migrations/` is unchanged.

## Status

**Done** — Implementation committed `6f79834` on branch `sprint3/s3-42-ces-breakdown-accuracy`.
D72 closed in `docs/DEFECT-REGISTER.md`.
CI guard `test_ces_breakdown_no_hardcoded_zero_for_behavioral` active.
