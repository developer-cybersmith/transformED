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
1. Adds `tinytag` (MIT, pure-Python, no ffmpeg binary — audio-metadata-only, consistent
   with CLAUDE.md's "no video/ffmpeg code exists yet" stance) as a runtime dependency.
   **Round 2 correction:** Round 1 shipped this with `mutagen` instead, and asserted (wrongly,
   unverified) that `mutagen` is MIT — it is actually GPL-2.0-or-later. Caught in the real
   `/bmad-code-review` (Blind Hunter AND Acceptance Auditor, independently) and swapped to
   `tinytag`, a genuinely MIT-licensed, functionally equivalent library — see this story's
   Round 2 Senior Developer Review section.
2. `tts_node`, right after a successful synthesis produces real `audio_bytes`
   (`graph.py:~3451`), measures the REAL duration in milliseconds via
   `tinytag.TinyTag.get(file_obj=io.BytesIO(audio_bytes)).duration * 1000`, wrapped in its own
   try/except (a parse failure degrades to `duration_ms=None`, never crashes the segment —
   this node's entire documented purpose is to never hard-fail).
3. Carries that value as a **sibling** `"duration_ms"` key on the per-segment `audio_assets`
   wrapper dict (`{"segment_id": ..., "data": ..., "duration_ms": ...}`) — NOT inside `"data"`,
   because `"data"` is exactly the frozen, `extra="forbid"` `Narration.model_dump()` payload and
   a new key there would raise on any future `model_validate` round-trip.
4. `package_builder_node` reads that sibling key into a `duration_ms_by_id` map (validated —
   see Round 2 note below) and passes the segment's value into `_estimate_slide_timestamps` via a
   new optional `known_duration_ms` keyword — used directly as the total duration when not `None`
   and finite; the pre-existing word-count estimate is the fallback, byte-for-byte unchanged,
   otherwise (browser fallback, an unparseable buffer, or — Round 2 — a non-numeric/NaN value
   from a schema-drifted checkpoint, which Round 1 did not guard against and would have crashed
   the whole node via a bare `round()`).

## Story

**As** a student playing a generated lesson,
**I want** the slide-sync timestamps in my lesson package to be built from the REAL duration of
the narration audio that will actually play, not a word-count guess,
**so that** slide changes (and the segment-end quiz trigger) land at the moments the real audio
is actually at, instead of visibly drifting further out of sync the longer a segment runs.

## Acceptance Criteria

### Functional

- [x] **AC 1.** `tinytag>=2.3.0,<3.0.0` is added to `apps/api/pyproject.toml`'s `[project]`
  `dependencies` list, with a comment noting it is audio-metadata-only (no ffmpeg binary,
  not a video/transcoding dependency).
  **Verified:** `apps/api/pyproject.toml:39` —
  `"tinytag>=2.3.0,<3.0.0",        # MIT — audio-metadata only (no ffmpeg binary); measures REAL MP3 duration in tts_node (Story S3-38)...`.
  **Round 2 correction:** Round 1 shipped `mutagen>=1.47.0` here, labeled `# MIT`, and the AC
  text below claimed the same — both wrong. `pip show mutagen` / mutagen's own `COPYING` file:
  GPL-2.0-or-later. Caught by the real `/bmad-code-review` (Blind Hunter AND Acceptance Auditor,
  independently), swapped to `tinytag` (verified MIT via `pip show tinytag` — `License-Expression:
  ` classifier + `LICENSE` file, both MIT), consistent with this codebase's zero-copyleft-
  dependency pattern. See Round 2 review section for the full reasoning.
- [x] **AC 2.** On `tts_node`'s success path (`audio_bytes is not None`, i.e. Sarvam or Azure
  actually returned audio), the node measures the real duration in milliseconds from those exact
  bytes via `tinytag.TinyTag.get` and rounds to the nearest int.
  **Verified:** `graph.py:~3501-3504` (`tag = TinyTag.get(file_obj=io.BytesIO(audio_bytes)); ...
  duration_ms = round(tag.duration * 1000)`);
  `test_successful_synthesis_measures_real_duration_via_tinytag` asserts
  `assets[0]["duration_ms"] == _real_mp3_duration_ms()` against a genuine hand-built MP3 fixture
  — PASSED. (Round 2: renamed from `..._via_mutagen` when the library was swapped.)
- [x] **AC 3.** A `tinytag` parse failure (corrupt/empty/non-MP3 buffer) is caught in its own
  try/except, logs a warning, and leaves `duration_ms=None` — it must never raise out of
  `tts_node`, matching the node's existing "never hard-fails" contract for every other failure
  mode in the same loop.
  **Verified:** `test_tinytag_parse_failure_degrades_duration_to_none_not_crash` feeds
  `b"AUDIO_BYTES"` (not real MP3) through the mocked provider — node completes normally,
  `duration_ms is None`, `audio_provider == "sarvam"`, `audio_url` still set — PASSED.
- [x] **AC 4.** Every per-segment `audio_assets` wrapper dict gains a `"duration_ms"` key
  **sibling to** `"data"` (never inside it) — `None` on the browser-fallback path
  (`audio_bytes is None`) and on the whole-segment exception/degrade path, a real measured
  value on success.
  **Verified:** 4 tests cover all 3 paths (`test_successful_synthesis_measures_real_duration_via_tinytag`,
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
- [x] **AC 7.** `package_builder_node` builds a `duration_ms_by_id` map reading the sibling
  `"duration_ms"` key out of `state["audio_assets"]` and passes
  `known_duration_ms=duration_ms_by_id.get(segment_id)` into its `_estimate_slide_timestamps`
  call site.
  **Verified:** `graph.py:~4127-4162` (lookup), `graph.py:~4308` (call site kwarg) —
  `test_package_builder_uses_real_duration_not_word_count_estimate` PASSED. **Round 2:** the
  lookup was a dict comprehension in Round 1; Edge Case Hunter found it trusted
  `item.get("duration_ms")` unvalidated, which could crash the node on a non-numeric/NaN
  checkpoint value — rewritten as a `for` loop with explicit numeric/finite validation (logging,
  never crashing) and duplicate-`segment_id` warning parity with `_index_by_segment_id`. See
  Round 2 review section.
- [x] **AC 8.** The final `LessonPackage`'s `segments[i].narration.timestamps` for a segment
  whose audio was really synthesized reflect the REAL measured duration (verified against a
  genuine, tinytag-parseable MP3 fixture — not a fake byte string), not the word-count formula's
  output for the same script/slide count.
  **Verified:** `test_package_builder_uses_real_duration_not_word_count_estimate` asserts
  `ts[0]["end_ms"] == real_duration_ms (2612)` and `!= word_count_estimate_ms (1200)` on the
  actual `LessonPackage`-shaped `result["lesson_package"]` — PASSED. (Round 2: the fixture's
  measured value changed from ~2606ms under `mutagen`'s byte-count/bitrate method to ~2612ms
  under `tinytag`'s frame-count method — same bytes, two different legitimate MP3 duration
  algorithms; see `test_fixture_duration_matches_a_pinned_independently_computed_value`.)

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
  test) — exactly the predicted failure modes. (This was Round 1's RED run, against the
  mutagen-era code — the `2606` here is that round's real observed value, left as an accurate
  historical record rather than rewritten to `2612`. Round 2's own new crash-prevention tests
  have their own independent RED confirmation, pasted in the Round 2 review section below.)
- [x] **AC 10.** The browser-fallback / unknown-duration path (`tinytag` parse failure, or no
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
  **Verified (Round 1):** `ruff check` → "All checks passed!"; `ruff format --check` → "2 files
  already formatted" (graph.py + new test file); `mypy app/modules/content/pipeline/graph.py
  --ignore-missing-imports` → "Success: no issues found in 1 source file" (required a
  `None`-narrowing guard + one `# type: ignore[no-untyped-call]` on the `MP3(...)` call, since
  `mutagen`'s own typed `FileType.info` attribute is `StreamInfo | None` and `strict = true`'s
  `disallow_untyped_calls` flags the constructor itself — documented in Debug Log).
  **Re-verified (Round 2, after the `mutagen` -> `tinytag` swap and the defensive-fix edits):**
  `ruff check .` → "All checks passed!"; `ruff format --check` on both modified files → "2 files
  already formatted"; `mypy app/modules/content/pipeline/graph.py --ignore-missing-imports` →
  "Success: no issues found in 1 source file" — **`tinytag` needed no `# type: ignore` at all**
  (unlike `mutagen`, it ships full call-site annotations on `TinyTag.get`, not just a `py.typed`
  marker), so the `no-untyped-call` suppression from Round 1 is gone entirely, not just changed.
  Full command output pasted in the Round 2 review section.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one segment's synthesized audio buffer, measured
   once per segment per `tts_node` run. Range: 4–12 segments per lesson (per
   `docs/handoffs/lesson-delivery-dev1.md`), each buffer typically a few seconds to ~2 minutes of
   narration audio (a few KB to low hundreds of KB of MP3). `tinytag.TinyTag.get(...)` parses the
   MP3 header/frame table in memory — it does not decode audio samples, so cost does not scale with
   duration, only with doing it once per segment (same order as the existing per-segment Storage
   upload it sits next to). *(Round 2: swapped from `mutagen` to `tinytag` — see this story's
   Round 2 Senior Developer Review section; the license-driven library swap does not change this
   answer, both parse header/frame metadata only.)*
2. **Fixed budget vs. variable input.** N/A with reason: this story introduces no new fixed
   budget/cap. It replaces one *already-existing*, always-approximate value
   (`_estimate_slide_timestamps`'s word-count guess) with a measured one when available, and
   preserves the exact prior fallback behavior otherwise — there is no new place a variable input
   can exceed a fixed budget. **Round 2 correction (Blind Hunter — the original wording here was
   wrong, not just imprecise):** this originally claimed `audio_bytes` "already passed through the
   existing `check_ceiling`... so it is not attacker-controlled or unbounded-by-construction here."
   `check_ceiling` is a **dollar-cost** guard (the $3.00/lesson ceiling), not a byte-size or
   audio-duration bound — it says nothing about how large a single TTS provider response can be.
   The corrected answer: there is genuinely no NEW size ceiling introduced by this story (the
   header-only parse cost is independent of buffer size for any input a TTS provider would
   plausibly return), but there was also no PRE-EXISTING byte-size ceiling on `audio_bytes` for
   this story to inherit or rely on either — that gap (if it is one) belongs to `tts_node`'s
   provider-response handling generally, predates this story, and is out of this story's scope to
   fix. Recorded accurately rather than claimed-safe-by-a-guard-that-doesn't-cover-it.
3. **Scope of every limit.** N/A — no limit introduced.
4. **Unbounded reads/writes.** None introduced. `duration_ms_by_id` in `package_builder_node`
   iterates `state["audio_assets"]`, a list already fully materialized in memory by the time
   `package_builder_node` runs (same list `audio_by_id`'s existing `_index_by_segment_id` call
   already iterates, one line above) — no new Supabase read, no new iteration source. Per
   CLAUDE.md's own framing for pipeline-internal work: this is in-memory, not request-path, so
   `tests/unit/test_unbounded_queries.py`'s `.limit()`/`.range()` requirement does not apply —
   stated explicitly per this task's instructions, not skipped silently. **Round 2 (Edge Case
   Hunter):** the ORIGINAL `duration_ms_by_id` dict comprehension trusted `item.get("duration_ms")`
   as-is from a Supabase JSONB checkpoint — a schema-drifted or hand-edited value (non-numeric or
   NaN) reached `_estimate_slide_timestamps`'s bare `round(known_duration_ms)` and raised
   `TypeError`/`ValueError`, crashing the WHOLE node rather than degrading just that one segment —
   the same failure class `_index_by_segment_id` was hardened against for `audio_by_id` one story
   ago (D32/D33). This is a "which values are trusted after a JSONB round trip" defect, not an
   unbounded-reads one, but it is exactly the kind of thing Q4's spirit exists to surface —
   confirmed reproducible by execution (see Round 2 review section) and fixed: non-numeric/
   non-finite values are now validated and normalised to `None` (logged), both where the map is
   built AND, defence-in-depth, inside `_estimate_slide_timestamps` itself.
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

**Cumulative, Round 1 + Round 2:**

- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED (`tts_node`: real duration
  measurement, sibling `duration_ms` key on every path — Round 1 via `mutagen`, **Round 2:
  swapped to `tinytag`** (license fix); `_estimate_slide_timestamps`: new optional
  `known_duration_ms` keyword, docstring updated, **Round 2: added a `math.isfinite` guard**
  (defence-in-depth against non-finite values reaching a bare `round()`);
  `package_builder_node`: `duration_ms_by_id` lookup wired into the existing
  `_estimate_slide_timestamps` call site — **Round 2: rewritten from an unvalidated dict
  comprehension into a validated loop** (non-numeric/non-finite values normalised to `None` and
  logged, duplicate-`segment_id` warning added) after Edge Case Hunter found the original could
  crash the whole node on a malformed checkpoint value)
- `apps/api/pyproject.toml` — MODIFIED (Round 1: added `mutagen>=1.47.0`; **Round 2: replaced
  with `tinytag>=2.3.0,<3.0.0`**, license comment corrected)
- `apps/api/tests/unit/test_audio_duration_s3_38.py` — NEW, then MODIFIED in Round 2 (17 tests
  total: the original 10 renamed/updated for the `tinytag` swap, plus 7 new — a pinned-literal
  duration cross-check, a two-segment mixed-duration-outcome test, two crash-prevention tests
  (non-numeric and NaN `duration_ms`), a direct `_estimate_slide_timestamps` finiteness unit
  test, a duplicate-`segment_id` logging test, and a JSON checkpoint round-trip test)
- `docs/stories/3-38-real-audio-duration.md` — MODIFIED (this file: story-first commit, then
  ACs/tasks checked off with verification notes, Dev Agent Record filled in, Round-1 self-review
  added; **Round 2: AC/Scale & Load text corrected in place where Round 1's claims were wrong,
  Round 2 Senior Developer Review section added**)

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
- 2026-08-12: Round 2 — real `/bmad-code-review`, 4 independent parallel agents. Confirmed one
  high-severity finding by execution (`pip show mutagen`): `mutagen` is GPL-2.0-or-later, not
  MIT as Round 1's AC 1/pyproject comment claimed — swapped to `tinytag` (genuinely MIT,
  verified the same way). Confirmed a second, real crash risk by execution (reverted the fix,
  reproduced `TypeError`/`ValueError`): `duration_ms_by_id` trusted an unvalidated checkpoint
  value into a bare `round()` — now validated, with a matching defence-in-depth guard inside
  `_estimate_slide_timestamps` itself. Added 7 new tests (pinned-literal duration cross-check,
  two-segment mixed-duration-outcome, two crash-prevention tests, a direct finiteness unit test,
  a duplicate-`segment_id` log test, a JSON checkpoint round-trip) — 17/17 pass. Full regression: `test_tts_node.py` 14/14,
  `test_package_builder_node.py` 39/39, CI guards `test_node_return_shape.py`/
  `test_unbounded_queries.py` 19/19, broader `tests/unit/` 1010/1010 (excluding the same
  pre-existing `pypdfium2`/`pdfplumber` environment gap Round 1 and Story 3-36 both already
  documented). `ruff check` / `ruff format --check` / `mypy --ignore-missing-imports` all clean
  — `tinytag` needed zero `# type: ignore` (fully call-site-annotated), unlike `mutagen`.
  Corrected AC 1/2/3/4/7/8/10/13 and the Scale & Load Q1/Q2/Q4 text in place to reflect current
  (Round 2) reality rather than leaving them describing Round 1's `mutagen`-based
  implementation. One Blind Hunter finding investigated and REJECTED as factually wrong (the
  `except` block's `duration_ms = None` reset is not a dead assignment — traced the exact
  control flow and confirmed it discards a real, already-measured value on late validation
  failure). Full findings table and dispositions below.

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
  **Round 2: added anyway** (`test_two_segments_with_different_duration_outcomes_do_not_leak`)
  — Blind Hunter raised the same gap independently, and it was cheap enough to just close
  directly rather than re-argue the precedent-coverage judgment call a second time.

## Senior Developer Review (AI) — Round 2 (real `/bmad-code-review`, 4 parallel agents)

**Review date:** 2026-08-12
**Outcome:** APPROVE WITH CHANGES — all applied before merge, including one defect (the license
mislabel) more consequential than anything Round 1 found, and one confirmed-by-execution crash
risk Round 1's self-review did not catch.

Round 1 was Dev 1 self-reviewing inline — real diligence (10/10 tests, RED/GREEN both
demonstrated, mypy genuinely fixed), but not independent, exactly as its own Layer 1 disclosed.
This round ran 4 genuinely independent parallel reviewers (a Cynical/Blind-Hunter-style pass —
diff-only; an Edge Case Hunter — diff + project read access; an Acceptance Auditor — diff + this
story file, independently re-executing everything claimed; a Scale & Load Hunter — diff +
`docs/SCALE-CONTRACT.md`). Every finding below was independently re-verified by actually running
something (not taken on the reviewer's word) before being fixed, accepted, or rejected — the
same rigor this project's own `docs/DEFECT-REGISTER.md` describes as missing from 9 of its first
11 defects.

### The most severe finding — a real license violation, CONFIRMED by execution

Two of four reviewers (the Cynical/Blind-Hunter pass and the Acceptance Auditor, independently)
flagged that `mutagen` is asserted `# MIT` in `pyproject.toml`, in the story's "What this story
does" §1, and in AC 1's "Verified" note — and that this is simply wrong. Checked directly, not
taken on either reviewer's word: `pip show mutagen` in a real venv →
`License-Expression: GPL-2.0-or-later`; the installed package's own `COPYING` file is the literal
GNU GPL v2 text. This is the exact "asserted, not verified" failure pattern
`docs/DEFECT-REGISTER.md`'s binding rules exist to catch, applied to a license claim instead of
an exception hierarchy or a DB column — in a codebase whose CLAUDE.md bans PyMuPDF **by name**
for AGPL-3.0 and hand-picked every other PDF library specifically for a verified permissive
license. GPL-2.0-or-later does not carry AGPL's network-use ("SaaS is conveying") trigger, so
this is not the identical legal risk shape as the PyMuPDF case — but given a genuinely equivalent
MIT-licensed library (`tinytag`) exists and is a drop-in replacement, the safest fix is to
eliminate the ambiguity entirely rather than rely on a legal interpretation nobody here is
qualified to bless. Swapped `mutagen` → `tinytag` (verified MIT the same way: `pip show tinytag`
→ `License-Expression: MIT`, `LICENSE` file present, MIT text). Every AC, the Scale & Load
section, and the test file were updated to match — not left describing a dependency the code no
longer uses.

### The second-most-severe finding — a confirmed, reproducible crash, not a hypothetical

The Edge Case Hunter found that `duration_ms_by_id`'s original dict comprehension trusted
`item.get("duration_ms")` from a Supabase JSONB checkpoint as-is, and that
`_estimate_slide_timestamps`'s `round(known_duration_ms)` has no type/NaN guard — the exact
failure class `_index_by_segment_id` was hardened against for `audio_by_id` one story ago
(D32/D33). **Reproduced by execution, not assumed:** reverted the fix and ran the two new
crash-prevention tests against the pre-fix code —

```
tests/unit/test_audio_duration_s3_38.py::test_non_numeric_duration_ms_does_not_crash_package_builder FAILED
tests/unit/test_audio_duration_s3_38.py::test_nan_duration_ms_does_not_crash_package_builder FAILED
tests/unit/test_audio_duration_s3_38.py::test_estimate_slide_timestamps_rejects_non_finite_known_duration_directly FAILED

E   TypeError: type str doesn't define __round__ method
E   ValueError: cannot convert float NaN to integer
E   ValueError: cannot convert float NaN to integer
```

— confirming a schema-drifted or hand-edited `duration_ms` really does crash the WHOLE node
(not just degrade one segment), contradicting `package_builder_node`'s own documented "one bad
item never crashes the whole node" guarantee. Fixed at both ends: `duration_ms_by_id` is now
built by an explicit loop that normalises non-numeric/non-finite values to `None` (logged, never
raised) and warns on a duplicate `segment_id` (parity with `_index_by_segment_id`'s existing
observability for the sibling `audio_by_id` map); `_estimate_slide_timestamps` itself also gained
a `math.isfinite` guard as defence-in-depth, since it is a public module symbol other future
callers could reach directly with an unvalidated value.

### Findings — fixed

| # | Finding | Source | Fix |
|---|---|---|---|
| 1 | `mutagen` mislabeled MIT; actually GPL-2.0-or-later — see above | Cynical/Blind Hunter AND Acceptance Auditor, independently, both confirmed via `pip show` | Swapped `mutagen` → `tinytag` (genuinely MIT, verified the same way) throughout `pyproject.toml`, `graph.py`, the test file, and every AC/Scale-&-Load reference that asserted the old library or its (wrong) license. |
| 2 | `duration_ms_by_id` crashes the whole node on a non-numeric/NaN checkpoint value — see above | Edge Case Hunter; reproduced by execution (reverted the fix, ran the new tests, got the exact predicted `TypeError`/`ValueError`) | `duration_ms_by_id` rewritten as a validated loop (non-numeric/non-finite → `None`, logged); `_estimate_slide_timestamps` gained a matching `math.isfinite` guard, defence-in-depth. 3 new tests (non-numeric, NaN, direct-unit-test finiteness check). |
| 2b | `duration_ms_by_id`'s original comprehension bypassed `_index_by_segment_id`'s duplicate-`segment_id` warning log — the sibling `audio_by_id` map logs it, this one didn't | Cynical/Blind Hunter | The rewritten loop now logs it too; `test_duplicate_segment_id_in_audio_assets_duration_ms_keeps_last_and_logs` proves it fires (via `caplog`), not just that "last one wins" resolves without crashing. |
| 3 | Headline duration test computes its "expected" value via the exact same `round(x * 1000)`-shaped formula the production code runs, so it cannot catch a bug that changed that formula identically in both places | Cynical/Blind Hunter | Added `test_fixture_duration_matches_a_pinned_independently_computed_value` — asserts against a hardcoded literal (`2612`), independently observed by actually running the fixture through `tinytag`, not re-derived from the MPEG spec on paper (which would risk drifting from what the library actually computes). |
| 4 | The fixture's own docstring/comment claimed `frame_len = 144 * bitrate / sample_rate = 470 bytes` — the actual value is 417 (`(144 * 128_000) // 44_100 == 417`) | Cynical/Blind Hunter, verified independently by direct computation | Comment corrected in the test file; noted as a Round 1 documentation-only error (the code always computed the real number — only the comment's arithmetic was wrong, so no test was ever silently trusting the wrong value). |
| 5 | `duration_ms_by_id: dict[str, Any]` discarded the `float \| None` precision `_estimate_slide_timestamps`'s own `known_duration_ms` parameter is careful to declare | Cynical/Blind Hunter | Retyped as `dict[str, float \| None]` as part of the same loop rewrite (finding #2). |
| 6 | No test covers a JSONB checkpoint round trip for the new `duration_ms` field | Cynical/Blind Hunter | Added `test_duration_ms_survives_a_json_checkpoint_round_trip` — narrow and explicit about its own scope (covers that `float \| None`, including NaN, round-trips through `json.dumps`/`json.loads` cleanly; does not claim to cover the full Supabase-mock checkpoint path end-to-end, which is a systemic property of how this entire test suite mocks Supabase, not specific to this field — see "accepted, not fixed" below). |
| 7 | No test runs two segments with different duration outcomes in the same `package_builder_node` call | Cynical/Blind Hunter AND Scale & Load Hunter (via the corrected Q4 answer), independently; Round 1's own self-review had already named this as a judgment call, not a gap | Added `test_two_segments_with_different_duration_outcomes_do_not_leak` — proves sec_0's real duration and sec_1's word-count-estimate fallback don't cross-contaminate in one call. |
| 8 | Scale & Load Q2 claimed `check_ceiling` bounds `audio_bytes`'s size — it is a dollar-cost guard, not a byte-size one | Cynical/Blind Hunter | Q2 corrected in place: no NEW size ceiling is introduced by this story, but there was also no pre-existing one to rely on — stated accurately instead of claimed-safe-by-a-guard-that-doesn't-cover-it (see Scale & Load section above). |
| 9 | AC 1/2/3/4/7/8/10/13 and the "What this story does" section still describe the Round 1 `mutagen`-based implementation after the Round 2 swap | Acceptance Auditor (implicit — flagged that ACs must describe current, not historical, state) | All corrected in place, each with an explicit "Round 2 correction/note" marking what changed and why, rather than silently rewritten as if Round 1 had always used `tinytag`. |

### Findings — accepted, not fixed (reasoning recorded)

- **The `except` block's `duration_ms = None` is a "redundant, misleading dead assignment"**
  (Cynical/Blind Hunter). **Investigated and REJECTED as factually wrong**, not accepted: traced
  the exact control flow in `tts_node` (`graph.py:~3425-3550`). The mutagen/tinytag measurement
  happens INSIDE the same outer per-segment `try` block, followed by `Narration.model_validate(...)`
  — which can still raise. Any exception anywhere in that block (including AFTER a successful
  duration measurement) reaches the outer `except`, which is exactly where this reset lives. It is
  not a no-op: it discards a real, already-measured `duration_ms` when a LATER step in the same
  try block (e.g. Narration validation) fails. The comment's own claim ("whatever partial work
  happened before the exception... is discarded") is accurate. Kept as-is; recorded here so the
  claim is not re-raised.
- **No test characterizes `tinytag`'s (or `mutagen`'s, originally) behavior on a
  truncated-but-header-valid MP3** (Cynical/Blind Hunter, Scale & Load Hunter, and Round 1's own
  self-review, all independently). Still not fixed in Round 2 — genuinely low severity (the
  surrounding try/except already degrades any parse anomaly to `None`, never a crash or a
  silently-wrong-but-plausible value) and would need a deliberately-crafted truncated fixture that
  adds real complexity for a case this story's fallback chain already handles safely by
  construction. Left as a named, un-actioned gap rather than silently dropped a second time.
- **The JSON checkpoint round-trip test (finding #6, fixed above) does not cover the FULL
  Supabase-mocked checkpoint path end-to-end** — every OTHER test in this file (and in
  `test_tts_node.py`/`test_package_builder_node.py`) mocks the Supabase client to hand back a
  native Python dict directly, never a real serialized JSON string. This is a systemic property
  of how this entire test suite mocks Supabase across every field of every node output, not
  something specific to `duration_ms` — fixing it comprehensively would mean re-architecting the
  Supabase test-double strategy pipeline-wide, which is out of this single story's scope. The
  narrow round-trip test added here demonstrates `duration_ms` specifically carries no
  JSON-unsafe type (no datetime/Decimal/etc.), which is the concrete risk this field could have
  introduced; it does not claim to close the systemic gap.
- **Whether GPL-2.0-or-later would actually have been a live legal problem for a
  backend-only, never-redistributed dependency** (Acceptance Auditor's nuance, echoing the
  Cynical/Blind Hunter finding) — genuinely debatable (GPL-2.0 lacks AGPL's network-use trigger,
  and this codebase never distributes `apps/api` as software to end users). Not resolved by
  argument here: swapped the dependency instead, which makes the question moot rather than
  requiring a legal judgment call this review is not positioned to make.

### Re-verification after fixes

- `test_audio_duration_s3_38.py` — 17/17 pass (10 Round 1 + 7 Round 2)
- The 3 new Round 2 crash-prevention/finiteness tests RED-confirmed by reverting `graph.py` alone
  (`git stash`, not assumed) and re-running against the pre-Round-2 code — all 3 failed with the
  exact predicted exception types (pasted above), then restored and reconfirmed GREEN
- `test_tts_node.py` — 14/14 pass, file untouched
- `test_package_builder_node.py` — 39/39 pass, file untouched
- `test_node_return_shape.py` + `test_unbounded_queries.py` (CI guards) — 19/19 pass
- Broader `tests/unit/` suite — 1011 passed, 1 skipped (excluding the same pre-existing
  `pypdfium2`/`pdfplumber`-module-not-found environment gap Round 1 and Story 3-36 both already
  documented; included, it's 1022 passed / 19 pre-existing-unrelated-failed / 6 skipped, same 19
  failures as with this story's changes stashed out — confirmed identical either way)
- `ruff check .` → "All checks passed!"
- `ruff format --check` on both modified files → "2 files already formatted"
- `mypy app/modules/content/pipeline/graph.py --ignore-missing-imports` → "Success: no issues
  found in 1 source file" — zero `# type: ignore` needed for `tinytag` (fully call-site-annotated,
  unlike `mutagen`)
- `uv.lock` deliberately left untouched (matches Round 1's own convention): CI installs via
  `uv pip install -e ".[dev]" --system`, not a locked sync, so the lockfile is not
  merge-blocking either way — verified by reading `.github/workflows/ci.yml` directly rather than
  assuming.
