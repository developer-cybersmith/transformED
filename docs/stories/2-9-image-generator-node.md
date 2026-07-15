---
baseline_commit: 64803af372bfd4cde37fe40943eed395404eaf64
---

# Story 2.9: `image_generator` Node — GPT Image 1 Mini → Imagen 4 Fast → Text-Only Fallback (S2-10)

Status: ready-for-dev

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
  - [ ] 1.1 `grep -rn "dalle\|DallE\|DALL-E" apps/api/app apps/api/tests` (excluding `__pycache__`) to confirm scope before deleting — expect the stub's TODO comment (removed with the stub body, Task 4) and `providers/image/dalle.py` itself; check for any test file referencing it too.
  - [ ] 1.2 Delete `apps/api/app/providers/image/dalle.py`. Re-run the full suite immediately after, before any other change, to confirm nothing depended on it (Story 2-8's Task 1.2 precedent).

- [ ] Task 2: `OpenAIImageProvider` (AC: 4, 9, 10)
  - [ ] 2.1 Create `apps/api/app/providers/image/openai_image.py`: `OpenAIImageProvider(ImageProvider)`, `__init__(lesson_id)` mirrors `DalleImageProvider`'s constructor shape (`AsyncOpenAI(api_key=settings.openai_api_key)`, stores `lesson_id` for cost tracking) — this part of the old DALL-E provider's structure is fine to reuse, only the model name and response-shape handling change.
  - [ ] 2.2 `generate(prompt, size)`: `is_circuit_open("gpt_image")` check first; `@with_retry(max_attempts=2)` (optional node, per CLAUDE.md §14's "2 attempts for optional nodes" — image generation is optional, unlike the critical Phase 2 nodes); real call to `self._client.images.generate(model="gpt-image-1-mini", prompt=prompt, size=size, n=1)`; extract `response.data[0].b64_json` (GPT Image models return base64, not a URL) and return as `f"data:image/png;base64,{b64_json}"`. If the response has neither `b64_json` nor `url`, raise a clear `ValueError` (do not return an empty/malformed string).
  - [ ] 2.3 Cost tracking mirrors `DalleImageProvider._maybe_accumulate_cost`'s pattern exactly (per-lesson_id, price-by-size lookup table) — use a documented placeholder price for `gpt-image-1-mini` (see Dev Notes on why an exact rate can't be verified here).

- [ ] Task 3: `ImagenProvider` (AC: 5, 9, 10)
  - [ ] 3.1 Create `apps/api/app/providers/image/imagen.py`: `ImagenProvider(ImageProvider)`, `__init__(lesson_id)` reads `settings.google_api_key`, stores `lesson_id`.
  - [ ] 3.2 `generate(prompt, size)`: `is_circuit_open("imagen")` check first; `@with_retry(max_attempts=2)`; real `httpx.AsyncClient` POST to Google's Imagen 4 Fast REST endpoint with the API key as a query parameter (`?key={api_key}`, Google's documented auth pattern for this API — do not put it in an `Authorization` header, that's not how this API authenticates); extract the base64 image data from the response and return as a `data:` URI, same shape as Task 2.2.
  - [ ] 3.3 Cost tracking mirrors Task 2.3's pattern with an Imagen-specific documented placeholder rate.

- [ ] Task 4: Replace the `image_generator_node` stub body (AC: 1, 2, 3, 7, 8, 11, 12, 13, 14)
  - [ ] 4.1 Idempotency checkpoint read (AC-13), Phase-A pattern — mirror `tts_node`'s exactly, keyed `"image_generator"`.
  - [ ] 4.2 Read `slides = state.get("slides", [])`. Empty list → log a warning, write the checkpoint with `slide_images = []` (Story 2-8's empty-input-still-checkpoints fix, applied from the start), return (AC-14).
  - [ ] 4.3 For each slide entry (iterating `state["slides"]`, each `{"segment_id": ..., "data": {slide_id, title, bullets, ...}}`): wrap the ENTIRE per-slide body in `try/except Exception` from the start (AC-11). Inside: validate `slide_id` against the same safe-path-component pattern Story 2-8 added (AC-12); check `cost_tracker.check_ceiling(lesson_id)` first — if over, set `image_url = None` and skip provider calls entirely (AC-3); otherwise build a prompt from `title`/`bullets` and attempt GPT Image 1 Mini → Imagen 4 Fast → `None`, checking each provider's return value for truthiness (not just non-`None`) before accepting it as success (Story 2-8 AC-2/review-lesson).
  - [ ] 4.4 On a successful provider call: decode the returned `data:` URI to raw bytes (no HTTP GET needed — see AC-4/5's design), upload to `lesson-images` at `f"{lesson_id}/{slide_id}.png"` with `file_options={"content-type": "image/png", "upsert": "true"}` (AC-7); call `cost_tracker.accumulate_cost()` for the successful provider's cost.
  - [ ] 4.5 On ANY exception anywhere in a slide's `try` block (malformed entry, invalid slide_id, provider error not already caught internally, upload error): log a warning with `lesson_id`/`slide_id` context and degrade to `{"slide_id": slide_id_or_placeholder, "image_url": None}` for that slide only — never let the exception propagate out of the loop.
  - [ ] 4.6 Write the checkpoint (AC-13) after the loop.
  - [ ] 4.7 Return `{**state, "slide_images": slide_images_out, "progress_pct": 93.0}` (unchanged progress value from the stub).
  - [ ] 4.8 Remove the stub's stale DALL-E/upload TODO comments. Confirm the `PipelineState.slide_images` field comment (`# [{slide_id, image_url}]`) still matches this story's actual output shape — it already does, no correction needed here (unlike `narration_scripts`/`audio_assets` in Story 2-8).

- [ ] Task 5: Tests (AC: all)
  - [ ] 5.1 Provider unit tests (`apps/api/tests/unit/test_image_providers.py`, new file): `OpenAIImageProvider` — success path returns a `data:image/png;base64,...` string; circuit-open raises before any API call; a response with neither `b64_json` nor `url` raises `ValueError`. `ImagenProvider` — success path returns a `data:` URI; circuit-open raises before any HTTP call.
  - [ ] 5.2 `image_generator_node` tests (`apps/api/tests/unit/test_image_generator_node.py`, new file): happy path (GPT Image 1 Mini succeeds) → storage upload called with `upsert=true` and the right path, `slide_images` entry has the storage path; GPT Image fails + Imagen succeeds → fallback works, GPT Image's failure doesn't propagate; both fail → `image_url: None`, no exception, no upload, no cost; cost-ceiling-over → skips straight to `image_url: None` with zero provider calls; malformed slide entry (missing `title`/`bullets`) → that slide degrades to `None`, other slides still process normally (Story 2-8 review-lesson test, applied proactively); unsafe `slide_id` (e.g. containing `../`) → degrades to `None`, no upload attempted; empty `state["slides"]` → `slide_images == []`, checkpoint written, no exception; idempotency cache-hit → zero provider calls; checkpoint write on success.
  - [ ] 5.3 Full regression: `pytest tests/unit/` — 333/333 (current baseline) still passes.

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

### Completion Notes List

### File List
