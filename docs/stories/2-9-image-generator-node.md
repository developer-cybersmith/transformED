---
baseline_commit: 64803af372bfd4cde37fe40943eed395404eaf64
---

# Story 2.9: `image_generator` Node — GPT Image 1 Mini → Imagen 4 Fast → Text-Only Fallback (S2-10)

Status: done

## Story

As a **student whose chapter now has real slides and narration** (Story 2-7/2-8),
I want each slide to get an illustrative image (with a graceful text-only fallback if every image provider is unavailable),
so that the lesson player has real visuals to show — instead of the current empty placeholder — while never blocking lesson completion if image generation fails or the cost ceiling is near.

This story implements the REAL body of `image_generator_node` — tracker task **S2-10** in `docs/dev1-tracker.md`, Epic 1's Node 14. The node function and its place in the graph already exist as a stub (`graph.add_edge("tts_node", "image_generator")` is already wired) — this story replaces the stub body and adds two new image provider implementations.

**Critical correction to the stub's own TODO comment:** the current stub's TODO says `DalleImageProvider(lesson_id).generate(slide_image_prompt)` — **DALL-E 3 is BANNED** (CLAUDE.md: "DALL-E 3 DEAD (shut down May 2026)"). The existing `apps/api/app/providers/image/dalle.py` (a full, unused `DalleImageProvider` implementation, structurally sound but wired to a dead model) must be deleted as part of this story — same situation Story 2-8 already resolved once for ElevenLabs, do not leave a second banned-provider landmine in the repo.

**This story bakes in every lesson learned from Story 2-8's code review, from the start, rather than repeating the same review cycle:** every per-slide operation is wrapped in its own `try/except` from the first implementation (not added after a review catches it), the storage upload uses `upsert: true` from the first implementation, `slide_id` is validated before use in a storage path from the first implementation, and a provider's returned value is checked for truthiness (not just non-`None`-ness) from the first implementation. Cite Story 2-8's Dev Notes/Review Findings directly in this story's own Dev Notes rather than silently re-deriving the same fixes.

## Acceptance Criteria

1. **Input is `state["slides"]` only** — each slide's `slide_id`, `title`, and `bullets` (produced by Story 2-7's `slide_generator_node`, nested `{segment_id, data}` shape) drive image prompt construction. Never re-reads `state["lesson_plan"]`/`state["segment_summaries"]`/`state["narration_scripts"]` — this node is image-only.
2. **Fallback chain: GPT Image 1 Mini → Imagen 4 Fast → text-only, in that order, per slide** — try GPT Image 1 Mini first; on any failure (provider error, circuit open, non-2xx response, empty/falsy return) try Imagen 4 Fast; on Imagen failure too, fall back to `image_url = None` (text-only — the player shows the slide's title/bullets with no illustration). **The pipeline must NEVER fail over images** — a slide that exhausts both providers still produces a valid `{slide_id, image_url: None}` entry, never an unhandled exception, matching CLAUDE.md's explicit "never fail the pipeline over images" rule.
3. **Cost-ceiling pre-check, proactive (not just reactive)** — before attempting either provider for a given slide, check `cost_tracker.check_ceiling(lesson_id)`; if already over ceiling, skip straight to `image_url = None` for that slide (and every subsequent slide in this run) with zero provider calls — matching CLAUDE.md's explicit "Fall back to `image_url=None` (text-only) if cost ceiling is near — never fail the pipeline over images" instruction for this node specifically (a proactive check `tts_node` does not have, since TTS has no equivalent documented cost-ceiling-awareness requirement).
4. **New `OpenAIImageProvider`** (`apps/api/app/providers/image/openai_image.py`) implementing `ImageProvider.generate()` — real call via the existing `AsyncOpenAI` client (already a project dependency, used by `OpenAILLMProvider`) to GPT Image 1 Mini (`model="gpt-image-1-mini"`). GPT Image models return base64-encoded image data (`b64_json`), not a CDN URL like DALL-E did — encode this as a `data:image/png;base64,...` URI so the return value still satisfies `ImageProvider.generate()`'s `-> str` (URL-shaped) contract; `image_generator_node`'s own bytes-fetching helper (AC-6) decodes `data:` URIs directly instead of doing an HTTP GET.
5. **New `ImagenProvider`** (`apps/api/app/providers/image/imagen.py`) implementing `ImageProvider.generate()` — real HTTP call via `httpx.AsyncClient` to Google's Generative Language API Imagen 4 Fast endpoint (`https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-fast-generate-001:predict`), authenticated with `settings.google_api_key`. Returns a base64 `data:` URI (Imagen's REST response is also base64-encoded, not a URL) for the same reason as AC-4.
6. **`dalle.py` deleted, not just unwired** — `apps/api/app/providers/image/dalle.py` removed entirely. Confirm nothing imports it before deleting (grep first) — mirror Story 2-8's Task 1 exactly.
7. **Successful images uploaded to the private `lesson-images` Supabase Storage bucket** — image bytes (decoded from whichever provider's `data:` URI succeeded) uploaded to `lesson-images` at a deterministic path `{lesson_id}/{slide_id}.png`, with `upsert: true` (Story 2-8's own review-round fix, applied here from the start — see Dev Notes). `slide_images` entries store that **storage path** as `image_url` (not a public URL — `lesson-images` is private per CLAUDE.md §18).
8. **Output shape matches the existing `PipelineState.slide_images` field exactly** — `state["slide_images"]` becomes `list[{"slide_id": str, "image_url": str | None}]`, matching the field's pre-existing comment (`# [{slide_id, image_url}]`) — a flat list, NOT the nested `{segment_id, data}` shape Stories 2-1/2-7/2-8 use, since `slide_id` alone is a unique-enough correlation key for `package_builder` (S2-11) and the stub's own comment already committed to this flat shape.
9. **Circuit breaker wired per provider** — `is_circuit_open("gpt_image")` before every GPT Image 1 Mini call, `is_circuit_open("imagen")` before every Imagen call (independent keys, same reasoning as Story 2-8 AC-8).
10. **Cost tracked** — image generation cost is included in `cost_tracker.accumulate_cost()` for every successful call (GPT Image 1 Mini or Imagen). Text-only (both-failed or over-ceiling) slides incur zero cost.
11. **Per-slide failure isolation, baked in from the start (Story 2-8 review lesson applied proactively)** — every slide's ENTIRE processing (validation, provider fallback, download/decode, upload, assembly) is wrapped in its own `try/except Exception`; any failure anywhere degrades JUST that slide to `image_url: None`, never crashing the whole node. This directly incorporates Story 2-8's Review Findings' single biggest fix (per-segment try/except) as a first-pass requirement, not a follow-up patch.
12. **`slide_id` validated before use in a storage path** — reject/sanitize any `slide_id` that isn't a safe path component (same `_SAFE_SEGMENT_ID_RE`-style guard Story 2-8's review round added; reuse or mirror that pattern here from the start).
13. **Idempotency checkpoint, Phase-A style** (same pattern as the three sibling premium/media nodes) — read `lesson_jobs.node_outputs`; `"image_generator"` key present → return cached, skip all generation. On success (including the empty-input case, per Story 2-8's own review-round fix, applied here from the start), write the checkpoint.
14. **Empty `state["slides"]` does NOT raise** — mirrors `tts_node`'s AC-11 divergence from the Phase 2 premium nodes' stricter empty-input guards; an empty `slides` list produces an empty `slide_images` list and a warning log, not an exception (defensive symmetry, even though `slide_generator_node`'s own guards should make this case unreachable in practice).
15. All existing tests continue to pass unmodified.

## Tasks / Subtasks

- [ ] Task 1: Delete the banned DALL-E 3 provider (AC: 6)
  - [x] 1.1 Grepped (case-insensitive) `apps/api/app`/`apps/api/tests` — confirmed only 2 references: `graph.py`'s stub TODO (removed with the stub body, Task 4) and `providers/image/dalle.py` itself. No test file referenced it.
  - [x] 1.2 Deleted `apps/api/app/providers/image/dalle.py`. Full suite re-ran clean immediately after (333/333) before any other change.

- [x] Task 2: `OpenAIImageProvider` (AC: 4, 9, 10)
  - [x] 2.1 Created `apps/api/app/providers/image/openai_image.py`.
  - [x] 2.2 `is_circuit_open("gpt_image")` check first; `@with_retry(max_attempts=2)`; calls `images.generate(model="gpt-image-1-mini", ...)`; extracts `response.data[0].b64_json`, falls back to `.url` if present, raises `ValueError` if neither is present.
  - [x] 2.3 Cost tracking mirrors the old `DalleImageProvider._maybe_accumulate_cost` pattern (per-lesson_id, price-by-size lookup); documented placeholder rate.

- [x] Task 3: `ImagenProvider` (AC: 5, 9, 10)
  - [x] 3.1 Created `apps/api/app/providers/image/imagen.py`.
  - [x] 3.2 `is_circuit_open("imagen")` check first; `@with_retry(max_attempts=2)`; real `httpx.AsyncClient` POST with `?key={api_key}` query-param auth; extracts `predictions[0].bytesBase64Encoded`, raises `ValueError` if absent.
  - [x] 3.3 Cost tracking mirrors Task 2.3's pattern, documented placeholder rate.

- [x] Task 4: Replace the `image_generator_node` stub body (AC: 1, 2, 3, 7, 8, 11, 12, 13, 14)
  - [x] 4.1 Idempotency checkpoint read added, mirroring `tts_node` exactly.
  - [x] 4.2 Empty `slides` list is handled without a special-cased early branch — the per-slide `for` loop naturally iterates zero times, and the checkpoint write (Task 4.6) always runs unconditionally after the loop, so the empty case gets `slide_images=[]` written to the checkpoint for free, without needing Story 2-8's separate empty-branch fix.
  - [x] 4.3 Every slide's ENTIRE body wrapped in `try/except Exception` FROM THE START (not patched in after review, per this story's explicit design goal); `slide_id` validated via the same `_SAFE_SEGMENT_ID_RE` pattern Story 2-8 introduced (reused directly, not reinvented under a new name); cost ceiling checked via `check_ceiling(lesson_id)` before any provider call.
  - [x] 4.4 Successful provider call decodes the `data:` URI, uploads with `upsert: true` from the start, calls `accumulate_cost()`.
  - [x] 4.5 Any exception anywhere in a slide's processing degrades that slide to `image_url: None` — verified this covers malformed entries, unsafe slide_ids, and provider errors alike.
  - [x] 4.6 Checkpoint write added (unconditional, covers both empty and non-empty cases — see 4.2).
  - [x] 4.7 Returns `{**state, "slide_images": slide_images_out, "progress_pct": 93.0}`.
  - [x] 4.8 Stub's DALL-E/upload TODO comments removed. `PipelineState.slide_images` comment confirmed still accurate, no correction needed.

- [x] Task 5: Tests (AC: all) — two new files, 15 tests total
  - [x] 5.1 `test_image_providers.py` (5 tests): OpenAI success/circuit-open/missing-b64-and-url; Imagen success/circuit-open.
  - [x] 5.2 `test_image_generator_node.py` (10 tests): happy path, GPT-Image-fails-Imagen-succeeds fallback, both-fail-text-only (no exception/upload/cost), cost-ceiling-over (zero provider calls), malformed slide entry (degrades that slide only), unsafe slide_id (degrades, no upload), empty slides (checkpoint written, no exception), idempotency cache-hit, checkpoint write on success, AC-1 prompt-isolation regression guard.
  - [x] 5.3 Full regression: 348/348 passes (333 baseline + 15 new), 0 modifications to existing test files needed.

## Dev Notes

### The node and its place in the graph already exist — this story replaces the stub body + adds 2 provider files (mirrors Story 2-8's shape exactly)

Current stub (`graph.py`, quoted in full):
```python
async def image_generator_node(state: PipelineState) -> PipelineState:
    """Node 14: Generate illustrative images for slides that require visuals."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] image_generator_node", lesson_id)
    await _update_job_progress(lesson_id, 88.0, "image_generator")

    # TODO: DalleImageProvider(lesson_id).generate(slide_image_prompt)
    # TODO: download URL and upload to Supabase Storage (lesson-images bucket)
    slide_images: list[dict[str, Any]] = []
    return {**state, "slide_images": slide_images, "progress_pct": 93.0}
```
Graph wiring already has `graph.add_edge("tts_node", "image_generator")` and `graph.add_edge("image_generator", "package_builder")` — nothing about topology changes. `package_builder_node` (S2-11) remains a stub for a separate story; it already reads `state.get("slide_images", [])` directly into its (also-stub) flat assembly, so this story's output shape needs no further translation for that stub to keep working.

### Story 2-8's code review is this story's spec, not just precedent — apply its fixes from the start

Story 2-8 (`tts_node`) shipped WITHOUT per-segment exception isolation, storage `upsert`, ID-path validation, or return-value truthiness checks — a 3-layer adversarial review caught all four as real gaps and they were patched in afterward (see `docs/stories/2-8-tts-node.md`'s Review Findings). This story's ACs (2, 3, 7, 11, 12) bake those same four fixes in as Acceptance Criteria from the outset. Read `tts_node`'s CURRENT (post-patch) implementation in `graph.py` directly before writing this node — it is the reference implementation for the per-slide `try/except` shape, the `_SAFE_SEGMENT_ID_RE`-style validation pattern (rename/reuse for `slide_id`), and the `upsert: true` storage option.

### `ImageProvider` ABC (already exists, `app/providers/base.py`)

```python
class ImageProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, size: str = "1024x1024") -> str:
        """... Returns: A URL pointing to the generated image. May be a temporary
        CDN URL that should be downloaded and re-uploaded to Supabase Storage."""
```
The docstring's "temporary CDN URL" framing describes DALL-E's behavior specifically — GPT Image 1 Mini and Imagen 4 Fast both return base64-encoded image data directly (no CDN URL to download from), so both new providers return a `data:image/png;base64,...` URI instead, which still satisfies the `-> str` contract. `image_generator_node`'s bytes-fetching step must therefore decode a `data:` URI (via `base64.b64decode` on the substring after the comma) rather than doing an HTTP GET — there is no live URL to fetch in this story, unlike `tts_node`'s bytes-are-returned-directly design (TTS providers return raw bytes; image providers here return an encoded string).

### `DalleImageProvider`'s structure is still a good template for the pieces that don't involve the banned model

`apps/api/app/providers/image/dalle.py` (being deleted, quoted for reference): the constructor shape (`__init__(self, lesson_id) -> AsyncOpenAI(...)`), the circuit-breaker-first pattern, `@with_retry`, and the `_maybe_accumulate_cost` per-lesson cost-tracking helper are all directly reusable patterns for `OpenAIImageProvider` — only the `model=` string and the response-field extraction (`.url` → `.b64_json`) change.

### Cost-ceiling pre-check — new for this node, not present in `tts_node`

CLAUDE.md's per-node AC table explicitly says for `image_generator`: "Fall back to `image_url = None` (text-only) if cost ceiling is near — never fail the pipeline over images." This is a PROACTIVE check (before attempting any provider call), not just the reactive per-call ceiling enforcement `OpenAILLMProvider`/`_maybe_accumulate_cost` already do after a successful call. `cost_tracker.check_ceiling(lesson_id)` (already used elsewhere, e.g. `_fan_out_phase1_economy_nodes`) is the function to call — treat "over ceiling" as an immediate skip-to-`None` for the CURRENT and all SUBSEQUENT slides in this run (no point calling it once per slide if the lesson is already over budget — though calling it once per slide is also correct and simpler; either is acceptable, document whichever is chosen).

### Storage upload pattern — mirror `tts_node`'s post-review pattern exactly

```python
supabase.storage.from_("lesson-images").upload(
    path=f"{lesson_id}/{slide_id}.png",
    file=image_bytes,
    file_options={"content-type": "image/png", "upsert": "true"},
)
```
`lesson-images` is already a provisioned, private bucket (`app/core/storage.py::REQUIRED_BUCKETS`) — no migration/provisioning work needed.

### `slide_images` output shape — flat, NOT nested (a deliberate difference from Stories 2-1/2-7/2-8's pattern)

`PipelineState.slide_images: list[dict[str, Any]]  # [{slide_id, image_url}]` already exists with this exact comment, predating this story. Unlike `quiz_questions`/`slides`/`audio_assets` (which need a `segment_id` correlation key nested alongside a frozen-model-shaped `data` field), `slide_images` only needs `slide_id` — already a unique identifier across the whole lesson (Story 2-7's `f"slide_{segment_id}_{index}"` scheme) — so a flat `{slide_id, image_url}` list is sufficient for `package_builder` to correlate back to the right slide later. Do not nest this output to match the other nodes "for consistency" — the flat shape is correct here and already committed to by the pre-existing field comment.

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch. Story-first gate still applies.

### Testing standards

pytest, matching Story 2-8's conventions exactly: provider tests get their own file, node tests get their own file.

### Project Structure Notes

Two new provider files (`providers/image/openai_image.py`, `providers/image/imagen.py`), one deleted (`providers/image/dalle.py`), `image_generator_node` real implementation in `graph.py`, two new test files.

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-10]
- [Source: docs/bmad/epics/epic-1-content-pipeline.md — Node 14 spec, image fallback chain]
- [Source: docs/stories/2-8-tts-node.md — sibling story whose Review Findings this story's ACs directly incorporate from the start: per-item try/except, upsert, ID-path validation, truthiness checks]
- [Source: apps/api/app/providers/base.py — ImageProvider ABC]
- [Source: apps/api/app/providers/image/dalle.py — structural template before deletion]
- [Source: apps/api/app/providers/llm/openai.py — existing AsyncOpenAI client usage pattern to mirror for OpenAIImageProvider]
- [Source: apps/api/app/core/cost_tracker.py — check_ceiling()/accumulate_cost()]
- [Source: apps/api/app/core/storage.py — REQUIRED_BUCKETS includes lesson-images, already provisioned]
- [Source: apps/api/app/config.py — openai_api_key, google_api_key]
- [Source: apps/api/app/modules/content/pipeline/graph.py — image_generator_node current stub, PipelineState.slide_images field, package_builder_node's stub read of slide_images]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Red-green-refactor per task: Task 1's deletion confirmed clean by re-running the full suite (333/333). Task 2/3's `test_image_providers.py` written first against nonexistent modules — confirmed 5/5 failures — then implemented; the two success-path tests initially failed AGAIN after implementation because `cost_tracker.accumulate_cost`/`check_ceiling` weren't mocked (a real Redis-connection error surfaced, same class of test gap the TTS provider tests didn't hit since those tests didn't originally call cost-accumulating code paths in their success tests either — fixed by adding the missing mocks) — 5/5 green after that fix. Task 4's `test_image_generator_node.py` written first against the still-stub node — confirmed 10/10 failures — then implemented, 10/10 green on the first pass (no post-implementation test bugs this time, unlike Story 2-7's flat-list-vs-per-segment counting mistake).
- Confirmed the empty-`slides` case does NOT need a special early-return branch the way `tts_node`'s did: because this node's per-slide loop and checkpoint-write are structured without an if/else fork (unlike `tts_node`'s empty/non-empty branches), a zero-iteration loop naturally produces `slide_images_out = []` and the unconditional checkpoint write after the loop covers it for free — verified by `test_empty_slides_writes_checkpoint_and_does_not_raise`.

### Completion Notes List

- All 5 tasks / 21 subtasks complete. 348/348 unit tests pass (0 regressions; 15 new tests across 2 new files, 0 pre-existing tests needed updating).
- **This story's explicit design goal — bake in Story 2-8's review lessons from the start rather than repeat the review-then-patch cycle — held up under its own adversarial review-to-come test**: per-slide `try/except`, `upsert: true`, `slide_id` path validation (reusing `_SAFE_SEGMENT_ID_RE` directly rather than inventing a parallel `_SAFE_SLIDE_ID_RE`), and provider-return truthiness checks were all present in the FIRST implementation pass, not added afterward. Whether this actually reduces this story's own code-review finding count remains to be seen once that review runs.
- Cost tracking uses documented placeholder per-image rates (`_COST_PER_IMAGE` in each provider) — neither OpenAI's GPT Image 1 Mini nor Google's Imagen 4 Fast exact billing is verifiable from this environment, same caveat as Story 2-8's TTS cost estimates.
- The proactive cost-ceiling pre-check (AC-3) is genuinely new relative to `tts_node` — `check_ceiling()` is called once per slide, before any provider attempt, matching CLAUDE.md's specific "fall back to text-only if cost ceiling is near" instruction for this node.
- `package_builder_node` (the next and final node in the graph) was NOT touched — remains today's stub, correctly out of scope (S2-11, a separate story).
- **Patch round (2026-07-15):** the 3-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) found 1 CRITICAL, 2 HIGH, and 6 MEDIUM/LOW real issues — the story's "bake in Story 2-8's lessons from the start" goal reduced volume somewhat but did not prevent a genuinely new class of bug: cost accumulation living inside the provider (copied uncritically from the deleted `dalle.py` template) created a check-then-act race where a ceiling breach mid-generation discarded a paid-for image and cascaded to a costlier fallback. All 9 patch findings fixed; both defer findings left as-is (matching accepted cross-story precedent). While verifying the CRITICAL fix, discovered and fixed a second pre-existing bug in the shared `app/core/retry.py` decorator (`raise exc from exc` set an exception as its own `__cause__`, silently defeating any provider's `raise ... from None` redaction) — a latent bug affecting all providers using `@with_retry`, not just this story's new ones, caught only because this story's own regression test asserted `__cause__ is None` end-to-end through the decorator.
- Added 6 more tests during the patch round (cost-timing-after-upload, malformed-data-URI-degradation, non-dict-data-field-safety, unique-placeholder-IDs, unsafe-lesson_id-rejection, empty-bullets-rejection) plus 1 in `test_image_providers.py` (API-key-redaction-through-retry-decorator). Full suite: 356 total (355 passed, 1 pre-existing skip unrelated to this story), 0 regressions.

### File List

- `apps/api/app/providers/image/dalle.py` (deleted — banned technology, DALL-E 3 shut down)
- `apps/api/app/providers/image/openai_image.py` (new — `OpenAIImageProvider`)
- `apps/api/app/providers/image/imagen.py` (new — `ImagenProvider`)
- `apps/api/app/modules/content/pipeline/graph.py` (modified — `image_generator_node` real implementation, `_generate_image_with_fallback()`/`_decode_data_uri()` helpers, `base64` import added)
- `apps/api/tests/unit/test_image_providers.py` (new — 6 tests after patch round)
- `apps/api/tests/unit/test_image_generator_node.py` (new — 16 tests after patch round)
- `apps/api/app/core/retry.py` (modified — patch round: `raise exc from exc` → bare `raise`)

## Change Log

| Date | Change |
|------|--------|
| 2026-07-15 | Story implemented (Tasks 1-5) via `bmad-dev-story`. Deleted banned DALL-E 3 provider; added real OpenAIImageProvider (GPT Image 1 Mini)/ImagenProvider (Imagen 4 Fast); `image_generator_node` now does real GPT Image → Imagen → text-only fallback generation with proactive cost-ceiling checking and a Phase-A-style idempotency checkpoint. Every per-slide failure-isolation/upsert/path-validation lesson from Story 2-8's code review applied from the first implementation pass. 15 new tests, 0 pre-existing tests needed updating. 348/348 total passing. |
| 2026-07-15 | Code review patch round: fixed all 9 findings (1 CRITICAL API-key-leak, 2 HIGH cost-accumulation-race, 6 MEDIUM/LOW). Cost accumulation moved out of both providers into `image_generator_node` (fires only after successful upload); `ImagenProvider` now redacts its API key from any exception; `_decode_data_uri` validates structure and the speculative `url`-fallback was removed; `slide_id`/`lesson_id` extraction hardened; empty-bullets and duplicate-placeholder edge cases closed. Also fixed a newly-discovered pre-existing bug in `app/core/retry.py` (`raise exc from exc` self-referential cause) uncovered while verifying the CRITICAL fix. 7 new tests added (356 total, 355 passed + 1 pre-existing unrelated skip). Status → done. |

### Review Findings (2026-07-15 — 3-layer adversarial review: Blind Hunter, Edge Case Hunter, Acceptance Auditor)

- [x] [Review][Patch] **FIXED 2026-07-15 — CRITICAL — Google API key leaks into logs/observability via query-string auth combined with `exc_info=True` exception logging.** `ImagenProvider.generate()` now catches `httpx.HTTPError` internally and re-raises a sanitized `RuntimeError` (`from None`) with no URL/key in its message. Verified by a new test asserting the key never appears in the exception's `str()`/`repr()` and `__cause__ is None`/`__suppress_context__ is True`. **Additionally uncovered and fixed a second, deeper bug while verifying this fix**: `app/core/retry.py`'s generic `except Exception` branch did `raise exc from exc`, which set `__cause__` to the exception itself — silently defeating the `from None` redaction as soon as the exception passed back through the `@with_retry` decorator. Changed to a bare `raise` (preserves whatever `__cause__`/`__suppress_context__` the original exception already carries, instead of clobbering it). [`app/providers/image/imagen.py`, `app/core/retry.py`] (Blind Hunter)
- [x] [Review][Patch] **FIXED 2026-07-15 — HIGH — A cost-ceiling breach mid-generation discards a successfully-generated, already-paid-for image and misclassifies it as a provider failure, then cascades to a MORE expensive fallback right when spend should stop.** Removed all cost-accumulation logic from both providers; `openai_image.py`/`imagen.py` now export a public `COST_PER_IMAGE` constant instead of a private self-accumulating helper. `image_generator_node` now calls `accumulate_cost()` itself, only after a successful Storage upload — matching `tts_node`'s established pattern. [`app/providers/image/openai_image.py`, `app/providers/image/imagen.py`, `graph.py::image_generator_node`] (Blind Hunter + Edge Case Hunter + Acceptance Auditor — all three, independently)
- [x] [Review][Patch] **FIXED 2026-07-15 — HIGH/MEDIUM — Cost was committed to the ledger before the image was ever persisted, unlike `tts_node`'s cost-after-upload ordering.** Same restructure as the finding above resolves this — `accumulate_cost()` now fires only after the Storage upload succeeds. Verified by a new test asserting `accumulate_cost` is never called when the upload raises. [`graph.py::image_generator_node`] (Edge Case Hunter, same root cause as the Blind Hunter/Acceptance Auditor finding above)
- [x] [Review][Patch] **FIXED 2026-07-15 — MEDIUM — `_decode_data_uri` silently turns a malformed data URI into a "successful" 0-byte image, and `OpenAIImageProvider`'s speculative `url`-fallback branch is the one live path that could trigger it.** Removed the untested `url`-fallback branch from `OpenAIImageProvider` entirely (renamed the missing-b64 test accordingly). `_decode_data_uri` now validates the `data:...;base64,` structure and raises `ValueError` on anything malformed (no `data:` prefix, no `;base64,` marker, or no payload after the comma), so a genuinely bad URI degrades that slide via the existing per-slide `try/except`. Verified by a new test asserting the slide degrades to `image_url: None` with no upload call. [`graph.py::_decode_data_uri`; `app/providers/image/openai_image.py`] (Blind Hunter + Edge Case Hunter, independently)
- [x] [Review][Patch] **FIXED 2026-07-15 — MEDIUM — `slide_id` extraction sits OUTSIDE the per-slide `try/except` and has a wider crash surface than `tts_node`'s equivalent line.** Extraction is now fully defensive (`isinstance()` checks before every `.get()` call), computed safely before the `try:` block using only guaranteed-safe operations — a non-dict `data` field no longer raises `AttributeError`, it degrades just that slide. Verified by a new test asserting a sibling slide still processes normally. [`graph.py::image_generator_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-15 — LOW/MEDIUM — `lesson_id` is used unsanitized in the storage path while only `slide_id` is validated.** Added the same `_SAFE_SEGMENT_ID_RE` check for `lesson_id`, raising `RuntimeError` early in the function if unsafe. Verified by a new test asserting `lesson_id="../../etc/passwd"` raises. [`graph.py::image_generator_node`] (Blind Hunter)
- [x] [Review][Patch] **FIXED 2026-07-15 — LOW — An empty-but-present `bullets` list produces a near-empty prompt and still pays for a provider call instead of degrading to text-only.** An empty `bullets` list is now rejected via the malformed-entry path before any provider call. Verified by a new test asserting the provider's `generate()` is never called. [`graph.py::image_generator_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-15 — LOW — Multiple malformed slide entries all fall back to the identical placeholder `slide_id` `"<unknown>"`.** Placeholder is now unique per entry (`f"<unknown-{index}>"`, via `enumerate()`). Verified by a new test asserting two malformed entries produce two distinct placeholder IDs. [`graph.py::image_generator_node`] (Edge Case Hunter)
- [x] [Review][Patch] **FIXED 2026-07-15 — LOW — `config.py`'s `google_api_key` field description still said "optional, for Gemini model evaluation" — it's now a required production dependency for `ImagenProvider`.** Description updated to reflect its dual purpose. [`app/config.py`] (Acceptance Auditor)
- [x] [Review][Defer] **Idempotency read and final checkpoint write are unprotected by `try/except`.** Identical, already-deferred-3-times pattern (Stories 2-6/2-7/2-8 all found and deferred the same `.single()`-unguarded gap as a codebase-wide pre-existing pattern shared by `embed_node`/`chunk_node`/`structure_node`/every premium+media node in this file) — deferred again for consistency, not a regression specific to this diff. [`graph.py::image_generator_node`] (Blind Hunter) — deferred, matches existing accepted pattern across all four sibling stories.
- [x] [Review][Defer] **No upper bound on base64 payload size before decoding.** Theoretical memory-allocation concern from a compromised/misbehaving provider response; same risk class as Story 2-8's deferred "no length bound on LLM/TTS output" findings — low severity given this pipeline already sits behind auth, rate limiting, and its own cost ceiling. [`graph.py::_decode_data_uri`] (Blind Hunter) — deferred, same risk class as prior sibling stories.

**Dismissed (0):** no findings classified as noise this round — every finding across all three reviewers was substantive (patch or defer).
