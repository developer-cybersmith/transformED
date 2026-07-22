---
baseline_commit: cdc984eb126c1eb9e4c3711200284b1129923935
---

# Story 2.17: Boundary-Only LLM Structure Validation (revive the dead structure_node LLM path)

Status: backlog

> Follow-up to **Story 2-16** (RC-2). Non-blocking correctness debt — filed so it is not lost. Do NOT start until 2-16 is merged.

## Problem

`structure_node`'s LLM structure-validation branch is effectively **dead code** for any real chapter. `_build_structure_prompt` (`graph.py:447-455`) shows the LLM only `raw_text[:6000]`; the adoption guard (`graph.py:530-540`) requires the LLM's section bodies to cover `≥ 0.9 × len(raw_text)`. For any document longer than `6000 / 0.9 ≈ 6,666 chars`, the LLM (having seen ≤6000 chars) can never satisfy the guard, so its output is always rejected and rule-based detection always wins. Confirmed by 5-agent audit (2026-07-22) and by the production log `LLM sections cover 5958/105248 chars (< 90%)`.

## Why not a one-liner

- Feeding full `raw_text` into the prompt → violates hierarchical-processing (full-chapter single call) and blows up `llm_mini` token cost; verbatim echo of large bodies is itself lossy. **Rejected.**
- Comparing `llm_total` against `min(len(raw_text), 6000)` → makes the guard pass by *accepting* LLM output covering only the first 6000 chars, silently discarding everything after. Reintroduces the exact data-loss the guard exists to prevent. **Rejected.**

## Proposed approach (boundary-only)

Change the LLM's job from "return section bodies" to "return heading **boundaries**" — an internal Pydantic shape of `[{title, level, char_offset}]` only (not the frozen `DocumentStructure` bodies). Reconstruct bodies **deterministically in Python** by reusing `build_section_bodies` over the LLM-approved offsets. The adoption guard shifts from body-coverage to **boundary sanity** (offsets monotonic, within `[0, len(raw_text)]`, spanning the doc). Coverage becomes lossless *by construction* — Python always owns the verbatim text; the LLM never holds it. Keep `settings.llm_mini` via `get_llm_provider`; no new model alias; no direct provider calls.

## Acceptance Criteria (draft)

1. LLM structure call returns boundary offsets only; Python slices bodies from full `raw_text`.
2. Adoption guard validates boundary sanity, not body-length coverage; no `raw_text` truncation in the prompt drives data loss.
3. A >6,666-char chapter can now legitimately adopt LLM boundaries when they are better than rule-based — proven by a test (the coverage gap noted in 2-16's audit: no test currently exercises the `<90%` rejection branch; add both branches).
4. Interoperates with Story 2-16's `coalesce_sections` (coalescing runs after adoption, on whichever boundary set wins).
5. No hardcoded models; degrade-not-fabricate preserved; hierarchical processing preserved.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Filed as deferred follow-up from Story 2-16 (RC-2). | Dev 1 |
