---
baseline_commit: ab3d79e64edc1ec233d97d1a81ea87a1d37bc9fc
---

# Story 2.8: `tts_node` — Sarvam → Azure → Browser TTS Fallback Chain (S2-9)

Status: ready-for-dev

## Story

As a **student whose chapter now has real slides** (Story 2-7/S2-8),
I want each segment's narration script synthesised into playable audio (with a fallback if the primary TTS provider is unavailable),
so that the lesson player has real narration audio to play back — instead of the current empty placeholder — while never blocking lesson completion if every server-side TTS provider fails.

This story implements the REAL body of `tts_node` — tracker task **S2-9** in `docs/dev1-tracker.md`, Epic 1's Node 13. The node function and its place in the graph already exist as a stub (`graph.add_edge("slide_generator", "tts_node")` is already wired) — this story replaces the stub body and adds two new TTS provider implementations.

**Critical correction to the stub's own TODO comment:** the current stub's TODO says `ElevenLabsTTSProvider().synthesize(...)` — **ElevenLabs is BANNED** (CLAUDE.md: "ElevenLabs REMOVED"; `apps/api/app/config.py`'s `elevenlabs_api_key` field is already marked deprecated). The dead `apps/api/app/providers/tts/elevenlabs.py` file (a full, unused `ElevenLabsTTSProvider` implementation) must be deleted as part of this story, not left as a landmine for a future dev to accidentally wire back in.

**Scope decision — word-to-slide audio timestamps are explicitly NOT part of this story.** `TTSProvider.synthesize()` (already defined in `app/providers/base.py`) returns *word-level* timestamps (`{"word": str, "start": float, "end": float}`), but the frozen `Narration.timestamps` field is typed `list[NarrationTimestamp]` — a *per-slide* structure (`{slide_id, start_ms, end_ms}`), one timestamp window per slide within a segment's single continuous narration track. Converting continuous word-level alignment into slide-level windows requires knowing how a segment's script maps onto its (1–8, from Story 2-7) slides — a real design problem with no established heuristic anywhere in this codebase yet, and the tracker's own S2-9 AC text does **not** mention timestamps at all (only "Audio file produced per segment; URL in `Narration.audio_url`; `audio_provider` set correctly; pipeline never fails over TTS"). `Narration.timestamps` has no minimum-length constraint, so `timestamps: []` validates cleanly. This story ships every segment with `timestamps: []`; slide-synced timestamp computation is explicitly deferred to a follow-up story once a real approach is agreed (do not invent an unvalidated even-split heuristic here just to fill the field).

## Acceptance Criteria

1. **Input is `state["narration_scripts"]` only** — each entry's `segment_id` and `script` (produced by Story 2-1's `narration_generator_node`) drive synthesis. Never re-reads `state["segment_summaries"]`/`state["sections"]`/`state["chapter_content"]`/`state["slides"]` — this node is audio-only, slide-timestamp mapping is out of scope (see above).
2. **Fallback chain: Sarvam AI Bulbul v2 → Azure TTS → Browser Speech, in that order, per segment** — try Sarvam first; on any failure (provider error, circuit open, non-2xx response) try Azure; on Azure failure too, fall back to `audio_provider="browser"` with `audio_url=""` (the player synthesises client-side from `script` text — no server audio needed for this tier). **The pipeline must NEVER fail over TTS** — a segment that exhausts both server-side providers still produces a valid (browser-fallback) `Narration` entry, never an unhandled exception.
3. **New `SarvamTTSProvider`** (`apps/api/app/providers/tts/sarvam.py`) implementing `TTSProvider.synthesize()` — real HTTP call via `httpx.AsyncClient` to Sarvam's Bulbul v2 TTS endpoint. **403 (not 401) is Sarvam's auth-failure status** — already correctly non-retryable via `with_retry`'s existing `_NON_RETRYABLE_STATUS_CODES` (`{400, 401, 403, 404, 422}`), no change needed there. **A 429 response body must be inspected**: `rate_limit_exceeded_error` → retryable (already the default for status 429 via `with_retry`); `insufficient_quota_error` → NOT retryable — this distinction the generic status-code-only `with_retry` decorator cannot make, so `synthesize()` must inspect the body itself and re-raise a *non*-`httpx.HTTPStatusError` exception (e.g. a plain `RuntimeError`) for the `insufficient_quota_error` case, which falls into `with_retry`'s existing catch-all "unknown exception — do not retry" branch — do not modify `with_retry` itself.
4. **New `AzureTTSProvider`** (`apps/api/app/providers/tts/azure.py`) implementing `TTSProvider.synthesize()` — real HTTP call via `httpx.AsyncClient` to Azure Cognitive Services' Speech synthesis REST endpoint (`https://{settings.azure_tts_region}.tts.speech.microsoft.com/cognitiveservices/v1`), using `settings.azure_tts_key`. Word-level timestamps are not natively returned by Azure's basic synthesis endpoint in the same shape Sarvam/ElevenLabs provide — return an empty timestamp list from this provider (consistent with this story's overall timestamp scope decision above), not a fabricated one.
5. **`elevenlabs.py` deleted, not just unwired** — `apps/api/app/providers/tts/elevenlabs.py` (the full, currently-unused `ElevenLabsTTSProvider` implementation) is removed entirely. Confirm nothing imports it before deleting (grep first).
6. **Successful audio uploads to the private `lesson-audio` Supabase Storage bucket** — audio bytes from a successful Sarvam/Azure call are uploaded to `lesson-audio` at a deterministic path `{lesson_id}/{segment_id}.mp3`; `Narration.audio_url` is set to that **storage path** (not a public URL — `lesson-audio` is private per CLAUDE.md §18, frontend fetches via the signed-URL endpoint, never `getPublicUrl`).
7. **Output shape is internal (nested `{segment_id, data}`), matching the established Story 2-1/2-7 pattern** — `state["audio_assets"]` becomes `list[{"segment_id": str, "data": {script, audio_url, audio_provider, timestamps: []}}]`, where `data` is validated via `Narration.model_validate(...)` inside this node itself (same "validate now, not deferred to `package_builder`" discipline Story 2-7 established for `Slide`).
8. **Circuit breaker wired per provider** — `is_circuit_open("sarvam")` checked before every Sarvam call, `is_circuit_open("azure_tts")` before every Azure call (separate provider keys — a Sarvam outage must not affect Azure's circuit state or vice versa). `record_success`/`record_failure` called on each provider's own key.
9. **Cost tracked** — TTS cost is included in `cost_tracker.accumulate_cost()` for every successful synthesis call (Sarvam or Azure), matching CLAUDE.md's "Include TTS cost in cost_tracker.accumulate_cost()" requirement. Browser-fallback segments incur zero cost (nothing was called server-side).
10. **Idempotency checkpoint, Phase-A style** (same pattern as `lesson_planner_node`/`slide_generator_node`) — read `lesson_jobs.node_outputs`; `"tts_node"` key present → return cached, skip all synthesis. On success, plain client-side read-modify-write.
11. **Empty `narration_scripts` does NOT raise** — unlike `lesson_planner_node`/`slide_generator_node` (Phase 2 premium nodes, empty input = upstream bug = raise), `tts_node`'s own house rule is "never hard-fail the pipeline over TTS" — an empty `narration_scripts` list produces an empty `audio_assets` list and a warning log, not an exception. This is a deliberate, documented divergence from Story 2-6/2-7's empty-input guard pattern, not an oversight.
12. All existing tests continue to pass unmodified.

## Tasks / Subtasks

- [ ] Task 1: Delete the banned ElevenLabs provider (AC: 5)
  - [ ] 1.1 `grep -rn "elevenlabs\|ElevenLabs" apps/api/app apps/api/tests` (excluding `__pycache__`) to confirm the only references are: `graph.py`'s stub TODO comment (removed alongside the stub body in Task 3), `config.py`'s already-deprecated `elevenlabs_api_key` field (leave as-is — harmless, documents history), `providers/tts/elevenlabs.py` itself, and `test_lesson_schema.py`'s enum-rejection test (asserts `"elevenlabs"` is an INVALID `AudioProvider` value — keep this test, it doesn't reference the file).
  - [ ] 1.2 Delete `apps/api/app/providers/tts/elevenlabs.py`.

- [ ] Task 2: `SarvamTTSProvider` (AC: 3, 8, 9)
  - [ ] 2.1 Create `apps/api/app/providers/tts/sarvam.py`: `SarvamTTSProvider(TTSProvider)`, `__init__` reads `settings.sarvam_api_key`.
  - [ ] 2.2 `synthesize(text, voice_id)`: `is_circuit_open("sarvam")` check first (raise if open, matching the `OpenAILLMProvider.complete_structured()` convention exactly); `@with_retry(max_attempts=3)`-decorated; real `httpx.AsyncClient` POST to Sarvam's Bulbul v2 endpoint; on 429, inspect the JSON body for an error-type field — if it indicates quota exhaustion (`insufficient_quota_error`), raise a plain `RuntimeError` (non-retryable via `with_retry`'s catch-all) instead of re-raising the `httpx.HTTPStatusError`; otherwise let the 429 propagate normally (retryable). `record_success`/`record_failure("sarvam")` on the outcome.
  - [ ] 2.3 Return `(audio_bytes, [])` — empty word-timestamps list is acceptable per this story's Narration-timestamps scope decision; do not attempt to parse alignment data even if Sarvam's response happens to include it.
  - [ ] 2.4 Cost: add a `_maybe_accumulate_cost`-equivalent call (or call `cost_tracker.accumulate_cost()` directly from `tts_node` after a successful Sarvam call, whichever keeps the provider class itself free of pipeline-specific `lesson_id` cost-tracking concerns — follow whichever pattern is simpler given `SarvamTTSProvider`'s constructor doesn't take a `lesson_id` the way `OpenAILLMProvider` does; document the choice in Dev Notes).

- [ ] Task 3: `AzureTTSProvider` (AC: 4, 8, 9)
  - [ ] 3.1 Create `apps/api/app/providers/tts/azure.py`: `AzureTTSProvider(TTSProvider)`, `__init__` reads `settings.azure_tts_key`/`settings.azure_tts_region`.
  - [ ] 3.2 `synthesize(text, voice_id)`: `is_circuit_open("azure_tts")` check first; `@with_retry(max_attempts=3)`; real `httpx.AsyncClient` POST to `https://{region}.tts.speech.microsoft.com/cognitiveservices/v1` with SSML built from `text`/`voice_id`, `Ocp-Apim-Subscription-Key` header. `record_success`/`record_failure("azure_tts")`.
  - [ ] 3.3 Return `(audio_bytes, [])`.

- [ ] Task 4: Replace the `tts_node` stub body (AC: 1, 2, 6, 7, 9, 10, 11)
  - [ ] 4.1 Idempotency checkpoint read (AC-10), Phase-A pattern — mirror `lesson_planner_node`/`slide_generator_node` exactly, keyed `"tts_node"`.
  - [ ] 4.2 Read `narration_scripts = state.get("narration_scripts", [])`. Empty list → log a warning, skip straight to checkpoint-write-and-return with `audio_assets = []` (AC-11 — do NOT raise, unlike Story 2-6/2-7's empty-input guards).
  - [ ] 4.3 For each entry, attempt Sarvam; on any exception (circuit-open `RuntimeError`, `httpx.HTTPStatusError`, or the retry-exhausted final exception `with_retry` re-raises), log and fall through to Azure; on Azure failure too, fall through to `audio_provider="browser"`, `audio_url=""`, zero cost, no exception raised at the `tts_node` level regardless of what either provider did (AC-2).
  - [ ] 4.4 On a successful Sarvam/Azure call: upload `audio_bytes` to Supabase Storage `lesson-audio` bucket at `f"{lesson_id}/{segment_id}.mp3"` (AC-6); call `cost_tracker.accumulate_cost()` for the successful provider's synthesis cost (AC-9 — see Dev Notes for the cost-model approach, since TTS isn't token-priced like `_COST_PER_1K`).
  - [ ] 4.5 Assemble `{"segment_id": ..., "data": Narration.model_validate({"script": ..., "audio_url": ..., "audio_provider": ..., "timestamps": []}).model_dump(mode="json")}` per entry (AC-7).
  - [ ] 4.6 Write the checkpoint (AC-10).
  - [ ] 4.7 Return `{**state, "audio_assets": audio_assets_out, "progress_pct": 86.0}` (unchanged progress value from the stub).
  - [ ] 4.8 Remove the stub's stale `ElevenLabsTTSProvider`/upload TODO comments. Correct the stale `PipelineState.narration_scripts` field comment (currently `# [{slide_id, script}]`, which has never matched `narration_generator_node`'s real output shape `{segment_id, script, narration_style, word_count}` since Story 2-1 shipped) and the stale `PipelineState.audio_assets` field comment (currently `# [{slide_id, audio_url, timestamps}]`) to the nested `{segment_id, data: {...}}` shape this story actually produces.

- [ ] Task 5: Tests (AC: all)
  - [ ] 5.1 Provider unit tests (`apps/api/tests/unit/test_tts_providers.py`, new file): `SarvamTTSProvider` — success path returns `(bytes, [])`; circuit-open raises before any HTTP call; a 429 with `rate_limit_exceeded_error` body is retried (via `with_retry`, verify call count); a 429 with `insufficient_quota_error` body is NOT retried (verify call count == 1); a 403 is not retried. `AzureTTSProvider` — success path returns `(bytes, [])`; circuit-open raises before any HTTP call.
  - [ ] 5.2 `tts_node` tests (`apps/api/tests/unit/test_tts_node.py`, new file): happy path (Sarvam succeeds) → `audio_provider="sarvam"`, storage upload called with the right path, `Narration.model_validate` passes; Sarvam fails + Azure succeeds → `audio_provider="azure"`, Sarvam's failure doesn't propagate; both fail → `audio_provider="browser"`, `audio_url=""`, no exception raised, no storage upload attempted, no cost accumulated; empty `narration_scripts` → `audio_assets == []`, no exception (AC-11); idempotency cache-hit → zero provider calls; AC-1 regression guard (prompt/input never includes `sections`/`chapter_content`/`slides` — trivial here since this node makes no LLM call at all, but assert the function signature/body never references those keys); checkpoint write on success.
  - [ ] 5.3 Full regression: `pytest tests/unit/` — 314/314 (current baseline) still passes.

## Dev Notes

### The node and its place in the graph already exist — this story replaces the stub body + adds 2 provider files

Current stub (`graph.py`, quoted in full):
```python
async def tts_node(state: PipelineState) -> PipelineState:
    """Node 13: Synthesise narration scripts to audio with word timestamps."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] tts_node: synthesising %d narrations", lesson_id, len(state.get("narration_scripts", [])))
    await _update_job_progress(lesson_id, 80.0, "tts_node")

    # TODO: ElevenLabsTTSProvider().synthesize(script, voice_id)
    # TODO: upload audio to Supabase Storage (lesson-audio bucket)
    audio_assets: list[dict[str, Any]] = []
    return {**state, "audio_assets": audio_assets, "progress_pct": 86.0}
```
Graph wiring (`_build_pipeline_graph()`) already has `graph.add_edge("slide_generator", "tts_node")` and `graph.add_edge("tts_node", "image_generator")` — nothing about topology changes. `image_generator_node`/`package_builder_node` remain stubs for separate stories (S2-10/S2-11).

### `TTSProvider` ABC (already exists, `app/providers/base.py`)

```python
class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice_id: str) -> tuple[bytes, list[dict[str, Any]]]:
        ...
```
Both `SarvamTTSProvider` and `AzureTTSProvider` implement this exact signature. The deleted `ElevenLabsTTSProvider` (`providers/tts/elevenlabs.py`, quoted for reference since it's being deleted) is the closest existing template for the circuit-breaker/retry/error-handling shape to follow — it correctly checked `is_circuit_open()` first, used `@with_retry(max_attempts=3)`, and called `record_success`/`record_failure` — reuse that STRUCTURE, not its ElevenLabs-specific HTTP calls.

### `with_retry`'s existing status-code classification (no changes needed to `app/core/retry.py`)

```python
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_NON_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({400, 401, 403, 404, 422})
```
403 is already non-retryable (matches "403 = Sarvam auth failure, never retry"). 429 is retryable by default — the `insufficient_quota_error` vs `rate_limit_exceeded_error` distinction must be made INSIDE `SarvamTTSProvider.synthesize()` before `with_retry` ever sees the exception: catch the `httpx.HTTPStatusError` for a 429, inspect `exc.response.json()` for the error type, and if it's `insufficient_quota_error`, raise a plain `RuntimeError` instead (which falls into `with_retry`'s `except Exception: ... raise exc from exc` branch — no retry). If it's `rate_limit_exceeded_error` (or unrecognized), re-raise the original `httpx.HTTPStatusError` unchanged so `with_retry`'s normal 429-is-retryable path applies.

### `narration_scripts` shape (Story 2-1's `narration_generator_node` output) — corrects a long-stale `PipelineState` comment

Each entry: `{"segment_id": str, "script": str, "narration_style": str, "word_count": int}` (verified against `narration_generator_node`'s actual `result` dict, `graph.py`). The `PipelineState.narration_scripts` field comment has said `# [{slide_id, script}]` since Story 2-1 shipped — wrong on both the key name (`segment_id`, not `slide_id`) and the field set (missing `narration_style`/`word_count`). Fix it while touching this area (Task 4.8).

### `Narration`/`NarrationTimestamp` frozen schema (`app/schemas/lesson.py`)

```python
class NarrationTimestamp(BaseModel):
    model_config = _STRICT
    slide_id: str
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(ge=0)]

class Narration(BaseModel):
    model_config = _STRICT
    script: str
    audio_url: str  # Supabase Storage signed URL — relative paths allowed in dev
    audio_provider: AudioProvider  # Literal["sarvam", "azure", "browser"]
    timestamps: list[NarrationTimestamp]
```
`timestamps: list[NarrationTimestamp]` has NO `min_length` — `[]` validates. `audio_url: str` (not `AnyHttpUrl`) — a bare storage path string is valid, consistent with AC-6's private-bucket-path requirement (not a public URL).

### Storage upload pattern (mirror `router.py`'s existing `upload_lesson()` pattern)

```python
supabase.storage.from_("lesson-audio").upload(
    path=f"{lesson_id}/{segment_id}.mp3",
    file=audio_bytes,
    file_options={"content-type": "audio/mpeg"},
)
```
`lesson-audio` is already a provisioned, private bucket (`app/core/storage.py::REQUIRED_BUCKETS`) — no migration/provisioning work needed here.

### Cost tracking approach — TTS isn't token-priced like the LLM providers

`OpenAILLMProvider._maybe_accumulate_cost()` prices by `(input_tokens, output_tokens)` against `_COST_PER_1K` — that model doesn't apply to TTS (priced per-character or per-second by these vendors, not per-token). Call `cost_tracker.accumulate_cost(lesson_id, cost)` directly from `tts_node` after a successful synthesis, with `cost` computed from a simple per-character-count estimate (e.g. `len(script) * settings.sarvam_cost_per_char` or a flat conservative per-call estimate) — the exact pricing formula is a judgment call for whoever implements this task; document whichever estimate is chosen and why, since neither vendor's exact billing API is available to verify against in this environment. Do not skip cost tracking entirely — CLAUDE.md's cost-ceiling rule applies to every provider call, TTS included.

### Circuit breaker keys — one per provider, not shared

`is_circuit_open("sarvam")` / `is_circuit_open("azure_tts")` are independent keys (`app/core/circuit_breaker.py` keys by provider-string, no code change needed there) — a Sarvam outage must not trip Azure's circuit and vice versa, matching CLAUDE.md's explicit fallback-chain intent (the whole POINT of a fallback chain is that the two providers fail independently).

### Empty-input behavior is a deliberate divergence from Story 2-6/2-7's pattern — do not "fix" it to match

Story 2-6 (`lesson_planner_node`) and Story 2-7 (`slide_generator_node`) both raise on empty input because they're single-shot premium nodes with no fallback — an empty input there is an upstream bug worth surfacing loudly. `tts_node`'s entire design philosophy (per CLAUDE.md §14: "TTS fallback chain ... NEVER hard-fails") is the opposite: this node exists specifically to guarantee the pipeline completes regardless of TTS availability. Extending that same "never hard-fail" posture to its own empty-input case (rather than treating it as parallel to the Phase 2 nodes' stricter posture) is the correct, deliberate choice — flag this explicitly in code review if it's questioned, don't silently "fix" it to raise.

### Branch

Single shared branch for all of Sprint 2: `sprint2/phase-b-generation-nodes` — do not create a new branch. Story-first gate still applies.

### Testing standards

pytest, matching established conventions. Provider tests get their own file (`test_tts_providers.py`, mirroring how `test_provider_tracing_resilience.py` tests provider-level concerns separately from node-level tests); node tests get `test_tts_node.py` (mirroring `test_lesson_planner_node.py`/`test_slide_generator_node.py`).

### Project Structure Notes

Two new provider files (`providers/tts/sarvam.py`, `providers/tts/azure.py`), one deleted (`providers/tts/elevenlabs.py`), `tts_node` real implementation in `graph.py`, two new test files.

### References

- [Source: docs/dev1-tracker.md — Sprint 2 section, S2-9]
- [Source: docs/bmad/epics/epic-1-content-pipeline.md — Node 13 spec]
- [Source: docs/stories/2-6-lesson-planner-node.md, docs/stories/2-7-slide-generator-node.md — sibling stories this one follows: internal loose models N/A here (no LLM call), but idempotency checkpoint pattern, nested {segment_id, data} output, and input-order discipline all carry over]
- [Source: apps/api/app/providers/base.py — TTSProvider ABC]
- [Source: apps/api/app/providers/tts/elevenlabs.py — structural template (circuit breaker/retry shape) before deletion]
- [Source: apps/api/app/core/retry.py — with_retry()'s existing status-code classification]
- [Source: apps/api/app/schemas/lesson.py — Narration/NarrationTimestamp frozen models]
- [Source: apps/api/app/config.py — sarvam_api_key, azure_tts_key, azure_tts_region, elevenlabs_api_key (deprecated)]
- [Source: apps/api/app/core/storage.py — REQUIRED_BUCKETS includes lesson-audio, already provisioned]
- [Source: apps/api/app/modules/content/router.py — storage upload call pattern to mirror]

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

### Completion Notes List

### File List
