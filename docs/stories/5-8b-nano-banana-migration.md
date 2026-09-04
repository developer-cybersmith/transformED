---
title: "Nano Banana Migration — Gemini Primary, GPT Image 2 Fallback (S4-8)"
status: in-progress
baseline_commit: ad52c2e
owners: [Dev 1]
sprint: 4
---

# Story 5-8b — Nano Banana Migration (Gemini primary, GPT Image 2 fallback)

## Problem Statement

`docs/DEFECT-REGISTER.md`'s D121 records that Imagen 4 Fast — the current fallback tier
of `image_generator_node`'s image-generation chain — was shut down by Google on
2026-08-17. Every call to it now hard-errors; repeated failures trip its circuit
breaker and the slide silently degrades to text-only (no crash, no visible error,
per `image_generator_node`'s own AC-11 per-slide isolation contract).

D121 named three replacement options and left the decision `OPEN, Owner: TBD`. A
doc-only decision story (`fc5948b`, branch `sprint4/s4-8-imagen-fallback`, never
merged) named Option 1 — Gemini "Nano Banana" — as the team's research-favored
choice, but explicitly deferred the actual provider order and forbade any code
change on that branch, requiring a separate follow-on implementation story. This
is that story.

The final decision recorded here differs from that draft in one respect: **Gemini
"Nano Banana" becomes the PRIMARY provider, GPT Image 2 becomes the FALLBACK** —
the reverse of the draft's order (which kept GPT Image 2 primary and only replaced
the dead fallback tier). Rationale: Gemini's image-generation quality was the
stated reason for wanting it in the primary position, not merely as a backstop.

## User Story

As the platform generating slide images for real lessons, I want a working,
non-dead fallback chain — Gemini "Nano Banana" first, GPT Image 2 second — so
that slide images are actually produced instead of silently degrading to
text-only on every call that reaches the (currently dead) second tier.

## Acceptance Criteria

- **AC1** — D121 is updated from `OPEN` to `FIXED-GUARDED`: decision recorded as
  Gemini "Nano Banana" primary / GPT Image 2 fallback, with owner and rationale
  (not `TBD`). `CLAUDE.md`'s Locked Technology Stack Image row is updated to match
  in the same docs-only commit — before any code changes.
- **AC2** — `apps/api/app/providers/image/nano_banana.py` implements the existing
  `ImageProvider` abstract interface (`app/providers/base.py`), following the same
  structural convention as `imagen.py` (raw `httpx` against Google's API, since
  Nano Banana is not exposed via an SDK path this codebase already depends on):
  `guard_breaker`/`is_circuit_open` (circuit breaker), `@with_retry(max_attempts=2)`,
  a Langfuse trace, module-level `COST_PER_IMAGE`. Request shape is Gemini's
  `generateContent` with `response_modalities=["IMAGE"]`; response is inline
  base64, decoded to the same `data:image/...;base64,...` URI shape the rest of
  the pipeline already expects.
- **AC3** — `_generate_image_with_fallback` (`graph.py`) tries `NanoBananaProvider`
  first, `OpenAIImageProvider` second, and returns `(None, "text-only")` if both
  fail — `ImagenProvider` and `imagen.py` are deleted entirely, not merely
  unwired.
- **AC4** — The per-image cost accounting branch (`graph.py`, currently keyed on
  `provider_used in {"gpt_image", "imagen"}`) is updated for the new pair
  (`"nano_banana"`, `"gpt_image"`); `imagen.py`'s `COST_PER_IMAGE` constant is
  removed along with the file.
- **AC5** — A new regression test explicitly pins the fallback ORDER (patch both
  providers with distinct successful payloads, assert Gemini's payload is the one
  that reaches the slide) — closing a real, confirmed gap: no existing test in
  `test_image_generator_node.py` asserts which provider is tried first, only which
  one succeeds when the other fails.
- **AC6** — A new AST-based guard test (`test_provider_call_site_guard.py`, same
  `ast.walk` + parent-chain technique as `test_unbounded_queries.py`) asserts
  `NanoBananaProvider(` and `OpenAIImageProvider(` are each instantiated from
  exactly one call site in `graph.py` — `_generate_image_with_fallback` — so an
  accidental second wiring point fails CI, not just review.
- **AC7** — Every test in `test_image_providers.py`/`test_image_generator_node.py`
  that referenced `ImagenProvider`/`imagen.py` is either deleted (if the assertion
  no longer applies to a two-tier Gemini/GPT chain) or rewritten against the new
  pair (if the underlying property — e.g. "both tiers failing degrades to
  text-only, never raises" — still needs coverage).
- **AC8** — Full `tests/unit/` suite (not just touched files) passes with zero
  regressions; `ruff format --check`, `ruff check`, `mypy` clean.
- **AC9** — Diff is scoped to exactly: this story file, `docs/DEFECT-REGISTER.md`
  (D121 + one new entry for the Scale & Load gap named below), `CLAUDE.md`,
  `apps/api/app/providers/image/nano_banana.py` (new),
  `apps/api/app/providers/image/imagen.py` (deleted),
  `apps/api/app/modules/content/pipeline/graph.py`,
  `apps/api/app/config.py` (comment only — `google_api_key` field already exists),
  `apps/api/tests/unit/test_image_providers.py`,
  `apps/api/tests/unit/test_image_generator_node.py`,
  `apps/api/tests/unit/test_provider_call_site_guard.py` (new). Nothing under
  `apps/web`, no other pipeline node, no other provider file.
- **AC10** — Existing guard tests for `graph.py` (`tests/unit/test_node_return_shape.py`,
  `tests/unit/test_unbounded_queries.py`) still pass — `image_generator_node`'s
  return shape and query-boundedness are unchanged by this story.

## Dev Notes

- `ImageProvider` (`app/providers/base.py:94-116`) has one abstract method:
  `async def generate(self, prompt: str, size: str = "1024x1024") -> str`.
- Fallback driver is `_generate_image_with_fallback` (`graph.py:4294-4340`) — two
  hardcoded sequential `try/except` blocks, not config-driven. Reorder = swap
  which provider is instantiated first; delete the Imagen block entirely rather
  than leaving it dead.
- `settings.google_api_key` (`config.py:55-62`) already exists and already backs
  `ImagenProvider` — reused as-is for `NanoBananaProvider`, only its description
  comment needs updating (it currently documents itself as Imagen-specific).
- Cost: Nano Banana ~$0.067/image vs Imagen's $0.02–0.06 and GPT Image 2's ~$0.05
  — a real increase on the new primary tier, worth calling out plainly in the
  D121 update rather than burying it.
- Test-mocking pattern: mirror `test_image_providers.py`'s **Imagen** style
  (`patch("httpx.AsyncClient")`, `mock_client_cls.return_value.__aenter__.return_value`)
  for Nano Banana, not the OpenAI-SDK style — both are raw-HTTP against Google.
  Provider modules import `is_circuit_open` etc. at module level, so tests must
  patch the CONSUMER module's reference (`app.providers.image.nano_banana.is_circuit_open`),
  not the defining module — the established, occasionally-inconsistent convention
  this file's own docstring already flags.

## Scale & Load

**Q1 — Unit of work and range:**
One unit = one slide's image generation attempt, up to two provider calls (Gemini,
then GPT Image 2 on failure). Range: 1–2 HTTP calls per slide, `_IMAGE_GENERATION_CONCURRENCY
= 3` slides in flight at once per lesson (unchanged by this story — D132's existing
semaphore). A typical lesson has 6–12 slides; largest observed is bounded by
`settings.max_chapter_pages` upstream, not by this node.

**Q2 — Fixed budgets that meet variable inputs:**
- `check_ceiling(lesson_id)` gates entry before any provider call — unchanged.
- Each provider's own `@with_retry(max_attempts=2)` bounds retries per call.
- Circuit breaker (`guard_breaker`) bounds repeated-failure cost per provider,
  independently, unchanged in shape (only the participating providers change).
- Cost per image increases (Gemini ~$0.067 vs GPT Image 2's ~$0.05) — this
  raises the effective ceiling-breach point for a lesson with many slides;
  explicitly named in the D121 update, not silently absorbed.
- `nano_banana.py`'s HTTP timeout (review finding, fixed in this story, not
  deferred): the first draft copied the deleted `imagen.py`'s bare
  `httpx.AsyncClient(timeout=30.0)` verbatim. A bare float applies to ALL
  httpx timeout categories including `connect=`, replacing the codebase's
  established 5s connect guard with 30s — tolerable for Imagen's occasional
  fallback role, not for this file's new PRIMARY role (hit on every slide).
  Fixed: a new `settings.google_image_request_timeout_s` field (mirroring
  `openai_image_request_timeout_s`, default 180.0) plus an explicit
  `httpx.Timeout(..., connect=5.0)`, matching `openai_image.py`'s existing
  convention exactly. Guarded by
  `test_nano_banana_uses_an_explicit_timeout_never_a_bare_float`.

**Q3 — Scope of limits:**
`_IMAGE_GENERATION_CONCURRENCY` is per-lesson (module constant, unchanged).
`max_lesson_cost_usd` is per-lesson (existing `settings` field, unchanged).
Circuit-breaker state is per-provider, process-wide (existing `guard_breaker` key
scheme, unchanged — Gemini and GPT Image 2 each get their own breaker key, same
as Imagen and GPT Image 2 do today).

**Q4 — Unbounded reads/writes:**
None introduced. No new Supabase reads/writes in this story beyond what
`image_generator_node` already does (cost read/write, storage upload) — the
provider swap is a pure in-memory/network-call change.

**Q5 — Inherited caps re-derived:**
`_IMAGE_GENERATION_CONCURRENCY = 3` is NOT re-derived here — it was sized for the
old GPT Image 2 / Imagen pair's latency profile. Nano Banana's real latency is
unknown until measured against the live API; if materially different, this cap
should be revisited in a follow-up, named explicitly rather than silently
inherited as correct.

**Q6 — Check-then-act safety:**
**Known, pre-existing gap (not introduced or worsened by this story, but
surfaced here and given its own register ID since the doc-only 5-8 story flagged
it without registering it):** `check_ceiling` (read) and `accumulate_cost` (write)
are not atomic — under `_IMAGE_GENERATION_CONCURRENCY = 3` concurrent slides, up
to `(3-1) × cost_per_image` can be spent past the ceiling before it is observed,
since all three slides can read the ceiling as "not yet breached" before any of
them writes. This applies identically regardless of which providers are in the
chain. Registered as **D140** (see `docs/DEFECT-REGISTER.md`) — acknowledged,
not silently fixed as a side effect of this story, since the fix (a lock or an
atomic Redis compare-and-set) is a separate, independently-scoped change.
