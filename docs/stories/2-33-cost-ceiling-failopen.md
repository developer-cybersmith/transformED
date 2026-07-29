# Story 2.33: Close the cost-ceiling fail-open on unpriced models

Status: review

## Story

As Dev 1 (pipeline + provider abstraction owner),
I want an LLM call on a model with no pricing entry to be **charged at a conservative rate and loudly flagged**, instead of silently costing nothing,
so that the $3.00/lesson ceiling cannot be switched off by the one operation the architecture is designed to make trivial — swapping a model via an env var.

**Source:** `DEV1-FIX-PLAN.md` scope item 10 (S1-7 / S2-15 fail-opens), confirmed still live on `main` 2026-07-29.

## The defect

`app/providers/llm/openai.py:_maybe_accumulate_cost`:

```python
pricing = _COST_PER_1K.get(model)
if pricing is None:
    logger.warning("No pricing data for model '%s' — cost not tracked", model)
    return          # <-- accumulate_cost is never called
```

`accumulate_cost` is never reached, so the lesson's running total stays at `$0.00`,
and `check_ceiling` — which compares that total against `max_lesson_cost_usd` — never
fires. **An unpriced model spends without limit.**

The price table has exactly two entries:

```python
_COST_PER_1K = {
    "gpt-4o":      {"input": 0.005,    "output": 0.015},
    "gpt-4o-mini": {"input": 0.000150, "output": 0.000600},
}
```

CLAUDE.md's own Per-Task Model Allocation table names the evaluation candidates as
**GPT-4o, Claude 3.5 Sonnet, o1-mini, Gemini 2.0 Flash**. Three of the four are absent
from the price table. CLAUDE.md also states: *"Never hardcode model strings — always use
`settings.llm_*` aliases. Swapping models is an env var change only."* So running the
model-evaluation sprint the PRD asks for is exactly what disables cost tracking, and the
only signal is one `WARNING` line.

**This is the only cost path with the defect.** The others are already correct and are the
precedent this story follows:

| Path | Unknown-cost behaviour | |
|---|---|---|
| `embeddings/openai.py` | single flat `_EMBED_COST_PER_1K_USD`, no lookup | safe |
| `image/openai_image.py` | `COST_PER_IMAGE.get(size, 0.02)` — **has a default** | safe |
| `tts_node` / `image_generator_node` | compute then `accumulate_cost` unconditionally | safe |
| **`llm/openai.py`** | `if pricing is None: return` | **fails open** |

## Acceptance Criteria

1. **AC-1 — An unpriced model is still charged.** `_maybe_accumulate_cost` never returns
   without calling `accumulate_cost` when `self._lesson_id` is set and token counts are
   present. Prove it: call with a model absent from `_COST_PER_1K` and assert
   `accumulate_cost` was awaited with a value `> 0`.
2. **AC-2 — The fallback rate is conservative, and derived, not hardcoded.** Use the most
   expensive known input/output rate in `_COST_PER_1K`, computed from the table itself so
   it cannot drift when a pricier model is added. Over-charging an unpriced model is the
   safe direction: it makes the ceiling fire *earlier*, never later.
3. **AC-3 — It is loud.** Log at **ERROR**, not WARNING, naming the model and stating that
   a fallback rate was applied. `main.py` wires Sentry's default
   `LoggingIntegration(event_level=ERROR)`, so this becomes a Sentry issue — an unpriced
   model in production is an operational defect, not a debug detail.
4. **AC-4 — The lesson still completes.** Do **not** raise on an unpriced model. PRD §14 is
   "downshift, complete the lesson, flag in admin" — never abort. Hard-failing would also
   make the model-evaluation workflow the PRD mandates impossible. Assert a full call
   succeeds and returns its content with an unpriced model.
5. **AC-5 — The ceiling actually fires on an unpriced model.** The end-to-end property, not
   just the accumulate call: with a lesson already near `max_lesson_cost_usd`, an unpriced
   model must push it over and raise `CostCeilingError`. This is the assertion that would
   have caught the original bug; AC-1 alone would not.
6. **AC-6 — Standing guard tests** (`DEV1-FIX-PLAN` item 10). A test that fails if any
   future edit reintroduces an early `return` before `accumulate_cost` on any branch of
   `_maybe_accumulate_cost` other than the deliberate `lesson_id is None` case.
7. **AC-7 — No regression.** Full suite shows exactly the pre-existing failures. `ruff
   check`, `ruff format --check` and `mypy app` produce no findings that did not already
   exist at baseline — measured **repo-wide**, not only on touched files (2026-07-29
   lesson: the touched-files-only wording is how 78 repo-wide errors went unnoticed).

## Tasks / Subtasks

- [x] Task 1 (AC-1, AC-2, AC-3, AC-4): conservative derived fallback + ERROR log; tests for each.
- [x] Task 2 (AC-5): end-to-end ceiling test with an unpriced model.
- [x] Task 3 (AC-6): standing guard test against a re-introduced early return.
- [x] Task 4 (AC-7): full suite, lint (repo-wide), types.

## Dev Agent Record

### Completion Notes

**The fix.** `_maybe_accumulate_cost` no longer returns on an unpriced model. It substitutes
a pricing dict derived from the table — `max(p["input"] ...)` / `max(p["output"] ...)` — logs
at ERROR naming the model and the applied rate, and falls through to the normal
`accumulate_cost` → `check_ceiling` path. The `self._lesson_id is None` guard is the sole
remaining early return, exactly as AC-6 requires.

**Why conservative-and-derived, not a literal.** Over-charging makes the ceiling fire earlier,
never later, so an unpriced model can only ever be *safer* than reality. Deriving it from the
table means the fallback stays the most expensive rate automatically when a pricier model is
priced later; `test_fallback_is_at_least_every_known_model_rate` asserts that as a property
over the whole table rather than against a fixed number.

**Why ERROR and not abort.** `main.py` wires Sentry's default
`LoggingIntegration(event_level=ERROR)`, so ERROR surfaces as an issue while WARNING did not —
which is why the original went unnoticed. Aborting was rejected: PRD §14 is "downshift …
complete lesson, flag in admin", and hard-failing would make the model-evaluation workflow
CLAUDE.md mandates impossible to run at all.

**AC-5 is the assertion that would have caught the original.** AC-1 (accumulate is called)
is necessary but not sufficient — the useful property is that the ceiling can still *fire*.
`test_ceiling_fires_on_an_unpriced_model` drives a lesson already over budget through an
unpriced model and asserts `CostCeilingError`.

**AC-6 guard is structural, not behavioural.** A behavioural test only catches the cases it
thinks to enumerate; the original defect was a `return` statement. The guard AST-parses
`_maybe_accumulate_cost`, asserts exactly **one** `Return` node, asserts its enclosing `if`
tests `_lesson_id`, and asserts `accumulate_cost` is still referenced. Reinstating the
original bypass fails it immediately.

**Mutation-proven.** Three mutations, all killed: restoring the original `return` (6 tests
red), using `min` instead of `max` for the fallback rate (2 red), and downgrading the log to
WARNING (1 red).

**Embed truncation — dropped, with the measurement recorded in code.** Per the 2026-07-29
English-only decision. `graph.py` now carries the measured `cl100k_base` ratios (English 6.0,
Hindi 1.06, Tamil 0.71 chars/token) and states plainly that the current cut yields ~5,300
tokens for English but ~30,100 for Hindi and ~45,200 for Tamil against an 8,000 cap. It also
records why the branch is near-unreachable today — chunks target 512 tokens and `token_count`
is always a real tokenizer count — so a future reader does not re-litigate it, and knows
exactly what to fix when an Indic language lands.

**AC-7 — regression, measured repo-wide.** Deliberately not "touched files only": that
wording is how 78 repo-wide ruff errors went unnoticed until 2026-07-29.

| Gate | `main` (`3900ae6`) | This branch |
|---|---|---|
| `ruff check .` | 31 | **31** |
| `ruff format --check .` | 10 files | **10 files** |
| `mypy app` | 24 | **24** |
| `pytest tests/unit tests/integration` (CI's set) | 741 passed | **750 passed** |
| full suite | 22 F / 1433 P | **22 F / 1442 P** |

Failure set byte-identical to `main` under `diff`. +9 tests, zero regressions.

### File List

- `apps/api/app/providers/llm/openai.py`
- `apps/api/app/modules/content/pipeline/graph.py` — comment only (embed-truncation note)
- `apps/api/tests/unit/test_cost_ceiling_failopen.py` — NEW

## Dev Notes

- **`_lesson_id is None` must keep its early return.** That is the "no lesson context"
  case (e.g. a provider constructed outside a pipeline run) and is legitimate. Only the
  *pricing* early-return is the defect. The guard test in AC-6 must allow the first and
  reject the second.
- **Derive the fallback, do not hardcode it.** `max(p["input"] for p in _COST_PER_1K.values())`
  and likewise for output. A literal would silently become non-conservative the day a more
  expensive model is priced.
- **Do not "fix" this by adding more models to the table.** That treats the symptom. The
  table will always lag whatever is set in the env; the point is that a miss must fail
  *closed*, not open.
- **`accumulate_cost` uses Redis `INCRBYFLOAT`** on `cost:{lesson_id}` with a 24h TTL —
  unchanged by this story. Tests should patch `app.core.cost_tracker.accumulate_cost` /
  `check_ceiling` rather than standing up Redis.
- `CostCeilingError` already exists (added in Story 2-32) and is a `RuntimeError` subclass
  so `content_pipeline_job`'s `"cost ceiling" in str(exc)` branch keeps working. Reuse it.

### Explicitly OUT of scope

- **Byte-naive embed truncation** (`graph.py`, `text[: _MAX_EMBED_INPUT_TOKENS * 4]`), the
  other half of `DEV1-FIX-PLAN` item 10. **Dropped by decision 2026-07-29: English only for
  now.** Measured ratios are 6.0 chars/token (English), 1.06 (Hindi), 0.71 (Tamil) — so the
  `~4 chars/token` constant is *conservative* for English and only dangerous for Indic
  scripts. It is additionally near-unreachable: chunks target **512 tokens** against an
  **8,000** cap, and `token_count` is always set from a real `cl100k_base` count, so the
  `len(text)//4` fallback and the truncation branch effectively never execute. Leave a code
  comment recording the measured ratios so whoever adds Hindi finds it. **Do not fix it here.**
- Adding models to `_COST_PER_1K` — see Dev Notes.
- Expanding `check_ceiling` coverage to more nodes (Story 2-32 established Phase 1 is
  already gated at fan-out).

### Project Structure Notes

Touches `apps/api/app/providers/llm/openai.py` and unit tests, plus a comment-only edit in
`apps/api/app/modules/content/pipeline/graph.py`. **No** `packages/shared/*`, **no**
`supabase/migrations/*` — §16 four-dev gate not triggered. Zero `apps/web/**`.

### Branching

`sprint2/dev1-cost-ceiling-failopen`, based on `main` (`3900ae6`). No overlap with any open PR.

### References

- [Source: DEV1-FIX-PLAN.md — scope item 10, S1-7 / S2-15 fail-opens]
- [Source: CLAUDE.md §14 — "Cost ceiling: $3.00/lesson — downshift ... complete lesson, flag in admin"]
- [Source: CLAUDE.md Per-Task Model Allocation — "Never hardcode model strings ... env var change only"]
- [Source: docs/stories/2-32-provider-retry-classification.md — `CostCeilingError`]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-29 | Implemented. Unpriced models now charged at the most expensive derived rate, logged at ERROR, lesson still completes. Structural AST guard added so a re-introduced early return fails immediately. 3 mutations killed. Repo-wide gates identical to main. Status → review. | Dev 1 |
| 2026-07-29 | Story created. Closes the last live fail-open from the fix plan's item 10; its sibling (embed truncation) explicitly dropped for English-only, with the measurement recorded. | Dev 1 |
