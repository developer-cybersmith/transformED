# Story 3-42 — Sarvam text chunking + real audio decoding (D74)

**Branch:** `sprint3/s3-42-sarvam-text-chunking` (from `main`).
**Owner:** Dev 1.
**Trigger:** L1 acceptance run — found live, mid-run, while investigating why every real
narration segment fell through Sarvam → Azure (unconfigured) → browser (no real audio file).

## Context

D67 (Story 3-41) fixed `sarvam_voice_id`'s invalid default. That fix is necessary but was not
sufficient — while running L1 against the corrected default, every real segment *still* 400'd
against Sarvam. Investigating live (not from docs, per this project's standing rule to verify
against the real API) surfaced two further defects in `SarvamTTSProvider._synthesize_inner`,
neither previously known:

### Defect 1 — 500-char-per-input server limit, never respected

A live call with >500 characters in one `inputs[]` string returns:
```
400 invalid_request_error
"Validation Error(s):\n- inputs.0: String should have at most 500 characters"
```
This codebase's real narration segments run far longer. Pulled from an actual generated lesson
(`f469da7d...`, T3, chapter 0, 15 segments): **lengths 1,351–4,069 characters, every single one
over the limit.** Every real segment was guaranteed to 400 against Sarvam regardless of voice_id
— D67 alone could never have produced real Sarvam audio.

### Defect 2 — `response.content` is the raw JSON body, not decoded audio

Sarvam's `/text-to-speech` endpoint returns `Content-Type: application/json` —
`{"request_id": "...", "audios": ["<base64-encoded WAV>", ...]}` — **not** a raw audio byte
stream. `_synthesize_inner`'s `audio_bytes = response.content` (line 156, pre-fix) captures the
raw JSON text, confirmed live:

```python
resp.headers["content-type"]  # "application/json"
resp.content[:50]             # b'{"request_id":"20260812_d8ba9bf4-aa97-4367-bc79-17...'
base64.b64decode(resp.json()["audios"][0])[:20]  # b'RIFF$\x12\x01\x00WAVEfmt ' -- the REAL audio
```

This has been broken since Story 2-8's original implementation and has **never once been
exercised by a real Sarvam success** in this session's testing (every real call this project has
ever made either hit Defect 1's 500-char limit or an invalid voice_id). Uploaded as-is, this
would have shipped a JSON text blob mislabeled as `audio/mpeg` — a file that "exists," is
non-empty, passes every emptiness check, and is completely unplayable. Exactly the shape
`docs/LESSON-DELIVERY-TRACKER.md`'s own warning describes: *"A valid-but-silent file passes
every assertion we have."* Confirmed no test catches this: every existing test
(`test_tts_node.py`) mocks the entire `SarvamTTSProvider` class at the call site
(`mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])`), so the real HTTP-response-parsing
code in `sarvam.py` has zero coverage. No dedicated `test_sarvam.py` exists at all.

### A third real constraint, found while designing the fix

Sarvam also caps `inputs[]` at **3 items per request** — confirmed live:
```
400 invalid_request_error
"Validation Error(s):\n- inputs: List should have at most 3 items after validation, not 8"
```
So a 4,069-char segment (≈9 chunks of ≤500 chars) needs **3 separate batched requests**, not one
request with 9 items.

## The fix

1. **`_chunk_narration_text(text, max_chars=500)`** — splits on sentence boundaries
   (`(?<=[.!?])\s+`), greedily packing sentences into ≤500-char chunks; falls back to word-boundary
   splitting for the rare single sentence exceeding 500 chars on its own (LLM-generated narration
   is not guaranteed to respect any sentence-length convention).
2. **Batch chunks into groups of ≤3** (Sarvam's real per-request array cap) and send one HTTP
   POST per batch, all within one `_synthesize_inner` call — this is still "one logical call" for
   circuit-breaker/retry accounting purposes (Story 2-32 AC-3's existing contract is unchanged:
   `guard_breaker` records exactly one outcome per `synthesize()` call regardless of how many
   internal HTTP requests it now makes).
3. **Base64-decode every returned clip** (`response.json()["audios"][i]`, not `response.content`).
4. **Concatenate all decoded WAV clips into one continuous file** via Python's `wave` module —
   reads each clip's real PCM frames and re-wraps them under one WAV header with the correct
   combined length. Naive byte concatenation of multiple complete WAV files produces an invalid
   multi-header file that most players stop reading after the first clip's declared length.

## What this does NOT do

- Does not change Sarvam's pricing (`COST_PER_CHAR` unchanged) — billed on total original text
  length, not per-chunk, since chunking doesn't drop or duplicate characters (verified: rejoining
  all chunks with single spaces reproduces the same character count as the input, modulo
  whitespace normalization at chunk boundaries).
- Does not change the circuit breaker or `@with_retry(max_attempts=3)` semantics at the
  `synthesize()` boundary — still exactly one breaker outcome per logical call.
- Does not add per-batch retry — a mid-batch HTTP failure fails the whole `_synthesize_inner`
  call and the existing outer retry decorator re-runs it from scratch (all batches). This is a
  known, accepted limitation shared with every other multi-step provider call in this codebase
  (e.g. LLM structured-completion retries also redo the whole logical call, not just the failed
  step) — not solved here, not silently ignored: named explicitly in Scale & Load Q6 below.
- Does not touch Azure's or the browser fallback's synthesis logic.

## Scale & Load

1. **Unit of work & range.** One narration segment, 1 chunk (≤500 chars) to ~9 chunks (a
   4,069-char segment, the largest observed in a real lesson) → 1 to 3 batched HTTP requests per
   segment (`ceil(chunks / 3)`).
2. **Fixed budgets vs variable input.** Two Sarvam-imposed hard limits, both now respected
   explicitly rather than discovered as a 400: 500 chars/input, 3 inputs/request. Neither is a
   silent truncation — `_chunk_narration_text` never drops characters, it only redistributes them
   across more requests.
3. **Scope of the limit.** Per-request (Sarvam's own API contract), not per-lesson or per-user —
   orthogonal to `settings.max_narration_chars_per_lesson` (Story 3-37's 10,000-char lesson-wide
   cap), which bounds total narration before this chunking ever runs.
4. **Unbounded reads/writes.** None introduced — chunk count is bounded by the segment's own
   length, itself bounded by Story 3-37's lesson-wide cap.
5. **Inherited caps re-derived.** N/A — these are newly-discovered Sarvam API constraints, not
   inherited from an earlier design.
6. **Concurrency.** Batched requests within one `_synthesize_inner` call run sequentially, not
   concurrently — deliberate: Sarvam's own rate limiting is per-key, and firing 3 requests at once
   for one segment would multiply the chance of hitting `rate_limit_exceeded_error` for no
   latency benefit worth the added complexity at this scale (≤3 sequential requests per segment,
   segments already run inside `tts_node`'s existing per-segment loop). Named limitation (not
   solved): a failure on batch 2 of 3 discards batch 1's already-paid-for audio and retries the
   whole call — see "What this does NOT do" above.

## Verification

- RED: reproduced both original defects live against the real Sarvam API (400 on >500 chars;
  `response.content` proven to be JSON text, not audio, via direct byte/header inspection).
- Reproduced the 3-items-per-request cap live before designing the batching fix, rather than
  guessing a batch size.
- New tests in `tests/unit/test_sarvam_chunking.py` (first dedicated Sarvam test file in the
  project) cover: chunking respects the 500-char boundary on real long text, sentence-boundary
  splitting keeps sentences intact where possible, oversized-single-sentence word-boundary
  fallback, batching respects the 3-item cap, WAV concatenation produces a single valid
  multi-frame file (verified via Python's own `wave` module reading it back, not just "is
  non-empty"), and the full `_synthesize_inner` path decodes base64 rather than returning raw
  JSON bytes (mocking `httpx` at the transport level, not mocking `SarvamTTSProvider` itself —
  the first Sarvam test to actually exercise this code path).


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
