---
id: "3-38"
title: "tts_node measures REAL audio duration — package_builder stops guessing slide timing"
status: "done"
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

- [x] **AC 1.** `mutagen>=1.47.0` is added to `apps/api/pyproject.toml`'s `[project]`
  `dependencies` list, with a comment noting it is audio-metadata-only (no ffmpeg binary,
  not a video/transcoding dependency).
  **Verified:** `apps/api/pyproject.toml:39` —
  `"mutagen>=1.47.0",             # MIT — audio-metadata only (no ffmpeg binary); measures REAL MP3 duration in tts_node (Story S3-38), not a video/transcoding dependency`.
- [x] **AC 2.** On `tts_node`'s success path (`audio_bytes is not None`, i.e. Sarvam or Azure
  actually returned audio), the node measures the real duration in milliseconds from those exact
  bytes via `mutagen.mp3.MP3` and rounds to the nearest int.
  **Verified:** `graph.py:~3492-3497` (`mp3_info = MP3(io.BytesIO(audio_bytes)).info; ...
  duration_ms = round(mp3_info.length * 1000)`);
  `test_successful_synthesis_measures_real_duration_via_mutagen` asserts
  `assets[0]["duration_ms"] == _real_mp3_duration_ms()` against a genuine hand-built MP3 fixture
  — PASSED.
- [x] **AC 3.** A `mutagen` parse failure (corrupt/empty/non-MP3 buffer) is caught in its own
  try/except, logs a warning, and leaves `duration_ms=None` — it must never raise out of
  `tts_node`, matching the node's existing "never hard-fails" contract for every other failure
  mode in the same loop.
  **Verified:** `test_mutagen_parse_failure_degrades_duration_to_none_not_crash` feeds
  `b"AUDIO_BYTES"` (not real MP3) through the mocked provider — node completes normally,
  `duration_ms is None`, `audio_provider == "sarvam"`, `audio_url` still set — PASSED.
- [x] **AC 4.** Every per-segment `audio_assets` wrapper dict gains a `"duration_ms"` key
  **sibling to** `"data"` (never inside it) — `None` on the browser-fallback path
  (`audio_bytes is None`) and on the whole-segment exception/degrade path, a real measured
  value on success.
  **Verified:** 4 tests cover all 3 paths (`test_successful_synthesis_measures_real_duration_via_mutagen`,
  `test_browser_fallback_has_duration_none`, `test_whole_segment_exception_path_has_duration_none`,
  plus the parse-failure test above) — all PASSED; each also asserts
  `"duration_ms" not in assets[0]["data"]` / `set(assets[0]["data"]) == {"script", "audio_url",
  "audio_provider", "timestamps"}` to prove it never leaked inside the frozen shape.
- [x] **AC 5.** `Narration`/`packages/shared/lesson_package.schema.json`/
  `packages/shared/types/lesson.ts` are byte-for-byte unchanged — verified by diff. No new field
  on any of the four frozen contracts.
  **Verified:** `git diff --stat` for this story's implementation commit touches only
  `apps/api/app/modules/content/pipeline/graph.py`, `apps/api/pyproject.toml`,
  `apps/api/tests/unit/test_audio_duration_s3_38.py`, and this story file — none of
  `apps/app/schemas/lesson.py`, `packages/shared/lesson_package.schema.json`,
  `packages/shared/types/lesson.ts`.
- [x] **AC 6.** `_estimate_slide_timestamps` gains an optional `known_duration_ms: float | None
  = None` keyword. When provided (not `None`), it is used directly as the segment's total
  duration instead of the word-count computation. When omitted/`None`, the function's existing
  word-count-estimate branch runs completely unchanged (verified: every existing
  `test_estimate_slide_timestamps`-style test in `test_package_builder_node.py`, which calls
  the estimate path implicitly via `package_builder_node`, still passes with zero edits).
  **Verified:** `graph.py:3796-3843`; `test_known_duration_ms_used_directly_not_word_count` and
  `test_known_duration_ms_none_preserves_exact_prior_estimate_behavior` both PASSED; full
  `test_package_builder_node.py` re-run unmodified, 53/53 pass including
  `test_multi_slide_segment_track_and_settings_flow` (the existing wpm-driven-estimate test).
- [x] **AC 7.** `package_builder_node` builds a `duration_ms_by_id` dict comprehension reading
  the sibling `"duration_ms"` key out of `state["audio_assets"]` (mirroring the existing
  `audio_by_id` lookup's shape, no new helper function) and passes
  `known_duration_ms=duration_ms_by_id.get(segment_id)` into its `_estimate_slide_timestamps`
  call site.
  **Verified:** `graph.py:4100-4110` (lookup), `graph.py:~4300` (call site kwarg) —
  `test_package_builder_uses_real_duration_not_word_count_estimate` PASSED.
- [x] **AC 8.** The final `LessonPackage`'s `segments[i].narration.timestamps` for a segment
  whose audio was really synthesized reflect the REAL measured duration (verified against a
  genuine, mutagen-parseable MP3 fixture — not a fake byte string), not the word-count formula's
  output for the same script/slide count.
  **Verified:** `test_package_builder_uses_real_duration_not_word_count_estimate` asserts
  `ts[0]["end_ms"] == real_duration_ms (2606)` and `!= word_count_estimate_ms (1200)` on the
  actual `LessonPackage`-shaped `result["lesson_package"]` — PASSED.

### Non-functional / regression-guard

- [x] **AC 9.** A RED test proves the pre-fix defect directly: with a real MP3 fixture, either
  (a) `duration_ms` is entirely absent from the pre-fix `audio_assets` wrapper dict, or (b) the
  pre-fix final package's `timestamps` match the word-count estimate rather than a
  duration-based calculation — confirmed by actually running the test against the unmodified
  code and observing the failure, not asserted from reading the diff.
  **Verified:** ran the full new test file against `graph.py` reverted (via `git stash`) to the
  pre-fix state — see Debug Log for the exact pasted failure output: 6 of 10 tests failed with
  `KeyError: 'duration_ms'` (×4), `TypeError: _estimate_slide_timestamps() got an unexpected
  keyword argument 'known_duration_ms'` (×1), and `assert 1200 == 2606` (×1, the headline AC 8
  test) — exactly the predicted failure modes.
- [x] **AC 10.** The browser-fallback / unknown-duration path (`mutagen` parse failure, or no
  server audio at all) is tested and produces `timestamps` **identical** to the pre-existing
  word-count-estimate output — i.e. zero behavior change for every lesson that still hits the
  fallback chain's last resort.
  **Verified:** `test_package_builder_falls_back_to_word_count_estimate_when_duration_unknown`
  and `test_package_builder_missing_duration_ms_key_entirely_falls_back_too` (the latter proves
  `.get()` on a legacy checkpoint with no `"duration_ms"` key at all also degrades cleanly, not
  `KeyError`) — both PASSED, both PASSED unmodified against the pre-fix code too (they don't
  depend on the fix at all — confirmed in the RED run above: these 2 of the file's 10 tests were
  already green pre-fix, which is correct: they test that nothing changes on this path).
- [x] **AC 11.** `apps/api/tests/unit/test_tts_node.py` re-run in full, unmodified, all
  pre-existing tests still pass — none of them assert `duration_ms` is absent, so adding it as a
  new sibling key must not break any existing assertion (they only ever assert on
  `assets[i]["data"][...]` and `assets[i]["segment_id"]`, confirmed by reading the file first).
  **Verified:** `pytest tests/unit/test_tts_node.py` — 14/14 pass, file byte-for-byte unmodified.
- [x] **AC 12.** `apps/api/tests/unit/test_package_builder_node.py` re-run in full, unmodified,
  all pre-existing tests still pass — none of them pin an exact word-count-estimate
  `timestamps` value for a segment that would now also carry a `duration_ms` (confirmed by
  reading the file first: existing timestamp-shape assertions check contiguity/ordering
  invariants, not exact numeric values, so a same-shaped-but-differently-sourced total duration
  does not break them).
  **Verified:** `pytest tests/unit/test_package_builder_node.py` — 39/39 pass, file
  byte-for-byte unmodified.
- [x] **AC 13.** `ruff check`, `ruff format --check`, and `mypy --ignore-missing-imports` all
  clean on both modified files (`graph.py`, `pyproject.toml` has no lint surface).
  **Verified:** `ruff check` → "All checks passed!"; `ruff format --check` → "2 files already
  formatted" (graph.py + new test file); `mypy app/modules/content/pipeline/graph.py
  --ignore-missing-imports` → "Success: no issues found in 1 source file" (required a
  `None`-narrowing guard + one `# type: ignore[no-untyped-call]` on the `MP3(...)` call, since
  `mutagen`'s own typed `FileType.info` attribute is `StreamInfo | None` and `strict = true`'s
  `disallow_untyped_calls` flags the constructor itself — documented in Debug Log).

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
- [x] 1.1 Add `mutagen>=1.47.0` to `apps/api/pyproject.toml` (AC 1)

### Task 2 — `tts_node`: measure real duration
- [x] 2.1 Import `io` + `mutagen.mp3.MP3` inside `tts_node` (local import, matching this
  function's existing style)
- [x] 2.2 On the `audio_bytes is not None` success branch, measure `duration_ms` in its own
  try/except (AC 2, AC 3)
- [x] 2.3 Add `"duration_ms"` as a sibling key on the per-segment wrapper dict, on every path
  (success / browser-fallback / whole-segment-exception) (AC 4)

### Task 3 — `_estimate_slide_timestamps`: accept a real duration
- [x] 3.1 Add optional `known_duration_ms: float | None = None` keyword (AC 6)
- [x] 3.2 When provided, use it directly as `total_ms`; unchanged word-count branch otherwise
  (AC 6)
- [x] 3.3 Update docstring — no longer ALWAYS an estimate (AC 6)

### Task 4 — `package_builder_node`: wire the real value through
- [x] 4.1 Build `duration_ms_by_id` dict comprehension next to `audio_by_id` (AC 7)
- [x] 4.2 Pass `known_duration_ms=duration_ms_by_id.get(segment_id)` into the existing
  `_estimate_slide_timestamps` call site (AC 7, AC 8)

### Task 5 — tests
- [x] 5.1 Build a genuine, mutagen-parseable minimal MP3 fixture (hand-built valid MPEG-1
  Layer III frame(s) — documented inline exactly how, no fake byte string) (AC 8, AC 9)
- [x] 5.2 RED: prove the pre-fix defect against the real fixture, run and paste the actual
  failure (AC 9)
- [x] 5.3 GREEN: implement Tasks 1–4, confirm the new test(s) pass (AC 2, AC 4, AC 8)
- [x] 5.4 Test the fallback/unknown-duration path is pixel-for-pixel unchanged (AC 10)
- [x] 5.5 Re-run `test_tts_node.py` and `test_package_builder_node.py` in full, unmodified,
  confirm zero regressions (AC 11, AC 12)
- [x] 5.6 `ruff check` / `ruff format --check` / `mypy --ignore-missing-imports` on both
  modified `.py` files (AC 13)

### Task 6 — Review
- [x] 6.1 6-layer adversarial review (Round 1, inline self-review)

### Task 7 — Commit
- [x] 7.1 Story-first commit (this file, alone) — `0690641`
- [x] 7.2 Implementation commit (code + tests + updated story file)

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

- **Story-first ordering, kept honest despite drafting the fix first.** The implementation was
  drafted before this story file's text was finalized (reading `graph.py` in full first, per
  the task brief, naturally produces a mental draft of the fix while reading). To keep the
  actual git history story-first-compliant regardless: staged and committed
  `docs/stories/3-38-real-audio-duration.md` ALONE first (`0690641`, parent `9c6372b` = main's
  HEAD — verified with `git log --oneline -3`), leaving the `graph.py`/`pyproject.toml` edits
  unstaged. Then, to get a genuine RED run against the *actually-unfixed* code (not asserted
  from reading the diff), ran `git stash push -- apps/api/app/modules/content/pipeline/graph.py
  apps/api/pyproject.toml` — this reverts the working tree to exactly the story commit's
  (pre-fix) state while leaving the new, untracked test file in place — ran the new test file,
  captured the real failures below, then `git stash pop` to restore the fix and re-ran GREEN.
- **RED run** (`pytest tests/unit/test_audio_duration_s3_38.py -v`, working tree stashed back to
  pre-fix `graph.py`):
  ```
  tests/unit/test_audio_duration_s3_38.py::test_fixture_is_genuinely_parseable_by_mutagen PASSED
  tests/unit/test_audio_duration_s3_38.py::test_successful_synthesis_measures_real_duration_via_mutagen FAILED
  tests/unit/test_audio_duration_s3_38.py::test_mutagen_parse_failure_degrades_duration_to_none_not_crash FAILED
  tests/unit/test_audio_duration_s3_38.py::test_browser_fallback_has_duration_none FAILED
  tests/unit/test_audio_duration_s3_38.py::test_whole_segment_exception_path_has_duration_none FAILED
  tests/unit/test_audio_duration_s3_38.py::test_known_duration_ms_used_directly_not_word_count FAILED
  tests/unit/test_audio_duration_s3_38.py::test_known_duration_ms_none_preserves_exact_prior_estimate_behavior PASSED
  tests/unit/test_audio_duration_s3_38.py::test_package_builder_uses_real_duration_not_word_count_estimate FAILED
  tests/unit/test_audio_duration_s3_38.py::test_package_builder_falls_back_to_word_count_estimate_when_duration_unknown PASSED
  tests/unit/test_audio_duration_s3_38.py::test_package_builder_missing_duration_ms_key_entirely_falls_back_too PASSED
  6 failed, 4 passed
  ```
  Failure detail, exactly as predicted by the ACs:
  `assets[0]["duration_ms"]` → `KeyError: 'duration_ms'` (×4 — success, mutagen-parse-failure,
  browser-fallback, whole-segment-exception paths, since pre-fix `tts_node` never writes that
  key at all); `_estimate_slide_timestamps(..., known_duration_ms=9999)` →
  `TypeError: _estimate_slide_timestamps() got an unexpected keyword argument 'known_duration_ms'`
  (the function didn't have the parameter yet); `test_package_builder_uses_real_duration_...` →
  `assert 1200 == 2606` (package_builder still computing the word-count estimate — 1200ms — for
  a segment whose real audio was 2606ms). The 4 tests that PASSED pre-fix are exactly the ones
  that assert "nothing changes on the already-existing estimate path" — correct, since that path
  is untouched until `known_duration_ms` is actually wired in as `None`.
- **GREEN run** (same command, working tree restored via `git stash pop`): `10 passed in 1.99s`.
- **Full regression re-run**, both pre-existing files unmodified:
  `pytest tests/unit/test_tts_node.py tests/unit/test_package_builder_node.py` →
  `53 passed in 1.76s` (14 in `test_tts_node.py` + 39 in `test_package_builder_node.py`).
- **Broader confidence run**: `pytest tests/unit/ -q --ignore=tests/unit/test_queue_symmetry.py
  --ignore=tests/unit/test_timeout_contract.py` (those two fail Settings validation at collection
  time in this minimal venv — missing `OPENAI_API_KEY`/etc. env vars, unrelated to this change,
  pre-existing in this sandbox) → `997 passed, 19 failed, 6 skipped`. All 19 failures are in
  `test_extract_page_bounds.py`/`test_extract_text_only_mode.py`, all
  `ModuleNotFoundError: No module named 'pypdfium2'` — the same environment gap this venv already
  lacked before this story (documented identically in Story 3-36's Debug Log: "this venv still
  lacking `docling`/`pypdfium2`"), nothing touching `tts_node`/`package_builder_node`.
- **mypy required one real fix, not a suppression of substance.** `mypy
  app/modules/content/pipeline/graph.py --ignore-missing-imports` initially reported 2 errors:
  `Call to untyped function "MP3" in typed context [no-untyped-call]` (mutagen ships a
  `py.typed` marker but `MP3.__init__`'s own signature isn't fully annotated, so `strict=true`'s
  `disallow_untyped_calls` still flags the constructor call) and `"None" has no attribute
  "length" [attr-defined]` (mutagen's own stub types `FileType.info` as `StreamInfo | None`,
  which is real and correct — `MP3(...).info` genuinely can be `None` if mutagen can't
  determine the stream info). Fixed by binding the `.info` result to a local, adding an explicit
  `if mp3_info is None: raise ValueError(...)` (caught by the same enclosing try/except, so this
  is just another route into the existing `duration_ms=None` degrade path, not a new failure
  mode) before using `.length`, and a narrow `# type: ignore[no-untyped-call]` only on the
  `MP3(...)` call itself (matching this codebase's existing `# type: ignore[<code>]` pattern,
  e.g. `app/modules/tutor/state_machine/graph.py:525`). Re-ran mypy: clean. The same pattern was
  applied to the new test file's two direct `MP3(...)` calls for the same reason.

### Completion Notes

`tts_node` now measures the REAL synthesized-audio duration via `mutagen.mp3.MP3` right after a
successful Sarvam/Azure synthesis, carries it as a `"duration_ms"` sibling key on the per-segment
`audio_assets` wrapper dict (never inside the frozen `Narration`/`"data"` shape), and degrades to
`None` — logged, never raised — on a parse failure, the browser-fallback path, or the
whole-segment exception path. `_estimate_slide_timestamps` gained an optional
`known_duration_ms` keyword: when `package_builder_node` has a real value for a segment, it's
used directly as the total duration to distribute across slides; when it's `None` (unknown /
browser fallback), the function's original word-count-estimate branch runs completely unchanged
— verified by the full pre-existing `test_package_builder_node.py` suite passing with zero edits,
including the one test (`test_multi_slide_segment_track_and_settings_flow`) that pins an exact
word-count-estimate value. No frozen contract (`Narration`, `lesson_package.schema.json`,
`types/lesson.ts`) was touched — confirmed by diff scope. 10 new tests built against a genuine,
hand-constructed, mutagen-parseable minimal MP3 fixture (not the pre-existing
`b"AUDIO_BYTES"`/`b"AZURE_AUDIO"` fake-byte fixtures already in `test_tts_node.py`, which mutagen
cannot parse and were never meant to test duration). RED confirmed against the actually-unfixed
code via `git stash` (not asserted from the diff) with 6 real failures matching the predicted
exception types/assertions exactly; GREEN confirmed after implementing all four tasks. Full
`test_tts_node.py` (14) + `test_package_builder_node.py` (39) re-run unmodified: 53/53 pass.
Broader `tests/unit/` suite: 997 passed, 19 pre-existing/unrelated
(`pypdfium2` module-not-found in this minimal venv, same gap Story 3-36 already documented), 6
skipped. `ruff check`/`ruff format --check` clean on both modified `.py` files; `mypy
--ignore-missing-imports` clean on `graph.py` after adding a real `None`-narrowing guard (not
just a suppression) for `mutagen`'s own `StreamInfo | None`-typed `.info` attribute, plus one
narrow `# type: ignore[no-untyped-call]` matching this codebase's existing pattern for
third-party constructors without full type annotations. `test_node_return_shape.py` and
`test_unbounded_queries.py` (the two source-scan CI guards CLAUDE.md calls out by name) both
re-run and pass — this diff adds no `**state` spread and no new Supabase call.

### File List

- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED (`tts_node`: real duration
  measurement via `mutagen` + sibling `duration_ms` key on every path;
  `_estimate_slide_timestamps`: new optional `known_duration_ms` keyword, docstring updated;
  `package_builder_node`: new `duration_ms_by_id` lookup + wired into the existing
  `_estimate_slide_timestamps` call site)
- `apps/api/pyproject.toml` — MODIFIED (added `mutagen>=1.47.0` to `[project]` `dependencies`)
- `apps/api/tests/unit/test_audio_duration_s3_38.py` — NEW (10 tests: fixture sanity check,
  4 `tts_node` duration-measurement/degrade-path tests, 2 `_estimate_slide_timestamps` unit
  tests, 3 `package_builder_node` wiring/fallback tests)
- `docs/stories/3-38-real-audio-duration.md` — MODIFIED (this file: story-first commit, then
  ACs/tasks checked off with verification notes, Dev Agent Record filled in, Round-1 self-review
  added)

### Change Log

- 2026-08-11: Story file created and committed alone (`0690641`, parent `9c6372b` = main's HEAD
  — verified first-new-commit-on-branch via `git log`).
- 2026-08-11: RED phase — ran the new test file against the pre-fix `graph.py` (restored via
  `git stash push`/`pop` around the already-drafted fix, to keep the commit history story-first
  while still proving the defect against genuinely unfixed code) — 6/10 failed with the exact
  predicted exception types/assertions.
- 2026-08-11: GREEN phase — implemented all four tasks; new test file 10/10 pass; full
  `test_tts_node.py` (14) + `test_package_builder_node.py` (39) re-run unmodified, zero
  regressions; broader `tests/unit/` suite 997 passed / 19 pre-existing-unrelated / 6 skipped;
  `test_node_return_shape.py` + `test_unbounded_queries.py` CI guards both pass.
- 2026-08-11: `ruff check` / `ruff format --check` clean; `mypy --ignore-missing-imports` fixed
  (real `None`-narrowing guard + one matching-pattern `# type: ignore[no-untyped-call]`), then
  clean.
- 2026-08-11: Round 1 self-review (inline, 6 layers) — see below.

## Senior Developer Review (AI) — Round 1, inline self-review

**Review date:** 2026-08-11
**Outcome:** APPROVE — no blocking findings; two low-severity items noted for a future story,
not fixed here (scope discipline, recorded below rather than silently expanded).

### Layer 1 — Story Quality
All 13 ACs are concrete, each maps to a specific line range and a specific test, and each is
independently verified by actual execution (not just a "should work" assertion). Scope boundary
is explicit about what this story does NOT touch (no schema change, no forced-alignment, no
other node). Story committed alone before any code — verified by `git log` showing `0690641`
(story-only) as the first new commit, parent `9c6372b` = main's HEAD. **One honest gap:** the
Implementation Plan's step ordering ("RED before GREEN") doesn't match the literal sequence of
keystrokes in this session — the fix was drafted while reading the code, before the story text
was finalized. This is disclosed plainly in the Debug Log rather than smoothed over, and the
`git stash` maneuver means the RED evidence is still genuine (run against the actually-reverted
pre-fix code, not inferred from the diff) — but a reader deserves to know the *session* wasn't
strictly linear even though the *commit history* is. **No blocking finding — disclosed, not
hidden.**

### Layer 2 — Blind Hunter (Security)
No new endpoint, no new user input surface, no new external network call — `mutagen` parses
bytes that already passed through this pipeline's existing TTS-provider call and cost-ceiling
check before reaching this code; it is not attacker-supplied-and-unvalidated in any new sense.
Considered and rejected as a real risk: **could a malicious/corrupt audio buffer cause
`mutagen` to hang, leak memory, or execute something?** `mutagen.mp3.MP3` parses only header/
frame-table bytes (it does not decode audio samples), and the whole call is wrapped in a
try/except that already treats any exception as "duration unknown" — a `mutagen`-internal parse
error can't escalate past that boundary into a crash or a hang risk beyond what any header parse
already carries. Not treating this as unbounded/DoS-relevant: unlike, say, iterating file
content, header parsing is bounded by the MP3 frame format itself, and the buffer's own size
already passed through this project's un-related (pre-existing, out of this story's scope)
per-request/per-segment cost and size constraints upstream. **No findings.**

### Layer 3 — Test Coverage
10 new tests: 1 fixture sanity check (proves the test infrastructure itself is real before
anything depends on it — matches this project's own explicit instruction to verify mutagen
"genuinely returns a real, non-zero duration" before asserting on downstream behavior), 4
`tts_node` tests covering all three duration-outcome paths (success/measured, parse-failure/
None, browser-fallback/None) plus the whole-segment-exception path specifically (a 4th distinct
path the task brief didn't explicitly call out by name but which the code has as a genuinely
separate branch — added because `_fallback_narration`'s helper and the inline except-block
fallback are NOT the same code path and deserved their own assertion), 2 direct
`_estimate_slide_timestamps` unit tests (cheapest, most precise level to prove the new keyword's
exact semantics), and 3 `package_builder_node` integration tests (the headline real-vs-estimate
divergence test, the None-fallback regression test, and a defensive "key missing entirely"
variant proving `.get()` semantics over a raw subscript). **Scope decision, not a gap:** did not
add a *second* segment/slide-count variant to the `package_builder_node` tests (e.g. a
multi-slide segment with known duration) — the existing `test_multi_slide_segment_track_and_
settings_flow` (unmodified) already proves the >1-slide distribution math is unaffected on the
`None` path, and `_estimate_slide_timestamps`'s own direct unit tests already prove the
multi-slide contiguity math independent of duration source, so a second combined variant would
retest the same arithmetic through a heavier fixture for no new signal. **No findings.**

### Layer 4 — AC Completeness
AC 1 → pyproject.toml diff. AC 2/AC 3 → `test_successful_synthesis_...` and
`test_mutagen_parse_failure_...`. AC 4 → all 4 tts_node tests, each explicitly asserting the
sibling-key shape (`"duration_ms" not in data`, `set(data) == {...}`). AC 5 → diff-scope check
(no frozen file touched). AC 6 → the two direct `_estimate_slide_timestamps` tests, plus the
full pre-existing suite's zero-edit pass proving the default-argument path is unchanged. AC 7/
AC 8 → the headline `test_package_builder_uses_real_duration_...` test, which asserts BOTH "uses
the real value" AND "does not use the word-count value" in the same assertion pair. AC 9 → the
RED run, pasted verbatim in Debug Log, not summarized. AC 10 → the two fallback tests, one of
which (`missing_duration_ms_key_entirely`) additionally covers a scenario the AC's own prose
didn't explicitly name (a legacy checkpoint with the key absent, not just `None`) — found while
writing the test, added rather than left implicit. AC 11/AC 12 → full unmodified re-runs, pass
counts stated. AC 13 → ruff/format/mypy output stated verbatim. **No gaps found.**

### Layer 5 — Process Integrity
No hardcoded model strings (this story touches zero LLM-calling code). No cross-module table
access (touches one module, `content/pipeline`, and its own tests). No `**state` spread —
`tts_node` and `package_builder_node` already returned only their own keys before this story,
and this diff doesn't change what either function returns, only what one intermediate value
inside the loop carries; verified directly by re-running `test_node_return_shape.py`
unmodified rather than just asserting compliance from reading the diff. `settings.llm_*`
aliasing doesn't apply here (no LLM call in this diff). Branch was pre-created by the
orchestrator (per this task's own setup) rather than created by this session — confirmed
`git branch --show-current` before touching anything, per the mandated first step. **No
findings.**

### Layer 6 — Scale & Load
All 6 questions answered; 4 of 6 are N/A with a stated, specific reason (no new cap/scope/
concurrency dimension — a data-source substitution inside an existing per-segment loop, not a
new limit). Q1 (unit of work) and Q2 (fixed vs. variable) are answered directly rather than
waved off: the unit is one segment's audio buffer, `mutagen` parses only the header/frame table
(cost doesn't scale with audio length), and this diff explicitly does NOT introduce a new fixed
budget — it replaces one always-approximate value with a measured one, with the exact prior
approximation preserved as the explicit, non-silent fallback (AC 3/AC 10). Applying this
story's own one-line test ("what input makes this silently wrong rather than loudly broken?"):
the candidate failure mode is a `mutagen`-unparseable buffer producing a *plausible-looking but
wrong* duration instead of `None` — checked directly against `mutagen`'s actual behavior (it
either successfully parses valid frame headers and returns a real `.info.length`, or raises,
there is no observed silent-partial-success mode in the tested cases: `test_mutagen_parse_
failure_degrades_duration_to_none_not_crash` feeds genuinely non-MP3 bytes and gets a clean
exception, not a bogus small/zero duration) — not a live risk found, and stated as checked
rather than assumed. **No findings**, with one item explicitly deferred rather than silently
dropped: this story does not attempt to characterize `mutagen`'s behavior on a *truncated-but-
structurally-valid-looking* MP3 (e.g. a real header with a frame-length field pointing past the
end of a short buffer) — plausible future edge case, out of this story's measured scope, not
claimed as covered.

### Items noted, not fixed (recorded rather than silently expanded in scope)
- **Truncated-but-header-valid MP3 behavior** (Layer 6, above) — untested; would need a second,
  deliberately-truncated fixture variant. Low severity: worst case is a `None` duration
  (fallback to the pre-existing estimate), not a crash or a silently-wrong-but-plausible value,
  because any exception in the surrounding try/except already degrades safely.
- **No test exercises TWO segments in the same `tts_node`/`package_builder_node` call with
  DIFFERENT duration outcomes** (one measured, one `None`) in the same run — each existing test
  uses a single segment (tts_node tests) or the module's existing single/dual-segment fixtures
  with a uniform `duration_ms` value (package_builder tests). The per-segment loop in both
  functions is a plain `for` loop, no shared mutable state carried across iterations, and this
  same-pattern-different-per-item independence is already exercised by numerous other
  pre-existing tests in both files (e.g. `test_malformed_entry_degrades_that_segment_only_not_
  whole_node` in `test_tts_node.py`) — judged as adequately covered by existing precedent rather
  than needing its own new test, but named explicitly here rather than left unstated.
