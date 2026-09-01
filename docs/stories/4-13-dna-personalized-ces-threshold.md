---
title: "DNA-Personalized CES Intervention Threshold (S4-13)"
status: in-progress
baseline_commit: 04ab778426c4bfd9b557c2b756c929e556a6d9e3
owners: [Dev 3, Dev 4]
sprint: 4
---

# Story 4-13 — DNA-Personalized CES Intervention Threshold

## Problem Statement

Learner DNA scores (9 dimensions, computed from 20 onboarding questions + refined each
session via `dna_fusion.py`) are **purely decorative** — they are rendered as badges and
profile text but never fed back into the student's actual learning experience.

The CES intervention threshold (`settings.ces_threshold = 50.0`) is the same for every
student regardless of their Learner DNA profile. A student who naturally persists through
difficulty and handles frustration well gets the same "intervene at 50" rule as one who
gives up quickly and becomes frustrated easily. This is incorrect: the 20 onboarding
questions and every subsequent session are building a behavioural profile that should
personalise when the tutor acts.

This story closes the lifecycle loop: **DNA informs the threshold → threshold shapes
interventions → interventions shape session behaviour → session behaviour refines DNA →
refined DNA improves the next session's threshold → repeat**.

---

## User Story

As a learner using the HIE platform, I want the AI tutor to intervene at the right moment
for *me* — sooner if I tend to give up easily or get frustrated, later if I naturally push
through difficulty — so that interventions feel well-timed rather than intrusive.

---

## Acceptance Criteria

- **AC1** — `compute_personalized_threshold(persistence, frustration_tolerance, goal_orientation, settings)`
  exists in `assessment/ces.py`, returns a `float` in
  `[settings.ces_dna_threshold_min, settings.ces_dna_threshold_max]`, rounded to 2 d.p.

- **AC2** — When all three DNA inputs are `None` (student has no onboarding data),
  `compute_personalized_threshold` returns `settings.ces_threshold` exactly — no
  adjustment, no clamp, no error.

- **AC3** — `create_session_endpoint` (HTTP `POST /sessions`) calls
  `seed_personalized_ces_threshold(session_id, user_id, redis, supabase, settings)` after
  the session row is created. Failure to seed the threshold (Redis error, Supabase error)
  is logged at WARNING and does **not** fail the HTTP response — the session is created
  regardless.

- **AC4** — `seed_personalized_ces_threshold` reads DNA in this order:
  1. Redis cache `user:{user_id}:dna` (JSON blob, TTL 1 h)
  2. Supabase `learner_dna` table (fallback when cache miss)
  3. All-`None` (fallback when neither has data — first session / no onboarding)

- **AC5** — `seed_personalized_ces_threshold` writes
  `session:{session_id}:ces_threshold` to Redis with TTL 86 400 s (24 h).

- **AC6** — `process_attention_signal` in `tutor/service.py` reads the threshold from
  Redis key `session:{session_id}:ces_threshold` before the 2-consecutive-window check.
  If the key is absent (Redis miss, key expired), it falls back to
  `settings.ces_threshold` — the existing hardcoded behaviour is the fallback, never a
  hard failure.

- **AC7** — `compute_personalized_threshold` applies the formula:
  ```
  threshold = settings.ces_threshold
            + (frustration_tolerance - 50) × settings.ces_dna_weight_frustration
            + (50 - persistence)           × settings.ces_dna_weight_persistence
            + (50 - goal_orientation)      × settings.ces_dna_weight_goal
  ```
  then clamps to `[ces_dna_threshold_min, ces_dna_threshold_max]`.
  Each absent dimension contributes 0 to the formula (individual `None` safety).

- **AC8** — Five new env-var-tunable `Settings` fields exist in `config.py`:
  `CES_DNA_WEIGHT_FRUSTRATION` (default 0.08), `CES_DNA_WEIGHT_PERSISTENCE` (default 0.05),
  `CES_DNA_WEIGHT_GOAL` (default 0.04), `CES_DNA_THRESHOLD_MIN` (default 40.0),
  `CES_DNA_THRESHOLD_MAX` (default 65.0). All weights are `ge=0.0, le=1.0`. Changing any
  weight is an env var change only, no code change required.

- **AC9** — No DNA Supabase query runs on the hot 5-second `process_attention_signal`
  path. The threshold is pre-computed at session creation and read from Redis O(1) on the
  hot path.

- **AC10** — Formula direction verified by test: `frustration_tolerance=80, persistence=20,
  goal_orientation=20` → threshold > base. `frustration_tolerance=20, persistence=80,
  goal_orientation=80` → threshold < base.

---

## Scale & Load

**Q1 — Unit of work and range:**
One unit = computing and caching the personalized threshold per session creation.
The computation is 3 float multiplications + 1 Redis SET. Range: always O(1) regardless
of learner history or lesson length. The Redis GET on the hot path is also O(1).

**Q2 — Fixed budgets that meet variable inputs:**
- DNA read: `learner_dna` has UNIQUE(user_id) → 1 row max. Never unbounded.
- Redis cache read: 1 key GET. Never unbounded.
- Threshold value: clamped to [40.0, 65.0] regardless of DNA extremes. An all-max
  DNA student cannot produce a threshold above 65.0 or below 40.0. This is an
  explicit surfaced constraint (not silent truncation) — the clamp is logged at DEBUG
  when it activates.
- `ces_threshold` Redis key: expires at 86 400 s. A session longer than 24 h (impossible
  by design — CES monitoring only in TEACHING state, max lesson < 2 h) would lose the
  key; the fallback to `settings.ces_threshold` handles this without error.

**Q3 — Scope of limits:**
- Per-user: `user:{user_id}:dna` (1 key, 1 h TTL)
- Per-session: `session:{session_id}:ces_threshold` (1 key, 24 h TTL)
- Per-deployment: `settings.ces_dna_weight_*`, `ces_dna_threshold_min/max` (env vars)

**Q4 — Unbounded reads/writes:**
None. DNA SELECT uses `.maybe_single()` — at most 1 row (UNIQUE constraint). Redis GET
is a point lookup. Redis SET is a point write. No lists, no scans, no COUNT.

**Q5 — Inherited caps re-derived:**
- `ces_dna_threshold_min=40.0, ces_dna_threshold_max=65.0` — derived for first
  implementation based on: base is 50.0; maximum expected adjustment with default weights
  is ±(50 × 0.08 + 50 × 0.05 + 50 × 0.04) = ±8.5 → buffer chosen as ±10. To be
  re-derived during calibration sprint with real session data.
- Default weights (0.08, 0.05, 0.04) — chosen as small initial values to produce
  ≤8.5 point adjustment. Must be re-calibrated post-launch. These ARE env vars.

**Q6 — Check-then-act safety:**
- DNA read is read-only. No RMW race.
- Redis SETEX for threshold is atomic and idempotent (same session_id always produces
  the same key). Concurrent `POST /sessions` for the same session_id is blocked by the
  `sessions_open_unique` partial index (migration `20260831000000_sessions_open_unique`).

---

## Tasks / Subtasks

- [ ] **T1 (Dev 3) — Story file committed alone** ← you are reading this commit
- [ ] **T2 (Dev 3) — `compute_personalized_threshold()` in `assessment/ces.py`**
  - Pure function, no I/O, returns `float`, all `None` → base, clamped
  - Unit tests AC1, AC2, AC7, AC10
- [ ] **T3 (Dev 3) — 5 new Settings fields in `config.py`** (AC8)
- [ ] **T4 (Dev 3) — `seed_personalized_ces_threshold()` in `assessment/service.py`**
  - Redis cache → Supabase fallback → None fallback
  - Writes `session:{sid}:ces_threshold` with 24 h TTL
  - Failure is non-fatal (WARNING log, session creation succeeds)
  - Unit tests AC3, AC4, AC5
- [ ] **T5 (Dev 3) — Wire into `create_session_endpoint` in `assessment/router.py`**
  - After `create_session()` returns `session_id`, call `seed_personalized_ces_threshold`
  - Unit tests AC3 (endpoint integration)
- [ ] **T6 (Dev 4 — implemented by Dev 3 cross-team) — Read threshold from Redis in
       `tutor/service.py:process_attention_signal`**
  - Replace `settings.ces_threshold` at line 557 with Redis GET + fallback
  - Unit tests AC6, AC9
- [ ] **T7 — Run full suite, ruff, mypy** (zero regressions)

---

## Dev Notes

**Architecture decision:**
Threshold is pre-computed at HTTP `POST /sessions` (where JWT-verified `user_id` and
Supabase are available), not at WS `session_start`. This avoids any change to
`websocket.py` or `start_session()` and keeps the hot 5-second path to a single Redis
GET (AC9).

**DNA Redis cache format:**
`user:{user_id}:dna` stores a JSON string like
`{"pattern_recognition": 60.0, "persistence": 72.3, ...}`. Parse with `json.loads`.
Written by `process_onboarding` and `dna_fusion.py`. TTL 1 h — a cache miss on session
creation falls back to Supabase, which is correct behaviour.

**Dimension directions (from scoring fix S4-5):**
- `frustration_tolerance`: HIGH score = easily frustrated (index 3 answers) →
  intervention should fire SOONER → raise threshold.
- `persistence`: HIGH score = keeps trying (index 3 answers) →
  intervention can wait LONGER → lower threshold.
- `goal_orientation`: HIGH score = highly self-directed → lower threshold.

**Files touched:**
- `app/modules/assessment/ces.py` — add `compute_personalized_threshold()`
- `app/config.py` — 5 new fields
- `app/modules/assessment/service.py` — add `seed_personalized_ces_threshold()`
- `app/modules/assessment/router.py` — wire in `create_session_endpoint`
- `app/modules/tutor/service.py` — Redis GET + fallback at line ~557
- `tests/unit/test_s4_13_dna_ces_threshold.py` — all AC tests

---

## Senior Developer Review (AI)

_To be filled after implementation._

---

## Dev Agent Record

### File List
_To be filled during implementation._

### Change Log
_To be filled during implementation._
