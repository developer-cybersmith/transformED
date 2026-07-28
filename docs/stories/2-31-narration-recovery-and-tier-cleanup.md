---
baseline_commit: 22df9b6
---

# Story 2.31: Narration-script recovery + tier checkpoint validation + list-endpoint fields

Status: ready-for-review

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
   - **Stamp the generating `tier` into the checkpoint VALUE on write; on read, reject when the stamp disagrees with this lesson's tier** so the section regenerates.
   - **Do NOT tier-scope the checkpoint keys.** That would re-bill every section on every ARQ retry against the $3.00/lesson ceiling and violates Story 2-28 AC-5's stated invariant (keys must stay `f"{node}:{section_id}"`, guarded by `test_phase1_checkpoint_idempotency.py`). A stamp in the *value* satisfies both constraints: the key space is untouched, and a same-tier retry is still a free cache hit.
   - **Legacy checkpoints** (written before this story) carry no stamp, so their provenance is unknowable. For those only, fall back to a count heuristic: reject `count > n_max`, since the write path truncates to `n_max` and a larger batch can only have come from a higher band. Do **not** extend it to `count < n_min` — the write path deliberately keeps short batches (Story **3-28** AC-8: *"Partial batch accepted… It does NOT discard the passing questions"*), so a below-band count is ambiguous between a stale-tier cache and legitimate underproduction. Log it; do not re-bill it.
   - **A rejected cache must never become an empty quiz.** If regeneration then fails (no parsed response, or every question fails validation), salvage the rejected-but-structurally-valid cached batch, truncate to `n_max`, and **re-stamp it with this lesson's tier**. Without this, a rejected cache plus one transient LLM failure ships a segment with zero questions — worse than the wrong-tier content the guard exists to prevent — and leaves the stale checkpoint in place, so every retry re-rejects and re-bills. `quiz_generator_node` has no `check_ceiling()` gate, so nothing else bounds that loop.

   > **Amended 2026-07-28 after review.** As first written this AC said "validate the cached question **count** against `_TIER_QUIZ_COUNT_BAND[tier]`". Implemented that way it could not catch its own named hazard: stale caches are all T2-sized (2–3 questions) and T1's `n_max` is 5, so every stale T2 cache passed for exactly the T1 lessons this AC describes. The count guard fired only for T3 lessons holding a 3-question cache — one tier of three, one of two possible stale counts. The wording above now describes the tier-stamp design that actually closes it. The original justification for narrowing also mis-cited Story 2-28 AC-8 (which is *Three canaries*); the keep-short-batches rule is Story **3-28** AC-8.
4. **AC-4 — `GET /lessons` carries `subject` and `estimated_duration_mins`.** Dev 2 asked for these so dashboard/library cards can show real durations without an N+1 round-trip per lesson.
   - Narrow the `select` and lift the two values from the `content` JSONB via a PostgREST path selector rather than pulling the whole column.
   - **Must not regress Story 1-6 AC-7:** `list_lessons` must never resolve signed URLs or attach full `content`. Assert `sign_storage_path` / `_resolve_lesson_content` are called **zero** times and `"content" not in` the items.
   - Populate the same two fields in `get_lesson` too — otherwise the detail endpoint returns `null` for data it is already holding while the list shows a value.
   - The exact `select` string must be verified against the live project with one request before merge (PostgREST path syntax cannot be certified from source).
5. **AC-5 — Signed-URL expiry raised for embedded lesson content.** `sign_storage_path` defaults to `expires_in=3600`, and `content/router.py` bakes 1-hour URLs into the lesson response with no client-side refresh path — so a student who leaves a lesson open past an hour loses audio and images with no recovery. Raise the expiry used for embedded lesson content to a session-realistic window. Leave `GET /api/media/signed-url` dormant and documented (it has zero callers; revision-mode video may supersede it — see `docs/decisionupdate.md` §7b).
6. **AC-6 — No regression.** Full suite shows exactly the pre-existing unrelated failures. `ruff`/`ruff format`/`mypy` produce no findings that did not already exist at baseline on any touched file.

## Tasks / Subtasks

- [x] Task 1 (AC-2): `_index_by_segment_id` → `.get(value_key)`; test that a malformed entry degrades one segment instead of crashing the node.
- [x] Task 2 (AC-1): `_fallback_narration(script)` + recovery lookup in `package_builder_node`; 6 cases per Dev Notes.
- [x] Task 3 (AC-3): tier-band validation on the quiz checkpoint read + test proving a T2-sized cache is rejected for a T1 lesson.
- [x] Task 4 (AC-4): `GET /lessons` narrow select + both fields; AC-7 regression assertions.
- [x] Task 5 (AC-5): raise embedded-content expiry; document the dormant endpoint.
- [x] Task 6 (AC-6): full suite, lint, types.

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

## Dev Agent Record

### Completion Notes

**AC-1 — narration recovery.** `_fallback_narration()` now takes the script:
`def _fallback_narration(script: str = "") -> dict[str, Any]`. `package_builder_node`
builds a `narration_script_by_id` index alongside the existing `audio_by_id` and lifts
**only** `entry["script"]` — never a spread, per the AC's `extra="forbid"` warning. The
recovery sits before the Story 2-19 timestamp-estimation block, so estimation still runs
over the recovered script rather than overwriting it. `_base_state()` in
`test_package_builder_node.py` gained a `NARRATION_SCRIPTS` fixture derived from
`AUDIO_ASSETS` with **segment-specific** text, so an AC-1 assertion can only pass for the
right reason.

**AC-2 — `_index_by_segment_id`.** `item[value_key]` → `item.get(value_key)`. A malformed
entry now yields `None` for that one segment instead of `KeyError`-ing the node.

**AC-3 — tier STAMP (first implementation was wrong; corrected in the review round).**

*What shipped first, and why it was wrong.* The initial guard rejected a cached batch only
when `count > _TIER_QUIZ_COUNT_BAND[tier][1]`, and the record defended that narrowing as
forced by the keep-short-batches rule. The Acceptance Auditor showed it **could not catch
the hazard AC-3 names**: pre-2-28 checkpoints are all T2-sized (2–3 questions) and T1's
`n_max` is 5, so every stale T2 cache passed cleanly for exactly the T1 lessons the AC
describes. The guard fired only for T3 lessons holding a 3-question cache. Worse, the test
that "proved" it used a 5-question cache against T3 — a count the write path can never
produce for T2 — so it validated a shape the migration hazard cannot generate.

Two further errors in that first record, both confirmed: the justification cited **Story
2-28 AC-8**, which is *Three canaries*; the keep-short-batches rule is **Story 3-28 AC-8**.
And the narrowing was presented as forced when it was not — stamping the tier in the
checkpoint **value** was never considered.

*What ships now.* `_write_phase1_checkpoint` records `{"segment_id", "questions", "tier"}`.
On read, a stamp disagreeing with the lesson's tier is an exact reject. This satisfies both
prior invariants — the key stays `f"{node}:{section_id}"` (2-28 AC-5), and a same-tier retry
is still a free cache hit — so the cost objection that motivated the narrowing does not
apply. Legacy unstamped checkpoints keep the `n_max` heuristic as a fallback, with
`count < n_min` logged but **not** rejected (still genuinely ambiguous, per 3-28 AC-8).
The residual gap now applies only to legacy checkpoints and closes as they age out.

*Salvage path (new, from Process Integrity + Edge Case Hunter, found independently).* A
rejected cache followed by a failed regeneration previously returned `{"quiz_questions": []}`
via two early returns that write **no** checkpoint — so the segment shipped zero questions
*and* the stale checkpoint survived, making every ARQ retry re-reject and re-bill.
`quiz_generator_node` has no `check_ceiling()` call, so nothing bounded it. Regeneration
failure now salvages the rejected batch, truncates to `n_max`, and re-stamps it.

**AC-4 — list endpoint.** `_LIST_COLUMNS` replaces `select("*")` with an explicit column
list plus two PostgREST path selectors
(`subject:content->metadata->>subject`, `estimated_duration_mins:content->metadata->>estimated_duration_mins`).
`_metadata_field()` reads either shape — flat alias (list) or nested `content.metadata`
(detail, which still selects `*`) — so `get_lesson` populates the same two fields.
`_coerce_float()` handles `->>` returning TEXT. `LessonStatusResponse` gained both fields
as `| None`.

**AC-4 — production-breaking bug caught in review.** The first `_LIST_COLUMNS` named
`completed_at`. That column exists on **`lesson_jobs`**, not on `lessons`
(`20260611000000_initial_schema.sql`). Under `select("*")` naming it was harmless —
`lesson.get("completed_at")` simply returned `None` — but naming it explicitly makes
PostgREST reject the entire query with `42703`, so **`GET /lessons` would have failed for
every user on every request**. Every AC-4 test mocks Supabase and asserts the select
*string*, so none could catch it. Removed, and now guarded by
`test_list_columns_names_no_column_absent_from_the_lessons_table`, which parses
`_LIST_COLUMNS` and checks each referenced column against the set defined by the migrations.

**AC-4 — untrusted-JSONB hardening (review).** `content.metadata` is LLM-generated, and
`_metadata_field` returned it raw into typed Pydantic fields. A dict- or number-valued
`subject` raises `ValidationError`, which on the list path 500s the **entire page**, not one
card. Added `_coerce_str` (drops non-`str`, caps length) and made `_coerce_float` reject
non-finite values — `float("NaN")` and `float("1e400")` both *succeed*, and a bare
`NaN`/`Infinity` token is invalid JSON that throws in the browser's `JSON.parse`.

**AC-5 — expiry.** `_EMBEDDED_MEDIA_EXPIRY_S = 8 * 60 * 60`, threaded through
`_resolve_lesson_content`. `GET /api/media/signed-url` left dormant, and now genuinely
documented **in `media/router.py`** — the first pass put the note in `content/router.py`,
a different module from the endpoint it describes, while Task 5 was marked complete.

**Test verification.** Every guard in this story is mutation-proven, and the review round
found three that were not. Killed on re-check: tier stamp ignored on read; tier not stamped
on write; salvage disabled; salvage without re-stamping; non-dict item guard; non-dict value
guard; `isinstance(str)` on the recovered script; blank-script recovery; `completed_at`
re-added to the select; `list_lessons` attaching and signing content per row.

Three first-round tests were **not** doing their job:
- `test_list_lessons_still_never_attaches_content_or_signs_urls` (the Story 1-6 AC-7 guard)
  **survived** a mutation that made `list_lessons` attach and sign content for every row —
  its fixture had no `content` key, so the mutated branch never fired. `_LIST_ROW` now
  carries a realistic content dict, and the mutation is killed.
- The expiry assertions were **tautological** — they interpolate the same constant the
  source uses, so only `_EXP > 3600` had force, and `3601` satisfied it while defeating
  AC-5's rationale. Replaced with an explicit floor (`>= 4h`) and a ceiling (`<= 24h`),
  since an over-long window on a bearer capability is its own problem.
- `_coerce_float`'s except branch had **zero** coverage; a non-numeric metadata value would
  have raised out of `_row_to_status_response`.

`_make_list_supabase_mock` deliberately does **not** reuse `_make_supabase_mock`, whose
`table()` `side_effect` dispatch would make the select-string assertion unfalsifiable.

**AC-6 — regression.** Full suite after the review round: **32 failed, 1380 passed,
3 skipped** vs baseline `754786a` **32 failed, 1341 passed, 3 skipped** — **+39 passing,
zero new failures**, failure sets byte-identical under `diff`. All 32 are pre-existing in
`tests/test_dna_fusion.py`, `test_dna_growth.py`, `test_onboarding_content.py`,
`test_tutor_service.py` (Dev 3 / Dev 4 files, untouched here). `mypy`: **clean** on all three
touched source files. `ruff check`: the single E501 in `graph.py` is pre-existing at baseline
(same line, shifted). `ruff format`: `graph.py` carries 7 hunks of pre-existing drift at
baseline (leading BOM + older compact log-call style); my own lines conform, and I did not
sweep the unrelated hunks into this diff.

**Scope note, restated so it is not lost:** this does **not** fix Dev 2's visible
0:00-quiz-fires-instantly symptom. That needs the virtual playback clock in
`AudioTimeline.tsx` (`docs/dev2-narration-playback-handoff.md`). This story makes the
*package* correct.

**Not repaired by this change:** lessons already built with a blank script — `package_builder_node`
cache-hits and returns the stored dict verbatim. Those need their `package_builder` checkpoint cleared.

**AC-4 live verification — DONE 2026-07-28, against the real project.** Three read-only
stages, all passed:

1. **Syntax.** The full `_LIST_COLUMNS` select was executed with an impossible `user_id`
   filter, so PostgREST had to parse and validate the string while returning zero rows.
   Parsed cleanly — the path-alias syntax `subject:content->metadata->>subject` is correct.
2. **Aliasing.** A one-row probe returned exactly the six expected flat keys
   (`lesson_id`, `status`, `title`, `created_at`, `subject`, `estimated_duration_mins`)
   and **no `content` column** — Story 1-6 AC-7 holds against the real database, not just
   against a mock.
3. **Extraction.** On a `status='ready'` lesson with populated content, the aliased values
   were compared against the nested `content.metadata` ground truth the detail endpoint
   reads. They agree after coercion.

Stage 3 also **confirmed the asymmetry `_coerce_float` exists for**, which until now was
inferred from the PostgREST docs rather than observed: `estimated_duration_mins` comes back
as **`str`** on the list path (`->>` yields TEXT) and as **`float`** on the detail path.
Without `_coerce_float` the two endpoints would report different types for the same field.

Separately, the `completed_at` finding was confirmed empirically rather than only from the
migrations: selecting it from `lessons` returns
`{'code': '42703', 'message': 'column lessons.completed_at does not exist'}`, while
`lesson_jobs.completed_at` selects fine. The bug was real and would have taken
`GET /lessons` down for every user.

**Nothing is now open before merge.**

### File List

- `apps/api/app/modules/content/pipeline/graph.py`
- `apps/api/app/modules/content/router.py`
- `apps/api/tests/unit/test_content_router.py`
- `apps/api/tests/unit/test_package_builder_node.py`
- `apps/api/tests/unit/test_fan_out_state_keys.py`
- `apps/api/tests/unit/test_quiz_checkpoint_tier_stamp.py` — NEW (review round, AC-3)
- `apps/api/app/modules/media/router.py` — docstring only (AC-5 dormancy note)
- `docs/dev1-tracker.md`

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-28 | Story created. Folds in the tier-blind checkpoint finding from Story 2-28's Edge Case Hunter review (AC-3) and the signed-URL expiry gap (AC-5) alongside Dev 2's two remaining reported items. | Dev 1 |
| 2026-07-28 | All 6 tasks implemented. AC-3 narrowed to an `n_max`-only guard during implementation — the `n_min` half conflicts with Story 2-28 AC-8's keep-short-batches rule; residual gap documented. Status → ready-for-review. | Dev 1 |
| 2026-07-28 | **AC-4 live verification passed** against the real project (syntax / aliasing / value-extraction, all read-only). Confirmed the `->>`-yields-TEXT asymmetry that `_coerce_float` exists for, and confirmed the `completed_at` bug empirically (`42703`). Nothing open before merge; status → ready-for-review. | Dev 1 |
| 2026-07-28 | **6-layer adversarial review round.** Fixed one production-breaking bug (`completed_at` named in `_LIST_COLUMNS` is a `lesson_jobs` column, not a `lessons` one — `GET /lessons` would have 42703'd for every user). **AC-3 redesigned**: the shipped `n_max` heuristic could not catch the hazard AC-3 names, because stale caches are T2-sized and T1's `n_max` is 5 — replaced with a tier stamp in the checkpoint *value*, keys untouched. Added a salvage path so a rejected cache plus a failed regeneration cannot ship an empty quiz or loop-bill. Hardened `_index_by_segment_id` against non-dict entries and non-dict values, recovered scripts against non-`str` values, and added the blank-script recovery branch. Hardened `_metadata_field`/`_coerce_float` against untrusted JSONB (non-`str` subject, `NaN`/`Infinity`). Fixed three tests that passed for the wrong reason. AC-3's text amended in place; the mis-cited "2-28 AC-8" corrected to 3-28 AC-8. Task 5's `media/router.py` dormancy note finally written. Status → blocked-on-verification pending the live `select` check. | Dev 1 |
