# Story 2.34: Remove the inert LLM structure validation (S1-6)

Status: review

## Story

As Dev 1 (content pipeline owner),
I want `structure_node` to stop making an LLM call whose result is arithmetically guaranteed to be discarded for every real document,
so that we stop paying for a safety net that has never once fired, and stop presenting it as one.

**Source:** `DEV1-FIX-PLAN.md` scope item 6 (S1-6). Decision 2026-07-29: delete the dead call now, and treat "replace font heuristics with docling" as a **Sprint 3** architecture item.

## The defect — this is arithmetic, not a quality judgement

`structure_node` builds rule-based sections from font metadata + regex, then calls the LLM to
"validate" them. Two constants make that call dead on arrival:

```python
# _build_structure_prompt — the LLM only ever SEES the first 6,000 chars
text_preview = raw_text[:6000] + ("..." if len(raw_text) > 6000 else "")

# ...but its output is only ACCEPTED if it covers 90% of the WHOLE document
llm_total = sum(len(s.body or "") for s in result.sections)
if llm_total < 0.9 * len(raw_text):
    # reject, keep rule-based
```

The LLM can only describe what it was shown, so `llm_total` ≲ 6,000. The guard therefore
passes only when `6000 >= 0.9 * len(raw_text)`, i.e. **`len(raw_text) <= ~6,667 characters`**.

A textbook chapter is 30,000–100,000 characters. So for every real document:

1. We make the call — **and pay for it**
2. The LLM answers about the first 6,000 characters
3. The guard rejects it
4. The rule-based sections win, exactly as if the call had never happened

The check only ever succeeds on documents too small to need checking. Both halves are
individually defensible — the 6,000-char window bounds prompt cost, the 90% guard prevents
silent data loss — but together they are mutually exclusive.

## What this story does NOT do

It does **not** improve structure detection. After this change we still detect headings with:

```python
if font.get("size", 0) >= threshold and font.get("bold", False):   # Strategy 1
for match in _TOPIC_RE.finditer(raw_text):                          # Strategy 2
```

That is a real limitation and it is being recorded, not fixed here — see Sprint 3 below.
Removing an inert call changes nothing about detection quality; it removes cost and a false
impression of safety.

## Acceptance Criteria

1. **AC-1 — `structure_node` makes no LLM call.** No `get_llm_provider` / `complete_structured`
   in the node. Assert with a spy that a full `structure_node` run performs **zero** provider
   calls, on both a short (<6,667 char) and a long (>6,667 char) input — the short case matters
   because that is the only input the old code could ever have accepted, so it is where a
   partial deletion would hide.
2. **AC-2 — Rule-based sections are unchanged.** For a fixed input, the sections produced after
   this change are **identical** to those the rule-based path produced before it. Pin with a
   direct comparison, not a shape check — "still returns sections" would pass even if the
   detection changed.
3. **AC-3 — Dead code is fully removed, not orphaned.** `_STRUCTURE_SYSTEM_PROMPT`,
   `_build_structure_prompt`, and the `DocumentStructure` response model must be deleted if
   they have no other caller, or explicitly kept with a comment saying why. No unreferenced
   prompt scaffolding left behind for someone to "reconnect" later.
4. **AC-4 — The empty-`raw_text` guard survives in intent.** The old code skipped the LLM when
   `raw_text` was empty, because the `< 90%` proxy is vacuously false for an empty string and
   hallucinated sections would have been adopted. With no LLM there is nothing to hallucinate,
   but the node must still behave sanely on empty input rather than crash — assert it.
5. **AC-5 — The limitation is recorded where someone will find it.** A comment at the top of
   `structure_node` stating that detection is font+regex only, that LLM validation was removed
   as provably inert, and pointing at the Sprint 3 docling direction. Same in
   `docs/dev1-tracker.md` against S1-6.
6. **AC-6 — No regression.** Full suite shows exactly the pre-existing failures. `ruff check`,
   `ruff format --check` and `mypy app` produce no findings that did not already exist at
   baseline, measured **repo-wide**.

## Tasks / Subtasks

- [x] Task 1 (AC-1, AC-2, AC-4): remove the LLM block; tests for zero provider calls, identical sections, empty input.
- [x] Task 2 (AC-3): remove or explicitly justify the orphaned prompt/model scaffolding.
- [x] Task 3 (AC-5): record the limitation in code and in the tracker.
- [x] Task 4 (AC-6): full suite, lint (repo-wide), types.

## Dev Agent Record

### Completion Notes

**Baseline captured BEFORE the deletion**, per the Dev Notes — otherwise AC-2 is
unfalsifiable. `tests/fixtures/structure_rule_based_baseline.json` holds the 5 sections the
pre-deletion code produced on a 9,274-char fixture with the LLM mocked to return output the
90% guard rejects, i.e. exactly the real-document case. The capture run also demonstrated the
defect live: `LLM sections cover 0/9274 chars (< 90%) — rejecting LLM output` with
`provider called: 1x`. Post-deletion sections compare **byte-identical** to that file.

**Credit where due: this was already known.** `graph.py` carried a
`KNOWN LIMITATION (Story 2-16 RC-2, deferred to Story 2-17)` comment stating the 6,000-char
window vs 90%-coverage mismatch precisely. Story 2-34 is the decision to act on it, not the
discovery of it — the story and the new test file both say so.

**AC-1's short-document case is the one that matters.** Under the old code, a document below
~6,667 chars was the *only* input whose LLM output could be adopted, so it is exactly where a
partial deletion would hide: strip the call from the long path only and every real-document
test still passes. Both sides of the threshold are asserted.

**AC-3 — what went and what stayed.** `_STRUCTURE_SYSTEM_PROMPT` and `_build_structure_prompt`
were graph.py-private and orphaned: **removed**. So were the two imports that existed only for
that block (`get_llm_provider`, `DocumentStructure`) — an unused provider import inside a node
is an invitation to wire it back up. `DocumentStructure` itself **stays**: it lives in
`app.schemas`, is exported in `__all__`, and is referenced by three test modules, so it is not
structure_node's to delete. That reason is made executable by
`test_document_structure_schema_is_deliberately_retained`, so a future cleanup does not remove
it on the assumption it was ours.

**Five existing tests converted, not deleted.** They asserted behaviour that can no longer
occur. Per the Dev Notes they now assert its absence, and each records what it used to pin:
- `test_structure_guard_adopts_faithful_llm_output`, `..._at_exact_90_percent_boundary` and
  `..._duplicated_bodies_pass_length_proxy` → consolidated into
  `test_structure_never_adopts_llm_output`. Its docstring preserves the Tier-3 #18 finding —
  the guard was a pure *length* proxy, so bodies duplicating the first half twice totalled
  100% of `len(raw_text)` while covering 50% of the content. **That hole is still unsolved**;
  it simply no longer has a guard to be a hole in. Anyone reinstating an LLM pass needs to
  know that.
- `test_structure_node_happy_path` → same field contract with `chunk_node`, now asserting zero
  LLM calls.
- `test_structure_node_coalesces_adopted_llm_output` → the adopted-output scenario is
  unreachable; coalescing on the surviving path is already covered by
  `test_structure_node_coalesces_oversegmented_rule_based` and `test_coalesce_sections.py`.
  Replaced with a source-level assertion that the scenario is genuinely gone rather than
  quietly untested.

**What this does NOT do, recorded in the node itself.** Detection is still font-size +
boldness thresholds plus a regex. The new comment block in `structure_node` lists the concrete
failure modes rather than hand-waving: a non-bold heading is invisible; one shared font size
gives false positives; multi-column layouts scramble reading order; and on **scanned pages
there is no font metadata at all** — `font_blocks` comes from `pdftext` — so the font strategy
collapses entirely and only the regex survives. It also carries the Sprint 3 docling direction
with both blockers (the 206–216s/41-page measurement vs `extract_timeout_cap_s = 1500`, and
the §16 four-dev review for a locked-stack change).

**AC-6 — regression, measured repo-wide.**

| Gate | `main` (`3900ae6`) | This branch |
|---|---|---|
| `ruff check .` | 31 | **31** |
| `ruff format --check .` | 10 files | **10 files** |
| `mypy app` | 24 | **24** |
| `pytest tests/unit tests/integration` | 741 passed | **745 passed** |
| full suite | 22 F / 1433 P | **22 F / 1437 P** |

Failure set byte-identical to `main` under `diff`. Interim note: removing the block orphaned
two imports and pushed `ruff check` to 33; caught and fixed before commit.

### File List

- `apps/api/app/modules/content/pipeline/graph.py`
- `apps/api/tests/unit/test_structure_no_llm.py` — NEW
- `apps/api/tests/fixtures/structure_rule_based_baseline.json` — NEW (pre-deletion baseline)
- `apps/api/tests/unit/test_structure_node.py`
- `apps/api/tests/unit/test_pipeline_tier1.py`
- `docs/dev1-tracker.md`

## Dev Notes

- **Capture the before-state for AC-2 first.** Run `structure_node` on a fixture input on the
  current code, record the resulting sections, and assert the post-change output matches. Doing
  it the other way round makes AC-2 unfalsifiable.
- **Check for other callers before deleting.** `DocumentStructure` may be referenced by the
  shared schema or by tests. If it is exported from `packages/shared/*`, **stop** — that is the
  §16 four-dev gate and out of scope here.
- **Existing tests will reference the removed path.** `tests/unit/test_structure_node.py` almost
  certainly patches `get_llm_provider` or asserts on LLM-adopted sections. Those assertions are
  now testing behaviour that cannot occur; update them to assert the *absence* rather than
  deleting them silently.
- **Do not tune the heuristics while you are in here.** Any change to `detect_headings` is a
  detection-quality change and belongs with the Sprint 3 work, where it can be measured.

### Sprint 3 direction — record, do not build

Structure detection should move from font-size heuristics to **docling's document hierarchy**.
Docling is *already* a dependency (`docling>=2.0.0`, Apache 2.0) and already runs in
`extract_subprocess.py` — but only for **table-bearing page runs** (Story 2-0b). It performs ML
layout analysis and emits typed section headers with levels, which is what the font-size
thresholds are currently approximating.

Two things must be settled before that work starts, and neither belongs in this story:

1. **Time cost.** `config.py` records page-scoped docling measured **206–216s** on a 41-page
   table-bearing PDF. Full-document docling on a 200–300 page textbook must fit inside
   `extract_timeout_cap_s = 1500`. That is a measurement, and it is the question that decides
   whether the direction is viable at all.
2. **§16 / locked-stack review.** CLAUDE.md pins the PDF stack. Changing what docling is used
   for is a stack-scope change and needs the 4-developer review.

Note also that Strategy 1 collapses entirely on scanned PDFs — `font_blocks` comes from
`pdftext`, so after OCR there is no font metadata and only the regex survives. Docling handles
that case; the current heuristics do not.

### Project Structure Notes

Touches `apps/api/app/modules/content/pipeline/graph.py`, its structure-node tests, and
`docs/dev1-tracker.md`. **No** `packages/shared/*`, **no** `supabase/migrations/*` — §16 gate
not triggered. Zero `apps/web/**`.

### Branching

`sprint2/dev1-s1-6-drop-inert-llm-validation`, based on `main`. Overlaps `graph.py` with PR #105
(which touches `providers/llm/openai.py` only) — no conflict expected, but rebase if #105 lands first.

### References

- [Source: DEV1-FIX-PLAN.md — scope item 6, S1-6]
- [Source: CLAUDE.md — locked PDF stack; §16 frozen contracts]
- [Source: apps/api/app/config.py — the 206–216s docling measurement]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-29 | Implemented. LLM block and its orphaned scaffolding removed; rule-based output pinned byte-identical to a baseline captured before the deletion. Five existing tests converted to assert the absence, preserving the Tier-3 #18 length-proxy finding. Gates identical to main. Status → review. | Dev 1 |
| 2026-07-29 | Story created. Removes an LLM call that is arithmetically always discarded for real documents (6,000-char prompt window vs a 90%-of-whole-document acceptance guard). Explicitly does not improve detection; records the docling direction for Sprint 3 with its blocking time-cost question and §16 review requirement. | Dev 1 |
