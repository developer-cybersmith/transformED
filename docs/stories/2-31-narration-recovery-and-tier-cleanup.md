---
baseline_commit: 22df9b6
---

# Story 2.31: Narration-script recovery + tier checkpoint validation + list-endpoint fields

Status: ready-for-dev

## Story

As Dev 1 (content pipeline owner),
I want the TTS fallback to preserve the real narration script, the Phase-1 checkpoint reader to reject cached work that no longer matches the lesson's tier, and `GET /lessons` to carry the two fields the dashboard needs,
so that Dev 2's remaining two reported items are closed and the tier fix from Story 2-28 cannot be silently undone by a stale cache.

**Source:** Dev 2's bug report of 2026-07-27 (items 2 and 3 — item 1 was Story 2-28), plus a Story 2-28 review finding from the Edge Case Hunter.

**Branching note:** stacked on `sprint2/dev1-pipeline-duplication-fix` (Story 2-28), not on `main` — both stories edit `package_builder_node` and overlapping regions of `graph.py`, so basing on `main` would guarantee conflicts. Rebase onto `main` once PR #100 merges.

## Acceptance Criteria

1. **AC-1 — The TTS fallback preserves the real script.** `_fallback_narration()` (`graph.py`, used by `package_builder_node` when a segment has no `audio_assets` entry) currently returns `{"script": "", ...}`, discarding narration text that is sitting in `state["narration_scripts"]`. It must recover the segment's real script by `segment_id`. Only the **audio** is missing in this degrade path — the script is not.
   - Lift **only** `entry["script"]`. **Never spread the flat entry** — `Narration` is `extra="forbid"` and `LessonPackage.model_validate` is deliberately uncaught, so a spread converts graceful degradation into a total post-spend failure.
   - Handle: `segment_id` absent from `narration_scripts`, empty/whitespace script, duplicate `segment_id` (last wins, no warning storm).
   - Must compose with the Story 2-19 timestamp-estimation block that immediately follows, not be overwritten by it.
2. **AC-2 — `_index_by_segment_id` stops raising on a malformed entry.** It uses `item[value_key]`; a single entry missing that key raises `KeyError` and takes down the node, contradicting the AC-5 "one bad item never crashes the node" guarantee its own docstring makes. Use `.get(value_key)`.
3. **AC-3 — Cached Phase-1 work is rejected when it no longer matches the lesson's tier.** `_quiz_batch_is_valid_shape` validates shape only, never count-against-band. Because Story 2-28 made `tier` actually reach the Phase-1 nodes, a lesson whose Phase-1 ran *before* that deploy holds a checkpoint sized to the wrongly-defaulted `T2` band; an ARQ retry now returns it verbatim and the T1 lesson silently ships T2 content while the logs show the tier fix working.
   - Validate the cached question count against `_TIER_QUIZ_COUNT_BAND[tier]` on **read**; treat a mismatch as a cache miss so the section regenerates.
   - **Do NOT tier-scope the checkpoint keys.** That would re-bill every section on every ARQ retry against the $3.00/lesson ceiling and violates Story 2-28 AC-5's stated invariant (keys must stay `f"{node}:{section_id}"`, guarded by `test_phase1_checkpoint_idempotency.py`).
4. **AC-4 — `GET /lessons` carries `subject` and `estimated_duration_mins`.** Dev 2 asked for these so dashboard/library cards can show real durations without an N+1 round-trip per lesson.
   - Narrow the `select` and lift the two values from the `content` JSONB via a PostgREST path selector rather than pulling the whole column.
   - **Must not regress Story 1-6 AC-7:** `list_lessons` must never resolve signed URLs or attach full `content`. Assert `sign_storage_path` / `_resolve_lesson_content` are called **zero** times and `"content" not in` the items.
   - Populate the same two fields in `get_lesson` too — otherwise the detail endpoint returns `null` for data it is already holding while the list shows a value.
   - The exact `select` string must be verified against the live project with one request before merge (PostgREST path syntax cannot be certified from source).
5. **AC-5 — Signed-URL expiry raised for embedded lesson content.** `sign_storage_path` defaults to `expires_in=3600`, and `content/router.py` bakes 1-hour URLs into the lesson response with no client-side refresh path — so a student who leaves a lesson open past an hour loses audio and images with no recovery. Raise the expiry used for embedded lesson content to a session-realistic window. Leave `GET /api/media/signed-url` dormant and documented (it has zero callers; revision-mode video may supersede it — see `docs/decisionupdate.md` §7b).
6. **AC-6 — No regression.** Full suite shows exactly the pre-existing unrelated failures. `ruff`/`ruff format`/`mypy` produce no findings that did not already exist at baseline on any touched file.

## Tasks / Subtasks

- [ ] Task 1 (AC-2): `_index_by_segment_id` → `.get(value_key)`; test that a malformed entry degrades one segment instead of crashing the node.
- [ ] Task 2 (AC-1): `_fallback_narration(script)` + recovery lookup in `package_builder_node`; 6 cases per Dev Notes.
- [ ] Task 3 (AC-3): tier-band validation on the quiz checkpoint read + test proving a T2-sized cache is rejected for a T1 lesson.
- [ ] Task 4 (AC-4): `GET /lessons` narrow select + both fields; AC-7 regression assertions.
- [ ] Task 5 (AC-5): raise embedded-content expiry; document the dormant endpoint.
- [ ] Task 6 (AC-6): full suite, lint, types.

## Dev Notes

- **This does NOT fix Dev 2's visible symptom, and the story must not claim it does.** The 0:00-quiz-fires-instantly behaviour comes from `AudioTimeline.tsx`: `audio_url == ""` → `hasAudio` false → immediate `handleEnded()`. `timeupdate` never fires, so `timestamps` are never read. Fixing the script makes the *package* correct; the player still needs a virtual playback clock (Dev 2 story) before a student sees any difference. Frame this as package fidelity or it will be reported as "didn't work".
- **The real production repro for AC-1** is the `tts_node` cache-hit replaying a persisted `node_outputs["tts_node"] = []`. `tts_node`'s own per-segment `except` already preserves `entry["script"]`, so the two index key sets are otherwise identical by construction — without this framing the fix reads as a no-op.
- **`narration_generator_node` returns `{"narration_scripts": []}`** on no-summary / LLM-failure / pacing-reject. In those cases there is genuinely no script to recover — accept the gap explicitly rather than inventing one.
- **Existing packages already built with a blank script are NOT repaired** — `package_builder_node` cache-hits and returns the stored dict verbatim. Affected lessons need their `package_builder` checkpoint cleared.
- **`_base_state()` in `test_package_builder_node.py` has no `narration_scripts`**, so the AC-1 fix is inert in every existing unit test until the fixture is extended. Derive `NARRATION_SCRIPTS` from `AUDIO_ASSETS` (flat shape: `{"segment_id": ..., "script": ...}`) and wire it in.
- **Fixture narration is currently identical for every segment** (deferred from Story 2-28 for exactly this reason) — make it segment-specific, or an AC-1 assertion cannot fail for the right reason.
- Every new test needs `@pytest.mark.unit` **and** `@pytest.mark.asyncio`.

### Project Structure Notes

Touches `apps/api/app/modules/content/pipeline/graph.py`, `apps/api/app/modules/content/router.py`, `apps/api/app/core/storage.py`, `apps/api/app/modules/media/router.py` (docstring only), and unit tests. **No** `packages/shared/*` and **no** `supabase/migrations/*` — §16 four-dev gate not triggered. Zero `apps/web/**` changes.

**Deliberately rejected to avoid the §16 gate:** emitting `audio_path` alongside `audio_url` (`Narration` is `additionalProperties: false`), and adding list-response types to `packages/shared/types/lesson.ts`.

### Cross-team

Hand-off to Dev 2, hard prerequisite for calling Bug 2 closed: a virtual playback clock in `AudioTimeline.tsx` (three-way branch on `hasAudio` / `!hasAudio && script.trim()` / neither; interval accumulator advancing only while `PLAYING`, calling `processTimeUpdate` — it must **never** call `handleEnded()`, since `processTimeUpdate`'s own boundary check already fires the quiz). Note the S2-26 never-stuck test uses a full-script fixture and will need re-pointing.

### References

- [Source: Dev 2 bug report, 2026-07-27]
- [Source: docs/stories/2-28-pipeline-state-duplication-fix.md — AC-3, AC-5 invariant]
- [Source: DEV1-FIX-PLAN.md — Phases 3 and 6]
- [Source: docs/decisionupdate.md §7b — revision-mode video, re signed-URL dormancy]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-28 | Story created. Folds in the tier-blind checkpoint finding from Story 2-28's Edge Case Hunter review (AC-3) and the signed-URL expiry gap (AC-5) alongside Dev 2's two remaining reported items. | Dev 1 |
