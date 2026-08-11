---
id: "3-38"
title: "tts_node measures REAL audio duration — package_builder stops guessing slide timing"
status: "ready-for-dev"
sprint: 3
story_points: 3
baseline_commit: "9c6372b"
owner: Dev1
priority: P2
blocker_ref: "N/A — no existing docs/DEFECT-REGISTER.md entry names this gap; found directly by
  reading tts_node/package_builder_node together during Sprint 3 audit (see Context below).
  Deliberately not allocating a new D-id in this story: this branch and two sibling worktrees
  (sprint3/s3-37-narration-char-cap, sprint3/s3-39-surface-section-truncation) all branch from
  the same commit 9c6372b and could race to claim the same next number — the register's own
  D62 entry documents that exact collision already happening twice on 2026-08-06. Whoever merges
  first can allocate the id against the merged register without three branches guessing at once."
---

# Story 3-38 — tts_node measures REAL audio duration (package_builder stops guessing)

## Context & Scope Boundary

**Why this story exists.** `tts_node` (`graph.py:3335`) ships `Narration.timestamps=[]` on
every path — the success path (`graph.py:~3474` pre-fix), the per-segment exception/degrade
path (`~3490`), and the `_fallback_narration` helper (`~3836`). `package_builder_node` then
calls `_estimate_slide_timestamps` (`~3746`) to backfill that empty list, and that function
**guesses** the segment's audio duration from `word_count / words_per_minute` — a pure estimate
with zero relationship to the bytes actually synthesized by Sarvam/Azure. The player's slide
sync (`timestamps` — binary search by playback time) and the segment-end quiz trigger
(`timestamps.at(-1).end_ms`) both depend on this track being close to the real audio, and until
this story nobody had ever measured the gap between the guess and reality for a single real
lesson.

**What this story does NOT do:**
- Does not add a new field to `Narration` or to
  `packages/shared/lesson_package.schema.json` / `packages/shared/types/lesson.ts` — all FOUR
  frozen (CLAUDE.md §"Interface Contracts"). `Narration.timestamps` already exists in the frozen
  schema; this story changes what value it carries, not the schema.
- Does not add word-level / forced-alignment timing — slides are still evenly split across the
  segment's total duration (Story 2-8/2-19's original scope decision). Only the *source* of the
  total duration changes: real (measured) instead of always-estimated.
- Does not touch `slide_generator_node`, `narration_script_generator_node`, or any Phase 1/2
  node — the fix is entirely inside `tts_node`'s per-segment loop and
  `package_builder_node`'s existing lookup-table + `_estimate_slide_timestamps` call site.
- Does not change `_estimate_slide_timestamps`'s behavior for any existing caller/test that
  doesn't pass the new `known_duration_ms` keyword — omitting it (the default) reproduces the
  exact prior word-count-estimate code path, unchanged line-for-line in its branch.

**What this story does:**
1. Adds `mutagen` (MIT, pure-Python-ish, no ffmpeg binary — audio-metadata-only, consistent
   with CLAUDE.md's "no video/ffmpeg code exists yet" stance) as a runtime dependency.
2. `tts_node`, right after a successful synthesis produces real `audio_bytes`
   (`graph.py:~3451`), measures the REAL duration in milliseconds via
   `mutagen.mp3.MP3(io.BytesIO(audio_bytes)).info.length * 1000`, wrapped in its own
   try/except (a parse failure degrades to `duration_ms=None`, never crashes the segment —
   this node's entire documented purpose is to never hard-fail).
3. Carries that value as a **sibling** `"duration_ms"` key on the per-segment `audio_assets`
   wrapper dict (`{"segment_id": ..., "data": ..., "duration_ms": ...}`) — NOT inside `"data"`,
   because `"data"` is exactly the frozen, `extra="forbid"` `Narration.model_dump()` payload and
   a new key there would raise on any future `model_validate` round-trip.
4. `package_builder_node` reads that sibling key into a small `duration_ms_by_id` dict
   comprehension (mirroring the existing `audio_by_id = _index_by_segment_id(...)` lookup one
   line above it) and passes the segment's value into `_estimate_slide_timestamps` via a new
   optional `known_duration_ms` keyword — used directly as the total duration when not `None`;
   the pre-existing word-count estimate is the fallback, byte-for-byte unchanged, when it is
   `None` (browser fallback or an unparseable buffer).

## Story

**As** a student playing a generated lesson,
**I want** the slide-sync timestamps in my lesson package to be built from the REAL duration of
the narration audio that will actually play, not a word-count guess,
**so that** slide changes (and the segment-end quiz trigger) land at the moments the real audio
is actually at, instead of visibly drifting further out of sync the longer a segment runs.

## Acceptance Criteria

### Functional

- [ ] **AC 1.** `mutagen>=1.47.0` is added to `apps/api/pyproject.toml`'s `[project]`
  `dependencies` list, with a comment noting it is audio-metadata-only (no ffmpeg binary,
  not a video/transcoding dependency).
- [ ] **AC 2.** On `tts_node`'s success path (`audio_bytes is not None`, i.e. Sarvam or Azure
  actually returned audio), the node measures the real duration in milliseconds from those exact
  bytes via `mutagen.mp3.MP3` and rounds to the nearest int.
- [ ] **AC 3.** A `mutagen` parse failure (corrupt/empty/non-MP3 buffer) is caught in its own
  try/except, logs a warning, and leaves `duration_ms=None` — it must never raise out of
  `tts_node`, matching the node's existing "never hard-fails" contract for every other failure
  mode in the same loop.
- [ ] **AC 4.** Every per-segment `audio_assets` wrapper dict gains a `"duration_ms"` key
  **sibling to** `"data"` (never inside it) — `None` on the browser-fallback path
  (`audio_bytes is None`) and on the whole-segment exception/degrade path, a real measured
  value on success.
- [ ] **AC 5.** `Narration`/`packages/shared/lesson_package.schema.json`/
  `packages/shared/types/lesson.ts` are byte-for-byte unchanged — verified by diff. No new field
  on any of the four frozen contracts.
- [ ] **AC 6.** `_estimate_slide_timestamps` gains an optional `known_duration_ms: float | None
  = None` keyword. When provided (not `None`), it is used directly as the segment's total
  duration instead of the word-count computation. When omitted/`None`, the function's existing
  word-count-estimate branch runs completely unchanged (verified: every existing
  `test_estimate_slide_timestamps`-style test in `test_package_builder_node.py`, which calls
  the estimate path implicitly via `package_builder_node`, still passes with zero edits).
- [ ] **AC 7.** `package_builder_node` builds a `duration_ms_by_id` dict comprehension reading
  the sibling `"duration_ms"` key out of `state["audio_assets"]` (mirroring the existing
  `audio_by_id` lookup's shape, no new helper function) and passes
  `known_duration_ms=duration_ms_by_id.get(segment_id)` into its `_estimate_slide_timestamps`
  call site.
- [ ] **AC 8.** The final `LessonPackage`'s `segments[i].narration.timestamps` for a segment
  whose audio was really synthesized reflect the REAL measured duration (verified against a
  genuine, mutagen-parseable MP3 fixture — not a fake byte string), not the word-count formula's
  output for the same script/slide count.

### Non-functional / regression-guard

- [ ] **AC 9.** A RED test proves the pre-fix defect directly: with a real MP3 fixture, either
  (a) `duration_ms` is entirely absent from the pre-fix `audio_assets` wrapper dict, or (b) the
  pre-fix final package's `timestamps` match the word-count estimate rather than a
  duration-based calculation — confirmed by actually running the test against the unmodified
  code and observing the failure, not asserted from reading the diff.
- [ ] **AC 10.** The browser-fallback / unknown-duration path (`mutagen` parse failure, or no
  server audio at all) is tested and produces `timestamps` **identical** to the pre-existing
  word-count-estimate output — i.e. zero behavior change for every lesson that still hits the
  fallback chain's last resort.
- [ ] **AC 11.** `apps/api/tests/unit/test_tts_node.py` re-run in full, unmodified, all
  pre-existing tests still pass — none of them assert `duration_ms` is absent, so adding it as a
  new sibling key must not break any existing assertion (they only ever assert on
  `assets[i]["data"][...]` and `assets[i]["segment_id"]`, confirmed by reading the file first).
- [ ] **AC 12.** `apps/api/tests/unit/test_package_builder_node.py` re-run in full, unmodified,
  all pre-existing tests still pass — none of them pin an exact word-count-estimate
  `timestamps` value for a segment that would now also carry a `duration_ms` (confirmed by
  reading the file first: existing timestamp-shape assertions check contiguity/ordering
  invariants, not exact numeric values, so a same-shaped-but-differently-sourced total duration
  does not break them).
- [ ] **AC 13.** `ruff check`, `ruff format --check`, and `mypy --ignore-missing-imports` all
  clean on both modified files (`graph.py`, `pyproject.toml` has no lint surface).

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one segment's synthesized audio buffer, measured
   once per segment per `tts_node` run. Range: 4–12 segments per lesson (per
   `docs/handoffs/lesson-delivery-dev1.md`), each buffer typically a few seconds to ~2 minutes of
   narration audio (a few KB to low hundreds of KB of MP3). `mutagen.mp3.MP3(...)` parses the MP3
   header/frame table in memory — it does not decode audio samples, so cost does not scale with
   duration, only with doing it once per segment (same order as the existing per-segment Storage
   upload it sits next to).
2. **Fixed budget vs. variable input.** N/A with reason: this story introduces no new fixed
   budget/cap. It replaces one *already-existing*, always-approximate value
   (`_estimate_slide_timestamps`'s word-count guess) with a measured one when available, and
   preserves the exact prior fallback behavior otherwise — there is no new place a variable input
   can exceed a fixed budget. The `mutagen` parse itself has no size ceiling risked: `audio_bytes`
   already passed through the existing `check_ceiling`/provider-call path before reaching this
   step, so it is not attacker-controlled or unbounded-by-construction here.
3. **Scope of every limit.** N/A — no limit introduced.
4. **Unbounded reads/writes.** None introduced. `duration_ms_by_id` in `package_builder_node` is
   a dict comprehension over `state["audio_assets"]`, a list already fully materialized in memory
   by the time `package_builder_node` runs (same list `audio_by_id`'s existing
   `_index_by_segment_id` call already iterates, one line above) — no new Supabase read, no new
   iteration source. Per CLAUDE.md's own framing for pipeline-internal work: this is in-memory,
   not request-path, so `tests/unit/test_unbounded_queries.py`'s `.limit()`/`.range()` requirement
   does not apply — stated explicitly per this task's instructions, not skipped silently.
5. **Inherited caps re-derived?** N/A — no caps involved; this is a data-source substitution
   inside an existing per-segment loop, not a new limit.
6. **Check-then-act under concurrency.** N/A — `tts_node` and `package_builder_node` each run
   once per lesson-generation job (one ARQ job = one lesson), and this change touches no
   shared/cross-job state — `duration_ms` lives entirely inside that job's own
   `lesson_jobs.node_outputs` checkpoint and in-memory `PipelineState`, never a table another
   job's concurrent run could race against.

**Why five of six are N/A, stated plainly:** this is a pure in-memory measurement + data-source
substitution inside two existing pipeline nodes' per-segment loops. It has no new request-path
budget, scope, or concurrency dimension. The one place the Scale Contract's spirit genuinely
matters is Q1/Q2's underlying question restated as this story's own one-line test: **"what
input makes this silently wrong rather than loudly broken?"** — answer: a `mutagen`-unparseable
buffer, and this story's AC 3 explicitly converts that into a **surfaced, explicit degradation**
(`duration_ms=None`, logged, and package_builder falls back to the pre-existing estimate) rather
than a silent wrong duration or a crash. That is the actual scale-contract-shaped risk in this
diff, and it is answered by AC 3 + AC 10's test, not left as prose.

## Tasks

### Task 1 — dependency
- [ ] 1.1 Add `mutagen>=1.47.0` to `apps/api/pyproject.toml` (AC 1)

### Task 2 — `tts_node`: measure real duration
- [ ] 2.1 Import `io` + `mutagen.mp3.MP3` inside `tts_node` (local import, matching this
  function's existing style)
- [ ] 2.2 On the `audio_bytes is not None` success branch, measure `duration_ms` in its own
  try/except (AC 2, AC 3)
- [ ] 2.3 Add `"duration_ms"` as a sibling key on the per-segment wrapper dict, on every path
  (success / browser-fallback / whole-segment-exception) (AC 4)

### Task 3 — `_estimate_slide_timestamps`: accept a real duration
- [ ] 3.1 Add optional `known_duration_ms: float | None = None` keyword (AC 6)
- [ ] 3.2 When provided, use it directly as `total_ms`; unchanged word-count branch otherwise
  (AC 6)
- [ ] 3.3 Update docstring — no longer ALWAYS an estimate (AC 6)

### Task 4 — `package_builder_node`: wire the real value through
- [ ] 4.1 Build `duration_ms_by_id` dict comprehension next to `audio_by_id` (AC 7)
- [ ] 4.2 Pass `known_duration_ms=duration_ms_by_id.get(segment_id)` into the existing
  `_estimate_slide_timestamps` call site (AC 7, AC 8)

### Task 5 — tests
- [ ] 5.1 Build a genuine, mutagen-parseable minimal MP3 fixture (hand-built valid MPEG-1
  Layer III frame(s) — documented inline exactly how, no fake byte string) (AC 8, AC 9)
- [ ] 5.2 RED: prove the pre-fix defect against the real fixture, run and paste the actual
  failure (AC 9)
- [ ] 5.3 GREEN: implement Tasks 1–4, confirm the new test(s) pass (AC 2, AC 4, AC 8)
- [ ] 5.4 Test the fallback/unknown-duration path is pixel-for-pixel unchanged (AC 10)
- [ ] 5.5 Re-run `test_tts_node.py` and `test_package_builder_node.py` in full, unmodified,
  confirm zero regressions (AC 11, AC 12)
- [ ] 5.6 `ruff check` / `ruff format --check` / `mypy --ignore-missing-imports` on both
  modified `.py` files (AC 13)

### Task 6 — Review
- [ ] 6.1 6-layer adversarial review (Round 1, inline self-review)

### Task 7 — Commit
- [ ] 7.1 Story-first commit (this file, alone)
- [ ] 7.2 Implementation commit (code + tests + updated story file)

## Dev Agent Record

### Implementation Plan

1. Read `tts_node`, `_estimate_slide_timestamps`, `_fallback_narration`, and
   `package_builder_node`'s existing `audio_by_id`/`_index_by_segment_id`/call-site code in
   full before writing anything, per this task's own instruction and this project's
   "declaring completion is not verification" culture.
2. Read `test_tts_node.py` and confirm the `b"AUDIO_BYTES"`/`b"AZURE_AUDIO"` fixtures used
   throughout are not real audio — mutagen will fail to parse them, which is fine for those
   pre-existing tests (they don't test duration) but means a NEW real MP3 fixture is required
   for this story's own duration-measurement tests.
3. Hand-build a minimal valid MPEG-1 Layer III frame (sync word `0xFFFB`, MPEG-1/Layer
   III/no-CRC, 128kbps/44100Hz/stereo header bytes, silent zero-byte payload sized to the
   layer-3 frame-length formula `144 * bitrate / samplerate`), repeated N times, and confirm via
   a scratch script that `mutagen.mp3.MP3` reports a real, non-zero, `duration_ms > 0` before
   writing any test assertion against it.
4. RED: write the failing test(s) against the pre-fix code, run, paste the real failure.
5. GREEN: implement `tts_node` measurement, sibling `duration_ms` key,
   `_estimate_slide_timestamps`'s new keyword, and `package_builder_node`'s lookup +
   call-site wiring. Re-run new tests green.
6. Re-run `test_tts_node.py` and `test_package_builder_node.py` in full, unmodified; ruff/
   ruff format/mypy on both changed `.py` files.
7. Update this story file's ACs/tasks to `[x]` with verification notes; fill in Debug
   Log/Completion Notes/File List/Change Log with what actually happened; add the Round-1
   self-review section.

### Debug Log

*(filled in during GREEN phase with actual commands/output)*

### Completion Notes

*(filled in after GREEN phase)*

### File List

*(filled in after GREEN phase)*

### Change Log

*(filled in after GREEN phase)*
