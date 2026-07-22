---
baseline_commit: 52ff4df76a580a45b540f33d569206977a6672e3
---

# Story 2.20: Sanitize free-text (title/summary) in single-line LLM prompt lists

Status: ready-for-dev

> **BUG (MED), from the 2026-07-22 audit.** Story 2-18 hardened the `segment_id` half of the `- segment_id={id}: {summary}` prompt line, but the free-text halves (`summary` in `lesson_planner`, `title`+`summary` in `slide_generator`) are still interpolated **unsanitized**. A newline in a summary (natural: a bulleted ≤100-word summary passed verbatim by `_cap_words`; or adversarial: PDF prompt-injection) splits one logical list entry into two, injecting a spurious `- segment_id=...` line → the LLM mis-echoes ids → the same `count/unknown/duplicate` guards trip → the sequential PREMIUM node hard-fails after all Phase-1 spend.

## Acceptance Criteria

1. **AC-1** — a `_single_line(text)` helper (`" ".join(str(text).split())`) collapses every whitespace run (incl. `\n`/`\r`/`\t`) to a single space. It is applied to the free-text fields interpolated into single-line prompt entries: `summary` in `lesson_planner_node._run_planner_batch`'s `summaries_text` (`graph.py:1099`), and `title` + `summary` in `slide_generator_node`'s `segments_text` (`graph.py:1537`).
2. **AC-2** — for any set of segments whose `summary`/`title` contain newlines, the built prompt has exactly one physical line per segment.
3. **AC-3** — content is preserved (readable), not slugified — only whitespace is collapsed; a clean summary is unchanged apart from internal whitespace normalization.
4. **AC-4** — existing planner/slide tests pass unmodified; new tests assert the one-line-per-segment property for newline-bearing summaries/titles through the real nodes.
5. **AC-5** — constraints preserved (no hardcoded models; summaries-only planner input; degrade-not-fabricate).

## Tasks / Subtasks
- [ ] Task 1: `_single_line` helper + apply at both prompt-build sites.
- [ ] Task 2: Tests (real-node one-line-per-segment for newline summaries/titles).
- [ ] Task 3: Regression green.

## Dev Notes
- Mirror Story 2-18's chokepoint discipline: sanitize where the text is interpolated into the line, not at every producer. `_cap_words` returns ≤100-word summaries verbatim (newlines survive) — confirmed at `graph.py` `summarise_segment` path.
- Do NOT slugify (would destroy the readable text the LLM needs) — only collapse whitespace.

## Change Log
| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Bug story from the Dev1↔Dev2 audit (MED: unsanitized free-text half of the prompt line 2-18 fixed for ids). | Dev 1 |

## Dev Agent Record
_(to be completed during dev-story)_
