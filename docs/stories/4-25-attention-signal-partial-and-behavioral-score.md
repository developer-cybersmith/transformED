---
baseline_commit: "1884f2b"
---

# Story 4-25: Attention signal contract — partial signals + ratified `behavioral_score`

**Status:** in-progress

---

## Story

As Dev 4,
I want `_parse_signal` to accept a partial attention signal (not all three of `behavioral_score` /
`head_pose_score` / `blink_rate` required) with proportional weight redistribution, and
`behavioral_score`'s definition ratified rather than left silent,
so that Dev 2 can ship MediaPipe head-pose detection first and blink/behavioral second (SYNC-B),
instead of the server rejecting every attention frame until all three land simultaneously.

Note: **`docs/LESSON-DELIVERY-TRACKER.md` L5's third defect (two disagreeing `compute_ces`
implementations) is explicitly OUT of scope for this story** — the user has directed that Dev 3
owns updating the CES-formula-reconciliation procedures/rules since Dev 3 is the one changing that
code. This story only touches the signal *parsing* boundary (`_parse_signal`), not
`compute_ces` itself.

---

## Context (verified 2026-08-11)

- `_parse_signal` (`service.py:54-100`) uses `_require_float` for `behavioral_score`,
  `head_pose_score`, and `blink_rate` — any one absent raises `ValueError` and the entire
  attention frame is rejected. `quiz_accuracy` / `teachback_score` already use `_optional_float`
  and tolerate `None`.
- `compute_ces` (`service.py:106-136`) is **already fully generic** over which signals are
  present: it builds `(value, weight)` pairs for all five signals, drops any `None`, and
  redistributes each present weight proportionally (`w / sum(present weights)`). This is not new
  logic to add — the CES math already does the right thing the moment `_parse_signal` lets a
  `None` through for any of the three MediaPipe-derived signals. **The gap is entirely at the
  parse boundary, not in the formula.**
- **A definition for `behavioral_score` already exists** — contrary to the framing in Dev 3's
  2026-08-05 handoff ("Dev 2 cannot invent it; you own the signal contract"), Dev 2 already wrote
  one down: `docs/dev2-frontend-role.md:91` and `docs/dev2-sprint-tracker.md:1550` both specify
  *"behavioral_score (0–1) from click/scroll/mouse activity events."* Nothing computes it yet on
  either side, and it has never been ratified into a frozen contract — that ratification, plus
  freezing an explicit range, is this story's other half.
- **`packages/shared/types/ws.ts` is frozen** (CLAUDE.md §16 — "Sprint 0 interface contract —
  frozen," 4-dev PR required to change). `AttentionSignalMessage.payload` currently declares
  `behavioral_score: number`, `head_pose_score: number`, `blink_rate: number` — no `| null`, no
  documented range. Widening these to `number | null` (required for partial-signal support to be
  contractually honest, not just server-tolerant) is a **structural change to a frozen file** and
  is explicitly **not done in this story** — flagged below as the 4-dev PR this story sets up but
  does not open.
- Danger already on record (L5 tracker): `assessment/service.py`'s `ces_contribution` is
  **already weight-multiplied**, so a reader who reasonably reaches for it gets a wrong number
  for "the fraction itself." Out of scope here (Dev 3's file), noted so nobody confuses this
  story's `NormalizedSignal` fractions with that field.

---

## Acceptance Criteria

- **AC 1:** `_parse_signal` accepts a payload missing any one, two, or all three of
  `behavioral_score` / `head_pose_score` / `blink_rate` without raising — each becomes `None` in
  `NormalizedSignal`, mirroring `quiz_accuracy`/`teachback_score`'s existing `_optional_float`
  treatment exactly.
- **AC 2:** A payload with **zero** of the five signals present (`quiz_accuracy`,
  `teachback_score`, `behavioral_score`, `head_pose_score`, `blink_rate` all `None`/absent) still
  raises `ValueError` — an attention frame carrying no attention data at all is a malformed
  message, not "everything is redistributed to 100%." This is the Scale Contract Q2 guard: a
  silent `CES = 0.0` (max-distraction reading) from an empty payload could falsely trigger an
  intervention, which is a worse failure than a loud rejection.
- **AC 3:** `compute_ces` redistribution is proven for every partial combination that matters —
  head-pose-only, blink-only, behavioral-only, and any two-of-three — not just the pre-existing
  teachback-only-None case. Confirms the formula needed no changes, only real inputs reaching it.
- **AC 4:** `NormalizedSignal`'s type annotations for `behavioral_score`, `head_pose_score`,
  `blink_rate` change from `float` to `float | None`, matching the two fields that were already
  optional.
- **AC 5:** `behavioral_score`'s definition is ratified in a non-frozen, Dev-4-owned document
  (`docs/ws-message-contract.md`) with an explicit 0–1 range and Dev 2's click/scroll/mouse-activity
  source — not left as a silently-typed bare `number`.
- **AC 6:** The frozen-contract gap (`ws.ts` declares `behavioral_score`/`head_pose_score`/
  `blink_rate` as non-nullable `number`, contradicting AC 1's server-side leniency) is explicitly
  flagged as a follow-up requiring a 4-dev-reviewed PR — not silently worked around, not silently
  left contradicting reality.
- **AC 7:** No regression to existing `_parse_signal` / `compute_ces` / `process_attention_signal`
  tests — the change is additive (fewer required fields), not a behavior change for payloads that
  already carry all three signals.

**Explicitly out of scope:** editing `packages/shared/types/ws.ts` (frozen); the CES-formula
duplicate reconciliation (Dev 3's, per the user's direction); any actual `behavioral_score`
computation logic (that's Dev 2's frontend work, unblocked but not built here).

---

## Scale & Load

1. **Unit of work:** one attention frame per tick, per session (~5s cadence per the Dev 4
   handoff's own Scale & Load section). This story does not change the cadence, only which fields
   within one frame are mandatory.
2. **Fixed budget vs variable input:** the "at least one real signal present" floor (AC 2) is the
   only new fixed constraint; it converts a would-be-silent `CES=0.0` misread into an explicit,
   loud `ValueError` surfaced to the caller (`_handle_attention_signal`'s existing best-effort
   error handling already logs and does not crash the socket).
3. **Scope:** per-message parsing logic; no new Redis keys, no new per-session or per-instance
   state.
4. **Unbounded:** none introduced — this story touches parsing and weight arithmetic only.
5. **Inherited caps:** N/A — no cap is being resized; three fields move from required to optional,
   which is a relaxation, not a new limit.
6. **Concurrency:** N/A — `_parse_signal` is a pure function with no shared state; nothing to race.

---

## Tasks / Subtasks

- [ ] 1.1 `service.py`: `NormalizedSignal.behavioral_score` / `.head_pose_score` / `.blink_rate` →
      `float | None`.
- [ ] 1.2 `service.py` `_parse_signal`: switch those three fields from `_require_float` to
      `_optional_float`.
- [ ] 1.3 `service.py` `_parse_signal`: add the "at least one signal present" guard (AC 2).
- [ ] 1.4 `test_tutor_service.py`: AC 1 tests (each field individually missing, all three missing
      but quiz/teachback present).
- [ ] 1.5 `test_tutor_service.py`: AC 2 test (all five absent → ValueError).
- [ ] 1.6 `test_tutor_service.py` / `test_ces.py`-style: AC 3 redistribution tests for the new
      partial combinations.
- [ ] 1.7 `docs/ws-message-contract.md`: ratify `behavioral_score` (AC 5) + flag the `ws.ts` gap
      (AC 6).
- [ ] 1.8 Update `docs/dev4-tracker.md`.
- [ ] 1.9 Full regression run on affected files.

---

## Dev Notes

### Why the "at least one signal" floor matters (AC 2)

`compute_ces`'s existing guard is `if weight_sum <= 0: return 0.0`. Before this story, that branch
was unreachable in practice — `_parse_signal` guaranteed `behavioral_score`/`head_pose_score`/
`blink_rate` were always present, so `weight_sum` could only be zero if `quiz_accuracy` and
`teachback_score` were *also* None, which still left three non-zero weights. Making all three
optional makes the true all-`None` case reachable for the first time, and returning `0.0` for
"we don't know" is indistinguishable from "you were watching a black screen" — with
`ces_threshold = 50`, two such windows falsely fire `distraction_detected`. AC 2 closes exactly
this gap.

### The frozen-contract follow-up this story owes (AC 6)

`packages/shared/types/ws.ts`'s `AttentionSignalMessage` needs `behavioral_score: number | null`,
`head_pose_score: number | null`, `blink_rate: number | null` to make the wire contract honest
once the backend accepts partial signals. That is a structural edit to a file marked "frozen" in
CLAUDE.md §16, requiring a 4-dev-reviewed PR — explicitly not opened by this story. Flagged to
Dev 2 + Dev 3 as the next SYNC-B step.
