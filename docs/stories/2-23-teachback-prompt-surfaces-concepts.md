---
baseline_commit: 52ff4df76a580a45b540f33d569206977a6672e3
---

# Story 2.23: teach-back prompt surfaces the concepts it is graded against

Status: review

> **BUG (MED, producer/consumer drift), from the 2026-07-22 audit.** `package_builder` writes a placeholder `teachback_prompt` = "In your own words, explain what you learned about {title}." The Dev3 teach-back scorer (`assessment/service.py:440`) ignores that prompt and grades the student's answer against the segment's **jargon terms** (`key_concepts = [j["term"] for j in segment.jargon]`). The student answers an open-ended question but is scored on specific concepts the prompt never surfaces → a correct, complete answer can be marked incomplete, depressing the CES teach-back contribution.

## Root cause & fix

Dev1 owns `package_builder` and the `teachback_prompt` field (an explicitly provisional placeholder). Align the shown prompt with the scoring basis by **surfacing the segment's key concepts** (its jargon terms — the exact `key_concepts` the scorer uses) in the prompt, when present. No change to Dev3's scorer. When the segment has no jargon, keep the generic prompt.

## Acceptance Criteria

1. **AC-1** — when a segment has jargon entries, `teachback_prompt` names those terms (the scorer's `key_concepts`), e.g. "In your own words, explain {title}. Try to cover: {term1}, {term2}, …". Terms are taken from the same `jargon` list the package emits (and the scorer reads), in order, deduplicated consistently with the glossary dedup already applied.
2. **AC-2** — when a segment has no jargon, the prompt is the existing generic form (no trailing "cover:" clause).
3. **AC-3** — the prompt remains a plain single-line string (schema `str`); terms are joined readably; no newlines injected (reuse the single-line discipline).
4. **AC-4** — no change to the assessment/Dev3 module; the alignment is producer-side only.
5. **AC-5** — Coverage: with-jargon prompt lists the terms; no-jargon prompt is the generic form. Existing package tests updated only where they asserted the exact old prompt string.
6. **AC-6** — constraints preserved (one-discipline rule — no reach into assessment tables; no hardcoded models).

## Tasks / Subtasks
- [ ] Task 1: build `teachback_prompt` from `title` + the segment's jargon terms (surface concepts when present).
- [ ] Task 2: Tests (AC-5). RED first.
- [ ] Task 3: Regression green.

## Dev Notes
- `teachback_prompt` built at `graph.py:3533`; the segment's jargon at `jargon_entries` (already computed in the loop). Scorer basis: `assessment/service.py:440-441` (`topic=title`, `key_concepts=[j["term"] for j in jargon]`). Align to that list exactly.
- Keep it a provisional-but-aligned placeholder (the audit's verify softened this to a rubric/UX gap, not a hard bug) — surfacing the graded terms is the minimal producer-side alignment.

## Change Log
| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Bug story from the Dev1↔Dev2 audit (MED/PLAUSIBLE: shown prompt vs graded concepts drift). | Dev 1 |

## Dev Agent Record
**Completed 2026-07-22.** `_build_teachback_prompt(title, jargon_entries)` surfaces the segment's jargon terms (the Dev3 scorer's `key_concepts`) when present; generic form otherwise; single-line via `_single_line`. No Dev3 change. Tests: terms surfaced with-jargon, generic without. 537 passed; mypy 0; ruff clean.

**File List:** `apps/api/app/modules/content/pipeline/graph.py`; test files updated per story; this story.
