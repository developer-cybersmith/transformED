---
baseline_commit: 0cf8731
---

# Story 2.46: Session Report — Attention Timeline Chart (S3-05)

Status: review

## Story

As a student reviewing my session report,
I want to see how my engagement moved over the session and where a focus check-in happened,
so that I understand my own attention pattern without being shown a raw, judgmental score.

**Source:** `docs/dev2-sprint-tracker.md` §S3-05 (Sprint 3, P2, "Session Report: Attention Timeline
Chart") and §S3-06 ("Reports Page" — add: attention timeline chart once MediaPipe/attention data
exists). Unblocked 2026-08-10 once S3-02 (attention monitor) shipped and merged into
`sprint3-master`.

**Blocking-dependency finding (resolved by user decision, 2026-08-13):** the real
`GET /api/session/{id}/report` endpoint (`apps/api/app/modules/assessment/router.py:44-76`,
verified against the live code, not the tracker's description of it) does **not** expose a
per-window CES time series or intervention timestamps — only `ces_history_summary`
(`{mean, min, max, window_count}`, aggregate) and `intervention_messages_used` (a bare count).
A real "area chart of CES over session time... interventions as vertical lines" cannot be built
from what the API returns today. User decision: **extend the backend first, inside this same
story**, rather than deferring the whole story or faking a chart from insufficient data (which
would be exactly the "reports success while being wrong" shape CLAUDE.md's Scale Contract
exists to prevent).

**Second finding, discovered while designing the extension — do not re-litigate, it is settled
by `docs/DEFECT-REGISTER.md` D77 (new, this story):** `session:{id}:ces_history` in Redis is
`ltrim`'d to the last 10 windows (`tutor/service.py`, `_CES_HISTORY_MAX=10`) and nothing else
durably stores per-window CES. At the default 5 s cadence that is **the last ~50 seconds of the
session**, for a session of any length — a 20-minute session and a 50-second session return the
same 10 stored windows. Persisting the *full* session's CES history durably (a new
`sessions.ces_timeline` column or a `ces_windows` table, written incrementally) is a bigger,
separate change and is explicitly **out of scope here** — registered as D77 instead. This story
exposes the existing, real, capped Redis data and **labels it honestly as a recency window**,
never implying it covers the whole session. Do not silently present 10 windows as "the session."

**Cross-team note (flag to Dev 3):** the backend task below (Task 1) touches
`apps/api/app/modules/assessment/service.py` and `router.py`, which CLAUDE.md's team-ownership
table assigns to Dev 3 ("Quiz API, teachback scorer, CES formula, Learner DNA, session reports,
analytics"). Done here as a small, additive, read-only extension (new response fields only — no
change to the CES formula, no change to any existing field) to unblock Sprint 3 without a
cross-team handoff delay, per explicit user instruction. Dev 3 should review this story's Task 1
diff specifically.

## Acceptance Criteria

1. **AC-1 (backend)** — `SessionReport` (`apps/api/app/modules/assessment/router.py`) gains two
   new, additive, nullable fields: `ces_timeline: list[dict[str, float]] | None` — `[{"minute":
   float, "ces": float}, ...]` in chronological order (oldest first — note `ces_history` is
   LPUSH'd, so raw Redis order is newest-first and must be reversed), derived from the *same*
   `ces_history` read `get_session_report` already performs for `ces_history_summary` (do not
   add a second Redis round trip) — `minute = round((entry_t - started_at_unix) / 60.0, 2)` for
   entries carrying a real timestamp `t`; legacy bare-float entries (no `t`, backward-compat
   path) are excluded from the timeline (cannot be time-placed) but still counted in
   `ces_history_summary` exactly as today — and `intervention_events: list[dict[str, Any]] |
   None` — `[{"minute": float, "type": "distraction"|"fatigue"|"confusion"}, ...]`, built from a
   **new, bounded** (`.limit(20)` — safety ceiling; natural bound is `max_distraction_per_session`
   + 1 fatigue + uncapped-but-rare confusion per D64) query on `session_events` where
   `event_type='intervention_triggered'`, selecting `created_at` and `payload->>intervention_type`,
   same `minute` formula against `sessions.started_at`. Both fields are `None` (not `[]`) when
   Redis is unavailable, `started_at` is missing, or the underlying list/summary is empty — do
   not conflate "no data" with "zero at every point."
2. **AC-2 (backend)** — Neither new field changes the shape or values of any existing
   `SessionReport` field. `ces_history_summary`'s existing mean/min/max/window_count computation
   is untouched (same values, same rounding) — only augmented to also retain the `t` per entry
   for `ces_timeline`. Existing tests in `test_session_report_endpoint.py` for
   `ces_history_summary` must still pass unmodified.
3. **AC-3 (backend)** — `apps/web/src/types/assessment.ts`'s `SessionReport` interface gains the
   matching `ces_timeline` and `intervention_events` fields (`number|null`-safe, matching the
   backend's `| None` exactly — frozen-contract discipline, verify field-for-field against the
   real Python model, not the tracker prose, per Story 2-41's own precedent).
4. **AC-4 (frontend)** — New `AttentionChart.tsx` (`apps/web/src/components/reports/`) renders an
   area chart from `report.ces_timeline` using `recharts` (new dependency — no D3 from scratch,
   per the tracker). X-axis: minutes (real values from the data, not assumed evenly spaced).
   Y-axis: **qualitative bands only** — reuse the exact thresholds already established by
   `cesScoreColor`/`formatCesLabel` in `apps/web/src/lib/utils.ts` (>=70 high/emerald, 50-69
   medium/amber, <50 low/rose) rather than inventing new ones — tick labels "Low"/"Medium"/"High",
   never a raw CES number anywhere in the rendered chart (same "never show the raw score"
   convention as `CESIndicator.tsx` and `SessionReport.tsx`'s Focus tile — verify with a text-
   content regex test, per Story 2-41's precedent, not just a label-presence check).
5. **AC-5 (frontend)** — `report.intervention_events` entries render as vertical reference lines
   on the chart at their `minute` position, one per event, distinguishable by `intervention_type`
   (e.g. color or dash pattern) via a `title`/tooltip naming the type — never the raw
   `ces_at_trigger` value stored in the event payload (that field is never sent to the frontend
   at all per AC-1, so this is enforced by the contract, not just by convention).
6. **AC-6 (frontend)** — Explicit, visible degradation, not silence: when `ces_timeline` is
   `None` or has fewer than 2 points, render a small "Not enough data for a timeline yet" message
   instead of an empty/broken chart — mirroring `formatCesLabel`'s `null → "Not measured"`
   pattern. When `ces_timeline` has data, the chart must carry a caption stating it covers the
   most recent portion of the session (e.g. "last {window_count} readings"), never implying full-
   session coverage — this is the D77 degradation surfaced explicitly, not hidden.
7. **AC-7 (frontend)** — Responsive: `AttentionChart` uses a fluid/percentage-width container
   (`ResponsiveContainer` from recharts) so it fits `SessionReport.tsx`'s existing `max-w-2xl`
   card grid at any viewport; below a `sm` breakpoint the chart collapses to a simpler view (no
   X-axis tick labels, reduced height) rather than being cut off or scrolling horizontally.
8. **AC-8 (frontend)** — Mounted in `SessionReport.tsx` as its own card, placed after the existing
   4-stat grid and before `DnaSnapshotSection`, matching the existing `rounded-2xl bg-white
   border border-neutral-100 shadow-sm` card styling. Rendered conditionally — omitted entirely
   (not an empty card) when `report.ces_timeline` is `None`, matching how `DnaSnapshotSection` is
   already conditionally rendered.
9. **AC-9** — Tests: backend (`ces_timeline`/`intervention_events` computed correctly from a
   real-shaped `ces_history` + `session_events` fixture, minute math verified against a known
   `started_at`, `None` on Redis-down/no-data, existing `ces_history_summary` assertions
   unchanged), frontend (chart renders points, Y-axis never shows a raw number — regex-checked,
   intervention markers render at the right position with the right type distinguishable,
   `<2` points shows the fallback message, recency caption present, mobile collapse, conditional
   mount/omission in `SessionReport.tsx`). Full `apps/api` and `apps/web` suites green (net new
   failures = 0 against each suite's pre-existing baseline — see Dev Notes on how to verify
   that, matching this session's own merge-verification pattern), `tsc --noEmit` clean, `eslint`
   clean on every touched file.

## Scale & Load

Answering `docs/SCALE-CONTRACT.md`'s six questions.

1. **Unit of work and its range.** One unit = one session report render, containing at most
   `_CES_HISTORY_MAX=10` CES-timeline points and at most 20 intervention events (query-limited).
   Min: 0 points (session ended before any CES window, or Redis flushed — both already handled
   as `None` by existing code this story extends). Typical: 5-10 points for any session that
   reached TEACHING for >=25-50s. Largest actually possible: 10 points, 20 events — both hard
   caps, not observed maxima, so there is no "beyond it" case to degrade further.
2. **Fixed budgets vs. variable input.** The CES-timeline budget (10 windows) is fixed regardless
   of session length — this is D77, the whole point of this story's scoping decision: rather than
   silently truncating a 20-minute session to its last 50 seconds and presenting that as
   complete, AC-6 requires an explicit, visible caption naming the actual window shown. The
   intervention-events budget (`.limit(20)`) is a safety ceiling far above the natural bound
   (`max_distraction_per_session` default 3 + 1 fatigue + a handful of D64-uncapped confusion
   events) — if it is ever hit, AC-1's query still returns the 20 most recent by `created_at`
   ordering (not undefined order), so degradation there is graceful, not silent-wrong.
3. **Scope of every limit.** `_CES_HISTORY_MAX` is a per-session Redis key cap (each session gets
   its own `ces_history` key). The new `.limit(20)` on `session_events` is per-request (one
   `get_session_report` call), not per-user or per-instance — no shared-bucket risk.
4. **Unbounded reads/writes.** None introduced. The new `session_events` query is explicitly
   `.limit(20)`, matching the existing bounded pattern already used for `quiz_attempts`
   (`.limit(500)`) and `teachback_attempts` (`.limit(50)`) in the same function. The `ces_history`
   read reuses the existing `redis.lrange(key, 0, 9)` call — no new read added, same bound.
5. **Inherited caps re-derived?** `_CES_HISTORY_MAX=10` was sized for the CES-window/intervention-
   trigger use case (only the last 2 windows matter for the distraction check) — this story is the
   first consumer that cares about *all 10* for display, and the first to notice that "10" was
   never meant to answer "how did the whole session go." That mismatch is exactly D77, registered
   rather than worked around by quietly asking for more than 10 (which would change tutor/
   service.py's distraction-detection memory footprint for an unrelated feature) or by silently
   presenting 10 as complete (which would be the wrong kind of "fix").
6. **Concurrent check-then-act safety.** No check-then-act sequence is introduced — this story
   only adds read paths (a GET endpoint's response fields) with no new writes, so there is no
   race to reason about. The one existing write this story's data depends on
   (`write_intervention_event`, fire-and-forget `asyncio.create_task`) is unchanged.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 2 — backend): Extend `get_session_report` to compute `ces_timeline` and
  `intervention_events`; add both fields to the `SessionReport` response model.
  - [x] 1.1 RED: test that a `ces_history` fixture with real `{"v","t"}` entries and a known
    `started_at` produces `ces_timeline` with correct `minute` values, oldest-first; a fixture
    with legacy bare-float entries excludes them from `ces_timeline` but still counts them in
    `ces_history_summary`; `None` when Redis unavailable or history empty (existing behavior
    preserved for the summary half); a `session_events` fixture with 2 `intervention_triggered`
    rows produces matching `intervention_events` with correct `minute`/`type`; existing
    `ces_history_summary` tests still pass unmodified with no fixture changes.
  - [x] 1.2 GREEN: implement, reusing the existing `ces_history_summary` Redis read (no second
    round trip) and adding the new bounded `session_events` query. Also fixed 4 regressions this
    change caused in `test_session_report_endpoint.py`'s call-count-position-based mock (its
    `_build_report_supabase` builder hardcodes table-call positions; inserting a new call shifted
    everything after it by one) — updated the mock's position mapping and the two exact-call-count
    assertions (6→7, 7→8). Verified via worktree comparison against pre-story `sprint3-master`:
    19/19 pre-existing failures match exactly, zero new regressions.
- [x] Task 2 (AC: 3): Add `ces_timeline`/`intervention_events` to
  `apps/web/src/types/assessment.ts`'s `SessionReport`, verified field-for-field against the
  real (just-changed) Python model.
  - [x] 2.1 RED: `tsc --noEmit` confirmed a real TS2339 error before adding the fields (a pure
    type addition has no runtime RED signal — the story's own note was right that a fixture test
    alone wouldn't fail pre-implementation under esbuild's type-stripping transform). Added a
    runtime pass-through test in `assessment.test.ts` too, for the non-type-checked regression
    net.
  - [x] 2.2 GREEN: implement. Also had to add the two new fields to 2 pre-existing `SessionReport`
    object literals in `__tests__/types/assessment.test.ts` that broke once the fields became
    required (non-optional, nullable) — `tsc --noEmit` clean after.
- [x] Task 3 (AC: 4, 5, 6): Build `AttentionChart.tsx` — recharts area chart, qualitative Y-axis
  bands reusing `cesScoreColor`/`formatCesLabel` thresholds, intervention vertical markers,
  `<2`-points fallback message, recency caption.
  - [x] 3.1 RED: tests for each of AC-4 through AC-6 — points render, Y-axis ticks are
    Low/Medium/High only (regex-checked for absence of a raw decimal), markers render at correct
    minute with type distinguishable, `<2` points shows the fallback text, recency caption text
    present and correct for a given `window_count`.
  - [x] 3.2 GREEN: implement. Added `recharts` (`2.15.4` — chosen over the newer `3.10.1` after
    hitting a real, reproducible bug in this project's stack: v3's `<YAxis>` renders zero ticks
    under identical conditions to v2, so the switch is a correctness fix, not a downgrade of
    convenience) to `apps/web/package.json` via `pnpm --filter web add`.
    **Two jsdom-gap discoveries along the way, fixed in the shared `src/test/setup.ts`, not just
    locally:** (1) jsdom has no `ResizeObserver`, which `<ResponsiveContainer>` depends on to
    measure and render at a real size — added a polyfill that reports a fixed size
    synchronously. (2) recharts also reads its wrapper `<div>`'s `getBoundingClientRect()`
    directly; jsdom's all-zero default reproduces the same silent-empty-chart problem. Fixing
    this naively (faking a size for ANY zero-rect element) broke axis ticks almost entirely —
    recharts also creates temporary, invisible `<span>` elements to measure tick-label text
    width for its own overlap-avoidance algorithm, and faking THOSE to a large size made every
    label look like it overlapped its neighbor, silently dropping nearly all ticks with no error
    of any kind (Y-axis rendered zero ticks, X-axis rendered exactly one — the "survivor" of an
    overlap-elimination pass). Fixed by scoping the override to `tagName === 'DIV'` only (the
    responsive-container wrapper is a div; the measurement helper is a span). Both fixes are
    reusable for any future chart component, not just this one.
- [x] Task 4 (AC: 7): Responsive behavior — `ResponsiveContainer`, mobile collapse below `sm`.
  - [x] 4.1 RED: test that below the `sm` breakpoint, X-axis tick labels are absent and height is
    reduced (assert on rendered props/classes, not a real viewport resize, matching how other
    responsive components in this codebase are tested). Implemented together with Task 3 (the
    component's `isMobile` branch was built in the same pass) — tests cover both the mobile and
    desktop cases explicitly (X-axis ticks absent below `sm`, present at/above it).
  - [x] 4.2 GREEN: implement. Reused the existing `useMediaQuery` hook
    (`apps/web/src/hooks/use-media-query.ts`) — first real consumer of it in the codebase.
- [x] Task 5 (AC: 8): Mount `<AttentionChart />` in `SessionReport.tsx`, conditional on
  `report.ces_timeline !== null`, positioned after the 4-stat grid and before
  `DnaSnapshotSection`.
  - [x] 5.1 RED: test presence when `ces_timeline` is non-null, absence (not an empty card) when
    `null`. `AttentionChart` mocked in `SessionReport.test.tsx` (it has its own full test file) so
    these tests check `SessionReport`'s own prop-passing/conditional-mount behavior in isolation.
  - [x] 5.2 GREEN: implement.
- [x] Task 6 (AC: 9): Full `apps/api` and `apps/web` suites green (verify net-new failures = 0
  against each suite's current pre-existing baseline — see Dev Notes); `tsc --noEmit` clean;
  `eslint` clean on every touched file. Backend: full suite via disposable worktree comparison
  against pre-story `sprint3-master` — 230 failed / 52 errors identical on both, my branch has
  exactly +10 passed (the new test file), zero regressions. Frontend: 79 files / 957 tests
  passing (was 955 before Task 5's 2 new tests). `tsc --noEmit` clean. `eslint` clean on every
  touched file. Backend `ruff` unavailable in this local environment (pre-existing gap, not
  fixed here) — not run.

## Dev Notes

### What NOT to do

- Do NOT present the 10-window `ces_timeline` as if it were the whole session. AC-6's recency
  caption is not optional polish — it is the surfaced-degradation this story's design is built
  around (D77). A chart with no caption is a silent-truncation defect, not a finished feature.
- Do NOT add a second Redis read for `ces_timeline` — extend the existing `ces_history_summary`
  read in `get_session_report` to also retain `t`, matching the "process once" principle already
  used elsewhere in this codebase.
- Do NOT invent new Y-axis thresholds for the chart — reuse `cesScoreColor`/`formatCesLabel`'s
  exact 50/70 (on the 0-100 scale) boundaries from `apps/web/src/lib/utils.ts` so the chart and
  the Focus tile above it never disagree about what "Low"/"Medium"/"High" mean.
- Do NOT send `ces_at_trigger` (the raw CES value at the moment of an intervention, present in
  `session_events.payload`) to the frontend — only `minute` and `type`. AC-5 depends on this
  being enforced at the contract level, not by frontend discipline alone.
- Do NOT touch the CES formula, the distraction/fatigue trigger logic, or `_CES_HISTORY_MAX`
  itself — this story is a read-only, additive extension of the report endpoint. Widening
  `_CES_HISTORY_MAX` to "fix" the recency-window limitation is explicitly out of scope (that's
  D77's real fix, a separate story) and would silently change tutor/service.py's memory
  footprint for an unrelated feature.
- Do NOT assume `docs/ces-lifecycle-learner-scenarios.md` / `docs/ces-decisions-developer-guide.md`
  (Dev 3's CES reference docs, merged into `sprint3-master` 2026-08-13) are current on exact line
  numbers — this session's `throwaway` merge changed `tutor/service.py` around the very sections
  those docs cite. Verify against the real file, not the doc's line references.

### Testing standards

Follow Story 2-41's precedent: `usePlayerStore`-style direct-state tests are not applicable here
(this is a `useSessionReport`/SWR-backed page, not a Zustand store) — instead follow
`SessionReport.test.tsx`'s existing pattern of mocking `useSessionReport`'s return value directly
and asserting on rendered output. For the "never shows a raw CES number" AC, assert on rendered
text content with a decimal-pattern regex (`/\d\.\d/`), not just presence of the qualitative
label — per `docs/DEFECT-REGISTER.md` binding rule 2, a test may not assert only on a mock it
constructed; assert the actual rendered DOM. For the backend, verify `ces_history_summary`'s
existing tests still pass with zero fixture changes (proves AC-2's non-regression), and add a
premise-style test asserting the `minute` math against a hand-computed value for a known
`started_at` + `t`, not just "some number came back."

**Verifying no new regressions (this session's established pattern):** before this story's
final commit, use a disposable `git worktree add ../transformED-s305-check sprint3-master
--detach` to run the same `apps/api`/`apps/web` test files against the pre-story baseline, and
diff the failure sets — confirms new failures are actually new, not pre-existing (the merge
verification earlier this session found 23/25 "new" failures were pre-existing on `main` alone).
Remove the worktree (`git worktree remove --force`) when done.

### References

- [Source: docs/dev2-sprint-tracker.md §S3-05, §S3-06 — original AC text and file locations]
- [Source: apps/api/app/modules/assessment/router.py:44-76 — real `SessionReport` model, verified
  live 2026-08-13, not the tracker's description]
- [Source: apps/api/app/modules/assessment/service.py — `get_session_report`'s existing
  `ces_history_summary` block (S3-50/D18) to extend, and the `quiz_attempts`/`teachback_attempts`
  bounded-query pattern to match for the new `session_events` query]
- [Source: apps/api/app/modules/tutor/service.py — `_CES_HISTORY_MAX=10`, `ces_history`'s
  `{"v","t"}` JSON entry format and legacy bare-float fallback, D64's now-present `redis.expire`
  calls]
- [Source: apps/api/app/modules/tutor/state_machine/graph.py — `write_intervention_event`'s
  `session_events` row shape: `event_type`, `payload.intervention_type`, `created_at`]
- [Source: apps/web/src/lib/utils.ts — `cesScoreColor`/`formatCesLabel` thresholds to reuse
  exactly for the chart's Y-axis bands]
- [Source: apps/web/src/components/reports/SessionReport.tsx — existing card styling and
  conditional-render pattern (`DnaSnapshotSection`) to match]
- [Source: apps/web/src/hooks/useSessionReport.ts — SWR-backed data hook, no changes needed]
- [Source: docs/stories/2-41-ces-indicator.md — sibling Sprint 3 story, "never show the raw
  score" testing convention to follow exactly]
- [Source: docs/DEFECT-REGISTER.md D77 (new, this story) — the recency-window limitation this
  story must surface, not hide]
- [Source: docs/SCALE-CONTRACT.md — the six questions answered above]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-13 | Story created per S3-05 in `docs/dev2-sprint-tracker.md`. Branch `sprint3/s3-05-attention-timeline-chart` off `sprint3-master` (per explicit user instruction — not `main`, since `sprint3-master` carries this session's throwaway merge and reconciliation work this story's dev notes depend on). Blocking-dependency finding (report API lacks timeline/intervention-timestamp data) surfaced during pre-implementation analysis; user chose to extend the backend within this same story rather than deferring or faking the chart. Second finding (Redis `ces_history` caps at 10 windows regardless of session length) registered separately as D77, scoped out of this story. | Dev 2 |
| 2026-08-13 | All 6 tasks implemented, TDD (RED confirmed before each GREEN). Backend: `ces_timeline`/`intervention_events` added to `get_session_report`/`SessionReport`, reusing the existing `ces_history` Redis read. Frontend: `SessionReport` type extended; `AttentionChart.tsx` built on `recharts@2.15.4` (not `3.10.1` — see Task 3 notes for the real, reproducible bug that made this a correctness choice); two jsdom-gap polyfills added to the shared `src/test/setup.ts` (`ResizeObserver`, scoped `getBoundingClientRect`) reusable by any future chart component; wired into `SessionReport.tsx` after the stat grid, before the DNA snapshot. Backend suite verified via disposable worktree comparison against pre-story `sprint3-master`: 230 failed/52 errors identical on both sides, +10 passed (new tests only) on this branch, zero regressions. Frontend: 79 files/957 tests green, `tsc --noEmit` clean, `eslint` clean. Status → review. | Dev 2 |

## Dev Agent Record

### Implementation Plan

1. Verified the blocking-dependency finding by reading the real, current `get_session_report`/`SessionReport` code directly (not the tracker's description) — confirmed no per-window timeline or intervention-timestamp data was exposed, and confirmed the second finding (Redis `ces_history`'s 10-window cap) by reading `tutor/service.py`'s write side. Both surfaced to the user before writing any code; user decided scope for both.
2. Backend (Task 1): extended the existing `ces_history_summary` Redis-read loop (S3-50/D18) to also retain each entry's timestamp and build `ces_timeline`, rather than adding a second round trip. Added a new, bounded (`.limit(20)`) `session_events` query for raw intervention rows, computing `intervention_events` (`minute`+`type` only, never `ces_at_trigger`) once `started_at` was available. Discovered and fixed 4 test regressions caused by inserting a new DB call into `test_session_report_endpoint.py`'s position-indexed mock builder (a pre-existing fragility in that file, not introduced here, but newly triggered) — updated the mock's call-position mapping and two exact-call-count assertions.
3. Frontend type (Task 2): `tsc --noEmit` was the only real RED signal for a pure type addition (esbuild strips types without checking, so a runtime test alone wouldn't fail first). Fixed 2 pre-existing `SessionReport` object literals elsewhere in the test suite that broke once the new fields became required.
4. `AttentionChart.tsx` (Tasks 3-4): built against `recharts@3.10.1` first (the current major version) and hit a real, reproducible bug — `<YAxis>` rendered zero ticks under every configuration tried, traced down to jsdom-environment interactions, not a mistake in my own JSX. Switched to `recharts@2.15.4` (still React-19-compatible) after confirming the same class of issue existed there too, then found and fixed the actual root cause: my own `getBoundingClientRect` polyfill (needed for `<ResponsiveContainer>`) was also inflating recharts' internal tick-label-width-measurement `<span>` elements to a fake 800×400, making every tick look like it overlapped its neighbor and get silently dropped. Scoped the polyfill to `tagName === 'DIV'` only. Both this and a `ResizeObserver` polyfill (jsdom has none) were added to the shared `src/test/setup.ts`, not a local test-file mock, since any future chart component would hit the identical gap.
5. Wiring (Task 5): mocked `AttentionChart` inside `SessionReport.test.tsx` (it has its own complete test file) so those tests check only `SessionReport`'s own prop-passing and conditional-mount behavior.
6. Verification (Task 6): used this session's established worktree-comparison pattern (already used twice earlier for unrelated merges) to get an exact pre-existing-failure diff rather than eyeballing pass/fail counts.

### Completion Notes

- All 9 ACs satisfied, all 6 tasks and their subtasks complete.
- Backend: 10 new tests (`test_s3_05_attention_timeline_chart.py`), 4 pre-existing tests repaired in `test_session_report_endpoint.py` (mock-position fix + 2 call-count assertions), zero net regressions (worktree-verified: 230 failed/52 errors identical pre/post, +10 passed).
- Frontend: 9 new tests (`AttentionChart.test.tsx`), 2 new tests (`SessionReport.test.tsx` wiring), 1 new test (`assessment.test.ts` pass-through), 2 pre-existing fixtures repaired (`__tests__/types/assessment.test.ts`). 79 files/957 tests green. `tsc --noEmit` clean. `eslint` clean on every touched file.
- New dependency: `recharts@2.15.4` (chosen over the newer `3.10.1` after finding a real bug in it — see Dev Notes/Implementation Plan). Pre-approved by the story itself (AC-4 named a "lightweight chart library... recharts or a canvas-based solution").
- Two reusable jsdom-gap polyfills added to `apps/web/src/test/setup.ts` for any future chart component: a `ResizeObserver` stub, and a `getBoundingClientRect` override scoped to `<div>` elements only (NOT SVG elements — the scoping is the load-bearing detail; a naive version breaks recharts' own text-measurement machinery).
- D77 (docs/DEFECT-REGISTER.md, registered before implementation started) is deliberately NOT fixed by this story — `AttentionChart` correctly surfaces the 10-window recency limit via its caption rather than hiding it.

### File List

- `apps/api/app/modules/assessment/service.py` (MODIFIED — `ces_timeline`/`intervention_events` computation, new bounded `session_events` query)
- `apps/api/app/modules/assessment/router.py` (MODIFIED — 2 new `SessionReport` fields)
- `apps/api/tests/test_s3_05_attention_timeline_chart.py` (NEW — 10 tests)
- `apps/api/tests/test_session_report_endpoint.py` (MODIFIED — mock call-position fix, 2 call-count assertions updated for the new query)
- `apps/web/src/types/assessment.ts` (MODIFIED — 2 new `SessionReport` fields)
- `apps/web/src/__tests__/types/assessment.test.ts` (MODIFIED — 2 pre-existing fixtures updated for the new required fields)
- `apps/web/src/__tests__/lib/assessment.test.ts` (MODIFIED — 1 new pass-through test)
- `apps/web/src/components/reports/AttentionChart.tsx` (NEW — the chart component)
- `apps/web/src/__tests__/components/reports/AttentionChart.test.tsx` (NEW — 9 tests)
- `apps/web/src/components/reports/SessionReport.tsx` (MODIFIED — mounts `<AttentionChart />`)
- `apps/web/src/__tests__/components/reports/SessionReport.test.tsx` (MODIFIED — `AttentionChart` mocked, fixture extended, 2 new wiring tests)
- `apps/web/src/test/setup.ts` (MODIFIED — `ResizeObserver` polyfill, scoped `getBoundingClientRect` override)
- `apps/web/package.json` (MODIFIED — added `recharts@2.15.4`)
- `pnpm-lock.yaml` (MODIFIED — lockfile update for the new dependency)
- `docs/DEFECT-REGISTER.md` (MODIFIED — registered D77, and separately the D61-D64 reconciliation notes from the prior turn)
