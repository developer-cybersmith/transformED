---
baseline_commit: a14d660fe3c67a196ffad44880672f479d4fa6ac
---

# Story 2.18: Sanitize derived `segment_id` (unsanitized title corrupts the planner prompt)

Status: review

> **BUG / BLOCKER story.** Same how-to PDF as Story 2-16, failing on a *different* guard one line further down in `lesson_planner_node`. Story 2-16's fix works (8 sections, not 44; planner got 8 segments, not 10 — count-mismatch gone). This is a new, adjacent defect: a section title containing a newline gets baked verbatim into a `segment_id`, corrupting the single-line prompt list the LLM must echo back, tripping the `unknown segment_id(s)` guard.

## Story

As a **student (or dev) uploading a step-by-step how-to chapter**,
I want segment identifiers to be safe single-line tokens regardless of how messy the source heading text is,
so that the lesson planner's prompt list is not corrupted by an id containing a newline (or other whitespace/control characters).

Dev 1's content-pipeline module only. Reported by Dev 2 on 2026-07-22.

## Observed Failure (reproduction)

Same 105,248-char Task Manager how-to PDF. Phase 1 succeeded; RC-1 coalescing bounded to 8 sections; `lesson_planner` received 8 segments. It then failed:

```
lesson_planner returned unknown segment_id(s): ['section_0_1', 'section_1_13', ..., 'section_4_5.', ...]
```

One section title is literally `"5.\nJobs"` (a mis-detected numbered step with an embedded newline). `_derive_section_id` produces `section_4_5.\nJobs`.

## Root-Cause Analysis

`_derive_section_id` (`graph.py:1670-1681`):
```python
def _derive_section_id(section: dict[str, Any], index: int) -> str:
    title = section.get("title") or "section"
    return f"section_{index}_{title}"
```
The raw, unsanitized title is concatenated into the id — no whitespace collapsing, no length cap, no control-char stripping. Called by all 6 Phase 1 economy nodes (`graph.py:1887, 2016, 2183, 2307, 2475, 2615`), so this id is embedded into every `segment_summaries`/`quiz`/`glossary`/etc. entry.

The planner then builds one prompt line per segment (`graph.py:1099`):
```python
summaries_text = "\n".join(f"- segment_id={s['segment_id']}: {s['summary']}" for s in batch)
```
An id containing `\n` splits one logical list entry into two physical lines, corrupting the list structure the model must echo back 1:1 — so it guesses, and the echoed ids don't match the input set → `unknown segment_id(s)` guard raises (`slide_generator_node`'s prompt at `graph.py:1537` has the same single-line-per-segment shape and the same exposure).

**Same underlying cause as Story 2-16** (rule-based heading detection misfiring on numbered how-to steps → garbage "titles"), surfacing through a different sink (`segment_id` derivation → prompt) rather than the count-mismatch guard.

## Acceptance Criteria

1. **AC-1 — `segment_id` is always a safe single-TOKEN identifier.** `_derive_section_id` slugifies the title before embedding it: every run of characters outside `[A-Za-z0-9]` (whitespace, punctuation, control, unicode) collapses to a single `-`, trimmed, and the title portion is capped to `_SECTION_ID_TITLE_MAX`. The returned id contains no whitespace (`\n`/`\r`/`\t`/space) and no `:`/`=` (the prompt-line delimiters). A blank / whitespace-only / all-control / all-punctuation title falls back to `"section"`. Input is length-bounded before slugging (untrusted heading text).

7. **AC-7 — the derived id satisfies the storage-path validator (`_SAFE_SEGMENT_ID_RE`).** `_derive_section_id`'s output must match `^[A-Za-z0-9_-]+\Z`. **This closes a HIGH-severity latent bug the audit surfaced:** the id is embedded into Supabase Storage object paths (`{lesson_id}/{segment_id}.mp3`, `{lesson_id}/{slide_id}.png`) which `tts_node` (`graph.py:2974`) and `image_generator_node` (`graph.py:3219`) validate against `_SAFE_SEGMENT_ID_RE`. The previous space-preserving id (`section_0_The Water Cycle`) **failed that gate for virtually every real multi-word heading**, silently degrading server-side TTS audio (`audio_url=""`) and slide images (`image_url=None`) to fallback while the lesson still "completed". Slugifying to `[A-Za-z0-9-]` makes the id pass, restoring audio + images. A regression test cross-checks `_derive_section_id` output against `_SAFE_SEGMENT_ID_RE` for realistic titles.
2. **AC-2 — Uniqueness per section is preserved.** The `section_{index}_` prefix still guarantees uniqueness even when two different titles collapse/truncate to the same string (the Story 2-1 collision concern the function exists for). No two sections in one chapter can produce the same id.
3. **AC-3 — The planner prompt line count equals the segment count.** For any set of segment_summaries whose ids come from `_derive_section_id` (including messy titles with embedded newlines), `summaries_text.split("\n")` has exactly one line per segment — the corruption that tripped the guard cannot recur.
4. **AC-4 — No behavior change for well-formed titles beyond the bounded length.** A clean title like `"Introduction"` still yields `section_{index}_Introduction`; only messy titles are altered. Existing Phase 1 / planner / package-builder tests pass unmodified.
5. **AC-5 — Coverage.** New unit tests: newline/tab/CR collapse; control-char stripping; length cap; blank/whitespace-only fallback; uniqueness under collapse-collision; the exact `"5.\nJobs"` repro; and a prompt-line-count assertion proving AC-3 end-to-end from `_derive_section_id` through the planner's `summaries_text` construction.
6. **AC-6 — Constraints preserved.** No hardcoded models; providers abstraction untouched; degrade-not-fabricate intact; `segment_id` remains stable within a run (idempotency/checkpoint keys unaffected for a given section+index).

## Tasks / Subtasks

- [x] Task 1: Sanitizer (AC-1, AC-2) — ✓ 2026-07-22 — added `_SECTION_ID_TITLE_MAX=60`; `_derive_section_id` now collapses whitespace (`" ".join(str(title).split())`), drops non-printables, caps to 60, falls back to `"section"`; `section_{index}_` prefix retained for uniqueness.
- [x] Task 2: Tests (AC-3, AC-5) — ✓ 2026-07-22 — `tests/unit/test_derive_section_id.py` (18 cases incl. the `"5.\nJobs"` repro and the planner prompt line-count assertion).
- [x] Task 3: Regression — ✓ 2026-07-22 — 489 passed / 1 skipped; `mypy app` = 0; ruff check + format clean.

## Senior Developer Review (AI) — review + systemic audit, 2026-07-22

5-layer review of the fix + a systemic Dev1↔Dev2 audit (25 agents). The review **caught that the first version of this fix was incomplete** and the audit found the same root cause firing as a HIGH latent bug — both now addressed by the slugify upgrade:

- **[Med → fixed] Security: single-LINE ≠ single-TOKEN.** Collapsing whitespace to a *space* left `section_4_5. Jobs`; a space (or a `:` from titles like `1. Step: do X`) still lets a whitespace-tokenizing consumer truncate the id to `section_4_5.` — reproducing the guard trip. Upgraded to slugify to `[A-Za-z0-9-]`.
- **[High → fixed] Derive/validate charset mismatch (audit).** `_derive_section_id` allowed spaces but `_SAFE_SEGMENT_ID_RE` (tts/image storage-path gate) rejects them → every real multi-word-titled lesson silently lost server-side audio + images. The slug fix aligns producer and consumer (AC-7 + cross-check test).
- **[Med → fixed] Test coverage: prompt-line-count test was a format replica; slide_generator sink uncovered.** Added a **real-node** `lesson_planner_node` regression test (exercises `graph.py:1099`) + a slide_generator-sink line test (Dev 2's request for coverage in the node files).
- **[Low → fixed] perf: whole untrusted title processed before cap.** Input now length-bounded before slug.
- **[Low → added] boundary (60/61), all-control fallback, storage-charset cross-check** tests.

**Dev 2's cross-check (independent manual read) — all incorporated:** slide_generator identical sink (covered by the chokepoint fix + sink test); uniqueness is index-based (`graph.py:3684` enumerate) — confirmed collision-safe; coalesce keeps survivor title verbatim; the dead `sec["id"]` re-sequencing in `coalesce_sections` (noted as a follow-up cleanup).

**Deferred to follow-up stories (found by the audit, NOT this bug's scope):** narration `timestamps=[]` breaking player slide-sync (High); `title`/`summary` newline in the planner/slide prompt lines — the *other half* of the same line (Med); partial Phase-1 per-section drop in package_builder (Med); slide_generator wholesale-reject on one bad slide count (Med); teachback prompt/scoring drift (Med). See the audit report.

## Dev Agent Record — Completion Notes

Single-chokepoint fix in `_derive_section_id` (fixes all 6 Phase 1 nodes and both prompt sinks at once). Sanitize = collapse all whitespace → single space, drop non-printables, cap 60, fallback `"section"`. Uniqueness stays index-based (AC-2). No call-site changes; package-builder grouping keys stay consistent because every consumer reads the derived id, never re-derives.

**Verification (post review+audit upgrade):** 498 passed / 1 skipped (0 regressions); `mypy app` = 0; ruff clean. Fix upgraded from whitespace-collapse to **slugify `[A-Za-z0-9-]`** — closes the reported newline bug, the echo-token issue, AND the HIGH storage-path charset mismatch (audio/images). Baseline `main` @ `a14d660`.

**File List:**
- `apps/api/app/modules/content/pipeline/graph.py` — `_SECTION_ID_TITLE_MAX` + sanitized `_derive_section_id` (MODIFIED)
- `apps/api/tests/unit/test_derive_section_id.py` — new tests (NEW)
- `docs/stories/2-18-sanitize-derived-segment-id.md` — this story (NEW)

## Dev Notes

- `_derive_section_id` is the single chokepoint — fixing it here fixes all 6 Phase 1 nodes and both downstream prompt sinks (planner `:1099`, slide_generator `:1537`) at once. Do NOT sanitize at each call site.
- Keep the `section_{index}_` prefix and the `index`-based uniqueness guarantee (AC-2) — do not derive uniqueness from the (now-sanitized, possibly-colliding) title.
- `segment_id` is also a package-builder grouping key (`graph.py:3383-3430`) and is matched against `plan_segment_ids`; sanitizing consistently at the one derivation point keeps producer and consumer aligned (all consumers read the derived id, never re-derive it).
- This is a targeted hotfix; the deeper heading-misdetection cause remains tracked by Story 2-16/2-17. Sanitizing the id is correct defense-in-depth regardless of upstream heading quality.

### Constraints (CLAUDE.md)
`settings.llm_*` only; providers abstraction; degrade-not-fabricate; planner input is summaries only; no banned deps.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Bug story from Dev 2's second blocker report (newline-in-segment_id). Adjacent to Story 2-16; same root cause, different sink. | Dev 1 (BMAD create-story) |

## Dev Agent Record

_(to be completed during `dev-story`)_
