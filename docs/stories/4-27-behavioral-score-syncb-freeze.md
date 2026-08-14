# Story 4-27 — Define behavioral_score + SYNC-B Wire Contract Freeze

**Status:** in-progress  
**Branch:** `sprint4/s4-27-behavioral-score-syncb`  
**Owner:** Dev 4 (wire contract + backend); Dev 2 + Dev 3 sign off on SYNC-B  
**Sprint:** Sprint 4 (Weeks 8–9)  
**Priority:** Critical — blocks Dev 2 L6 (MediaPipe), which blocks L7 end-to-end verification  
**Frozen contract change:** Yes — `packages/shared/types/ws.ts` is a frozen Week-1 contract.
This PR requires review by all 4 developers before merge (CLAUDE.md §"Interface Contracts").

---

## Context

Two contract gaps block Dev 2 from building L6 (MediaPipe attention capture):

1. **`behavioral_score` has no definition.** `ws.ts` declares it as `number` (required)
   and the backend accepts it as `float | None`, but neither document says what value
   to send. Dev 2 cannot emit a single frame without knowing what `behavioral_score`
   represents.

2. **`ws.ts` requires three MediaPipe fields as non-nullable** (`behavioral_score`,
   `head_pose_score`, `blink_rate` are typed `number`, not `number | null`), but the
   backend already accepts them as optional (`_optional_float` in `_parse_signal`).
   The TypeScript contract is stricter than the Python contract — when Dev 2 wires
   MediaPipe, they cannot send partial frames until this mismatch is fixed.

**SYNC-A** (which CES implementation survives) is already resolved in code:
`tutor/service.py:compute_ces` delegates to `assessment/ces.py` via `_canonical`,
and a CI guard (`test_ces_formula_defined_in_one_place`) enforces one-formula-one-file.
This story closes SYNC-A formally (tracker update + documentation note).

**SYNC-B** (wire scale, `behavioral_score` definition, partial signal validity) is
what this story delivers. Once merged, Dev 2 can build L6.

---

## Acceptance Criteria

### behavioral_score definition (T17)

**AC1** — `behavioral_score` is defined as the **tab-visibility score**:
- Value `1.0` when `document.visibilityState === 'visible'` (tab in foreground)
- Value `0.0` when tab is hidden (backgrounded, minimised, or `visibilityState !== 'visible'`)
- Range: [0.0, 1.0] — binary for MVP; a decay/interaction-recency model is a post-calibration
  enhancement (must not be built as part of this story)
- Rationale: a student whose tab is hidden is not receiving instruction; this signal
  correlates with intentional disengagement at zero implementation cost.

**AC2** — The definition is documented in `packages/shared/types/ws.ts` as a JSDoc comment
on the `behavioral_score` field, visible to Dev 2 when they open the file. It states:
the source (tab-visibility), the range (0.0–1.0), and when null is valid.

### Wire contract freeze (T19 + T20)

**AC3** — `AttentionSignalMessage` in `ws.ts` is updated so that all three MediaPipe fields
are typed `number | null`:
- `behavioral_score: number | null` — null when tab-visibility API is unavailable
  (e.g., iframe with cross-origin restrictions), or when the client deliberately omits it
- `head_pose_score: number | null` — null when MediaPipe has not initialised yet, or when
  a frame was dropped
- `blink_rate: number | null` — same as `head_pose_score`

**AC4** — All five numeric fields in the `AttentionSignalMessage` payload have an inline
range annotation comment: `// range: [0.0, 1.0]`. This is the SYNC-B field-scale freeze.
The scale for quiz_accuracy and teachback_score was already documented as range [0,1] in
spirit (they are fractions); this story makes the annotation explicit and uniform.

**AC5** — No change is made to `lesson.ts` or any other shared type. Only
`AttentionSignalMessage` in `ws.ts` is modified.

### Backend partial-signal tests (T19)

**AC6** — `_parse_signal` correctly handles a payload with `behavioral_score` missing
(absent key) and with `behavioral_score: null`:
- Missing key → `NormalizedSignal.behavioral_score = None` (no ValueError)
- `null` value → same result
- A non-finite behavioral_score (NaN, Inf) still raises ValueError

**AC7** — Three new unit tests cover partial MediaPipe signal paths through `compute_ces`:
- `behavioral_score=None`, head_pose and blink present → CES > 0 (redistribution, not zero)
- `behavioral_score=None, head_pose_score=None, blink_rate=None` (all MediaPipe absent),
  `quiz_accuracy=0.8` → CES ≈ 80.0 (quiz + any teachback only)
- All five signals None → CES = 0.0 (this test already exists in
  `test_s3_53_ces_production_closure.py`; reference it, do not duplicate it)

### SYNC-A closure (T16)

**AC8** — `assessment/ces.py` docstring already says "CANONICAL IMPLEMENTATION".
`tutor/service.py:compute_ces` already delegates via `_canonical`.
Guard test `test_ces_formula_defined_in_one_place` already CI-enforces one formula.
No code change needed. A comment is added to `tutor/service.py:compute_ces` noting
the SYNC-A resolution date and the guard test that enforces it.

**AC9** — `docs/LESSON-DELIVERY-TRACKER.md` is updated to mark SYNC-A resolved
and SYNC-B frozen (no more "Not started" for L5 items that are now unblocked).

---

## Dev Notes

### What does NOT change

- `tutor/service.py:_parse_signal` — already uses `_optional_float` for all three
  MediaPipe fields. Backend already accepts null.
- `assessment/ces.py:compute_ces` — already redistributes weights for any None signal.
- Any other contract file (`lesson.ts`, `lesson_package.schema.json`, migrations).
- The binary 0.0/1.0 definition is intentionally MVP-simple. Interaction-recency decay
  (last keypress/click within N seconds) is a named post-calibration enhancement; it
  must not be added here.

### What DOES change

1. `packages/shared/types/ws.ts` — three field types changed from `number` to
   `number | null`, JSDoc added.
2. `apps/api/tests/test_tutor_service.py` (or a new test file) — two new tests for
   partial MediaPipe signal paths through `_parse_signal` + `compute_ces`.
3. `docs/LESSON-DELIVERY-TRACKER.md` — L5 status update, SYNC-A/SYNC-B closure notes.

### ws.ts frozen contract reminder

`packages/shared/types/ws.ts` is a Week-1 frozen contract. This PR therefore requires
review + approval from all 4 developers before merge. The PR description must call this
out explicitly.

### Client implementation note for Dev 2

The simplest correct implementation for Dev 2 (L6):
```typescript
// attention_signal payload construction
const behavioral_score: number | null =
  typeof document !== 'undefined' && 'visibilityState' in document
    ? document.visibilityState === 'visible' ? 1.0 : 0.0
    : null;
```
Emit `null` for `head_pose_score` and `blink_rate` until MediaPipe is initialised.
The backend will compute CES from quiz_accuracy / teachback_score only until
MediaPipe signals arrive.

---

## Scale & Load

**Q1 — Unit of work:**
One attention frame payload processed by `_parse_signal`. Expected one frame per
`settings.ces_cadence_seconds` (default 5 s) per active session. Range: 1 frame/5 s
(normal), up to 1 frame/s if client overrides cadence (no server-side rate enforcement
exists — D52 rate limiter scope issue is a separate concern). The partial-signal path
is O(1) per frame regardless of which fields are present.

**Q2 — Fixed budgets vs variable input:**
`_parse_signal` processes a flat dict. Variable input = which of the five signal fields
are present. Budget is fixed: 5 fields × O(1) parse each. Partial signals (fewer than 5
fields) do not increase cost. All-None → `compute_ces` returns 0.0 (no error, no silent
wrong result — 0.0 is semantically correct: no engagement data available).

**Q3 — Scope of limits:**
The wire contract change (`ws.ts`) is global — one contract, all deployments. The
`behavioral_score` definition is also global. No per-user, per-instance scope issues.

**Q4 — Unbounded reads/writes:**
`_parse_signal` is pure (no I/O). No unbounded reads introduced. `BOUNDED: N/A` —
this story adds no reads or writes.

**Q5 — Inherited caps:**
The binary 0.0/1.0 range for `behavioral_score` is freshly derived here, not inherited.
The [0,1] range for all other fields was implicit; this story makes it explicit. No
inherited assumption left unreviewed.

**Q6 — Concurrent request safety:**
`_parse_signal` is a pure function. Concurrent calls on the same session_id from
multiple tabs are safe (no shared mutable state). Two tabs each emitting
`behavioral_score=1.0` produce two independent CES computations — correct because
both tabs are visible.

---

## Out of Scope

- Interaction-recency decay for `behavioral_score` (post-calibration enhancement)
- Field-range validation in `_parse_signal` (values outside [0,1] are clamped in
  `assessment/ces.py:compute_ces`, not rejected — clamping is the correct behaviour
  for a continuous signal)
- Scroll/keypress event tracking (a future behavioral_score enhancement)
- `quiz_accuracy` fraction exposure from the assessment module (T18 — Dev 3's task)
- T21/T22 consent modal and MediaPipe implementation (Dev 2, blocked by SYNC-B;
  now unblocked after this story merges)
- D64 (confusion-type intervention cap) — still open, separate story
