# Story 3-56 — S3-5: Pipeline cost attribution in Langfuse

**Branch:** `sprint3/s3-5-langfuse-cost-attribution` (from `main`).
**Owner:** Dev 1.
**Tracker source:** `docs/dev1-tracker.md` S3-5 — "All pipeline nodes — each Langfuse span must
include `token_cost_usd` in metadata. AC: Langfuse dashboard shows cost breakdown per node per
lesson; no node missing cost attribution."

## Context

This gap was first named during Story 2-6's review (`docs/stories/2-6-lesson-planner-node.md`)
and during this session's own earlier Langfuse skill self-audit, and deliberately deferred to
S3-5 rather than fixed piecemeal per-node.

Investigated fresh, not re-derived from memory, before writing this story — read all five
provider files that carry real per-call cost (`providers/llm/openai.py`,
`providers/embeddings/openai.py`, `providers/tts/sarvam.py`, `providers/tts/azure.py`,
`providers/image/imagen.py`, `providers/image/openai_image.py` — six files, one of the LLM file's
two methods counted separately below) plus `providers/avatar/heygen.py`.

**The real, current shape of the gap is narrower than the tracker's generic phrasing suggests:**

- **4 of 6 already correct.** `sarvam.py`, `azure.py` (TTS), `imagen.py`, `openai_image.py` each
  already call `generation.update(..., cost_details={"input": cost})` right where they compute
  cost — this evidently landed during the earlier Langfuse self-audit this session. Langfuse's
  `cost_details` is the SDK's own first-class cost field (distinct from the generic `metadata`
  dict), which is what actually drives the dashboard's cost breakdown — not a custom
  `token_cost_usd` metadata key as the tracker's literal wording implies. Extending the existing
  pattern, not inventing a new one, per the project's own binding rule 6 (`DEFECT-REGISTER.md`)
  against introducing parallel patterns.
- **2 real gaps, both in `providers/llm/openai.py`.** `_complete_inner` (backing `complete()`)
  and `_complete_structured_inner` (backing `complete_structured()`) both call
  `_maybe_accumulate_cost(model, prompt_tokens, completion_tokens)`, which computes a real dollar
  `cost` from `_COST_PER_1K` and passes it to `cost_tracker.accumulate_cost()` — but that `cost`
  value is never written back to the `generation` span. The span only ever receives
  `usage_details` (raw token counts), never `cost_details` (the dollar figure). Cost accumulation
  and the $3.00 ceiling are correct and unaffected by this gap — only the Langfuse-visible trace
  is missing the number.
- **1 real gap, `providers/embeddings/openai.py`.** Same shape: `_maybe_accumulate_cost` computes
  `cost` from `_EMBED_COST_PER_1K_USD` and accumulates it, but never reaches the span.
- **1 legitimately out of scope.** `providers/avatar/heygen.py` has no Langfuse tracing and no
  cost accumulation at all, matching CLAUDE.md's own description ("HeyGen cached intro/outro,
  ~$0/lesson, no live HeyGen per lesson") — there is no per-lesson cost here to attribute.

## The fix

Three call sites, same shape at each: give `_maybe_accumulate_cost` the `generation` object (it
doesn't currently receive it) and have it call `generation.update(cost_details=...)` right after
it computes cost — the exact point the dollar value already exists, matching where the other 4
providers already do this.

1. **`providers/llm/openai.py`** — `_maybe_accumulate_cost(self, model, input_tokens,
   output_tokens)` gains a `generation: Any | None = None` keyword param. The single combined
   `cost` float becomes two: `input_cost = safe_input / 1000 * pricing["input"]` and
   `output_cost = safe_output / 1000 * pricing["output"]` (the sum passed to `accumulate_cost`
   is unchanged — `input_cost + output_cost`). When `generation is not None`, call
   `_safe_trace(lambda: generation.update(cost_details={"input": input_cost, "output":
   output_cost}))`. Two keys, not one — unlike TTS/image (a single undifferentiated per-call
   cost), LLM billing genuinely splits by token type, and `usage_details` on the same span
   already carries that same `input`/`output` split — `cost_details` should mirror it, which is
   *more* accurate than the existing single-key pattern, not a departure from it.
   `_complete_inner` and `_complete_structured_inner` both pass their own `generation` local
   through at the existing call site (`await self._maybe_accumulate_cost(model, prompt_tokens,
   completion_tokens, generation=generation)`).

2. **`providers/embeddings/openai.py`** — same shape, single `cost_details={"input": cost}` key
   (embeddings have no output-token cost, matching the file's own existing `usage_details={
   "input": total_tokens, "output": 0}`).

## What this does NOT do

- Does not touch `cost_tracker.py`, `accumulate_cost()`, or `check_ceiling()` — the real
  accumulation and the $3.00 ceiling are already correct and untouched; this is a tracing-only
  change.
- Does not touch any of the 4 providers that already call `cost_details` correctly.
- Does not touch `heygen.py` — no per-lesson cost exists there to attribute.
- Does not add a new `token_cost_usd` metadata key — uses Langfuse's existing native
  `cost_details` field instead, since that is what the SDK/dashboard actually reads for cost
  breakdown, and 4 of 6 providers already establish that as the pattern.
- Does not touch `docs/DEFECT-REGISTER.md` or `docs/dev1-tracker.md` beyond marking this task
  done — no new defect is being registered, this closes a gap already named in Story 2-6's
  review.

## Scale & Load

1. **Unit of work & range.** One `generation.update()` call per provider call, already happening
   for every LLM/embedding call in the pipeline (Phase 1's 6 parallel nodes, Phase 2's 2
   sequential nodes, embeddings at ingestion). This change adds one additional keyword argument
   (`cost_details`) to calls that already exist — no new call, no new range.
2. **Fixed budgets vs variable input.** N/A — this is an observability write, not a budget. The
   real $3.00/lesson ceiling is enforced by `cost_tracker.check_ceiling()`, unaffected by this
   change; a value of $0.00 in `cost_details` (e.g., zero tokens from a degenerate response) is
   valid data, not an error state, and is not clamped or rejected here.
3. **Scope of the limit.** N/A — no limit introduced.
4. **Unbounded reads/writes.** N/A — no new read or write path; `generation` is the same
   already-open Langfuse observation each call site already holds a reference to.
5. **Inherited caps re-derived.** N/A — no cap involved.
6. **Concurrency.** N/A — `generation` is a per-call-stack-frame local object (one HTTP request,
   one `generation.update()`), never shared across concurrent calls; no check-then-act sequence
   introduced.

Every Langfuse call in this change already goes through `_safe_trace`/`safe_trace` (the
established best-effort wrapper — a Langfuse outage must never fail the pipeline), matching the
existing pattern at every other `generation.update()` call site in these files.

## Verification

- RED-GREEN via the Edit tool for each of the 3 call sites: add/extend a unit test asserting
  `generation.update` was called with `cost_details` containing the expected dollar figures
  (computed the same way `_maybe_accumulate_cost` computes them, so the test would catch a wrong
  formula, not just presence/absence of the key). Temporarily remove the new `cost_details` line,
  confirm the new/extended assertion fails, restore, confirm green.
- Run the full existing test files for `test_llm_openai.py` (or wherever the current
  `providers/llm/openai.py` tests live), `test_embeddings.py`/`test_embeddings_openai.py` (exact
  file names confirmed during implementation) — confirm zero pre-existing tests broke. The
  `generation.update` mock calls in existing tests assert specific kwargs
  (`usage_details=...`), not full-call-equality, so adding a new kwarg is not expected to require
  changes elsewhere — verified directly during implementation, not assumed.
- Full repo-wide regression (`pytest -q` from `apps/api`) — diff against the current baseline,
  confirm zero new failures.
- `ruff check` / `ruff format --check` / `mypy app` clean on both touched files.
- Cannot verify the AC's literal "Langfuse dashboard shows cost breakdown" visually — no real
  `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` exist yet in this environment (same limitation
  noted in this session's earlier Langfuse skill self-audit). Verification here is at the
  code/mock level: `cost_details` is sent with the correct computed values at every real
  per-call-cost site. The dashboard-level check remains the explicit deferred step once real
  credentials land, consistent with how the earlier Langfuse audit reported this same gap.

## Review Findings

Retroactive 8-layer BMAD review (2026-08-14) — the required 6-agent gate was skipped before the
original merge; run after the fact against `main`.

- [x] [Review][Patch] The two-call pattern (`generation.update(output=..., usage_details=...)`
  then a second `generation.update(cost_details=...)`) assumed the SDK merges fields across
  calls rather than the second call clearing the first's data — never verified. Checked directly
  against the real installed SDK (`langfuse/_client/attributes.py`): `create_generation_attributes`
  filters `None`-valued kwargs before `set_attributes()`, which only sets given keys, never clears
  omitted ones — confirmed safe. Added a premise test pinning this so a future SDK version that
  changes it fails here, not in production.
  [`test_langfuse_sdk_contract.py::test_update_call_with_only_cost_details_does_not_null_out_other_fields`]
- [x] [Review][Patch] No `# MOCK-CONTRACT:` note on the new mock-only tests — added, naming
  `test_langfuse_sdk_contract.py::test_generation_has_update_with_provider_kwargs` as the
  real-dependency premise test these mocks stand in for. [`test_s3_5_langfuse_cost_attribution.py`]
- [ ] [Review][Dismiss] AC's literal "token_cost_usd in metadata" wording vs. the actual
  `cost_details` implementation — a deliberate, disclosed, justified technical choice (Langfuse's
  native cost field, matching the other 4 providers' established pattern), not a silent deviation.
