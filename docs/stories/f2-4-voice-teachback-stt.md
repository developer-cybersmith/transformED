# Story F2-4 — Voice Teach-Back: Whisper STT Node

**Branch:** `feature2/f2-4-voice-teachback-stt`
**Owner:** Dev 3
**Sprint:** Bug Resolution Sprint (Feature Sprint 2)
**Created:** 2026-09-04

---

## Background

Teach-back is currently typed-only. Students who prefer to speak their explanation must either
type while thinking or skip. Adding a voice submission path (audio → Whisper STT → existing
scorer) closes this gap without changing the scorer, the DB schema, or the frozen typed-submit
endpoint contract.

**Rule status:** The "No STT in MVP" rule in CLAUDE.md was lifted (confirmed 2026-09-04) for
this dedicated audio endpoint only. The typed `POST /assessment/teachback` endpoint remains
unchanged — it still has no `transcript` field.

**Architecture decisions (all confirmed before story creation):**
- Transport: multipart REST upload (`UploadFile`)
- Endpoint: `POST /assessment/teachback/{session_id}/{segment_id}/audio` (new, additive)
- On transcription failure: HTTP 200 + `score_source="fallback"` (Whisper unavailable → skip
  directly to existing fallback scorer)
- Response: existing `TeachbackResult` schema — no new fields, no schema change
- Provider: new `apps/api/app/providers/stt/whisper.py` (follows existing provider pattern)
- DB: transcript stored in `response_text` column (already exists on `teachback_attempts`)
- Raw audio: NEVER stored — DPDP data-minimisation requirement
- Cost: Whisper usage accumulated via `cost_tracker.accumulate_cost(lesson_id, cost_usd)`

---

## Acceptance Criteria

**AC1 — New audio endpoint exists and accepts multipart audio**
`POST /assessment/teachback/{session_id}/{segment_id}/audio` accepts
`audio: UploadFile = File(...)` with JWT auth. Returns `TeachbackResult` on success.

**AC2 — File size is explicitly validated**
Files exceeding `settings.stt_max_file_mb` (default 25 MB) are rejected with HTTP 413 before
the Whisper API is called. No silent truncation or partial upload.

**AC3 — Transcription calls go through WhisperProvider**
Business logic never calls `openai.audio.transcriptions.create()` directly. It calls
`WhisperProvider.transcribe(audio_bytes, filename)` which returns the transcript string.
No hardcoded model string — uses `settings.stt_model` (default `"whisper-1"`).

**AC4 — Transcript fed into existing scorer**
On successful transcription the transcript is passed to `grade_teachback()` as `response_text`,
producing a full `TeachbackScoreResult` with `score_source="llm"`.

**AC5 — Fallback on transcription failure (HTTP 200 + score_source="fallback")**
If `WhisperProvider.transcribe()` raises any exception (API error, timeout, unsupported format):
- The endpoint returns HTTP 200 with `score_source="fallback"` (not HTTP 500)
- `ces_contribution` uses the existing fallback scorer path (same as typed-submit fallback)
- Failure is logged at WARNING level with `exc_info=True`
- No exception propagates to the caller

**AC6 — Whisper cost is accumulated**
After every successful transcription `accumulate_cost(lesson_id, cost_usd)` is called where
`cost_usd = (duration_seconds / 60.0) * STT_COST_PER_MIN` (STT_COST_PER_MIN = 0.006 USD/min).
Whisper `verbose_json` response provides `duration` field for exact billing.

**AC7 — Raw audio is never persisted**
The raw audio bytes are read into memory, transcribed, then discarded. No upload to Supabase
Storage, no DB column, no temp file that outlives the request.

**AC8 — Typed-submit guard tests still pass unchanged**
The five existing guard tests that enforce "typed submission has no STT fields" must pass without
any modification to their assertions:
- `test_teachback_submission_no_transcript_field` (test_assessment_stub_contracts.py)
- `test_submission_has_no_transcript_or_duration_fields` (test_teachback_endpoint.py)
- `test_spec_contains_no_transcript_field` (test_openapi_spec.py)
- `test_teachback_transcript_field_silently_ignored` (test_t26_api_contract_dev2.py)
- `test_teachback_attempts_uses_response_text_not_transcript` (test_migration_assessment_schema.py)
All five continue to pass because `TeachbackSubmission` is unchanged.

**AC9 — No hardcoded model string in new code**
`WhisperProvider` reads the model name from `settings.stt_model`. No string literal
`"whisper-1"` appears in `providers/stt/whisper.py` or `modules/assessment/service.py`.

**AC10 — `__all__` and guard tests for assessment module pass**
`test_node_return_shape.py` and `test_unbounded_queries.py` pass without modification.
Any new public symbol added to the assessment module is listed in `__all__`.

**AC11 — CLAUDE.md updated to reflect lifted rule**
The `"No STT in MVP — typed teach-back only"` line in CLAUDE.md is replaced with the precise
new rule: `"No STT on typed teach-back endpoint — voice uses the dedicated audio endpoint
(POST /assessment/teachback/{session_id}/{segment_id}/audio)"`.

---

## Out of Scope

- Frontend recording UI (Dev 2 story, separate branch)
- Changing `TeachbackSubmission` schema (frozen contract)
- Storing raw audio files anywhere
- Any new DB migration — `response_text` column already exists
- New `TeachbackResult` fields in the API response
- STT on anything other than the new audio endpoint

---

## Scale & Load

**Q1 — Unit of work and range?**
One audio file upload → one Whisper transcription → one `grade_teachback()` scorer call →
one `teachback_attempts` row insert.

- Min: ~1 KB audio file (tiny test clip, ~0s audio)
- Typical: 30–90s voice clip at 64 kbps = ~240–720 KB
- Max stated: `stt_max_file_mb` (default 25 MB); Whisper API hard limit is 25 MB
- Behaviour beyond max: HTTP 413 before the API is called (explicit error, not silent truncation)
- Whisper API duration limit: 25 MB at typical 32 kbps ≈ 100 min audio — well above any
  teach-back response (students would naturally stop at 2–5 min)

**Q2 — Fixed budgets while input varies?**
- File size cap: `stt_max_file_mb` (25 MB default) — enforced in handler before Whisper call.
  Past limit: HTTP 413 explicit error.
- Whisper API timeout: inherits `settings.openai_request_timeout_s` (120s default). Long audio
  may approach this. Past limit: exception caught → fallback path (AC5), never silent hang.
- Per-lesson cost ceiling: $3.00. A 5-min teach-back at $0.006/min = $0.03, negligible.
  `accumulate_cost()` logs accumulation; cost_tracker enforces the ceiling at lesson level.
- Retry: `with_retry()` on WhisperProvider, same §14 rules (3 attempts, exp backoff, retry
  on 429/5xx, never on 400/401). File upload to Whisper is idempotent (no side effect on retry).

**Q3 — Scope of every limit?**
- `stt_max_file_mb`: per-request, enforced in the FastAPI handler before any I/O.
- `openai_request_timeout_s`: per-HTTP-request to Whisper API (OpenAI org rate limits are
  per-org, shared across all API calls from this deployment — no change in scope from LLM calls).
- `teachback_attempts` row insert: per (session_id, segment_id, attempt); same uniqueness scope
  as existing typed-submit path.

**Q4 — Unbounded reads or writes?**
None. The handler reads one uploaded file (size-bounded by AC2). Writes one row to
`teachback_attempts` (bounded by the `segment_id` parameter). No unbounded queries.

**Q5 — Inherited caps re-derived?**
- 25 MB cap: Whisper API hard limit; also chosen because teach-back recordings should be short
  (2–5 min at 64 kbps ≈ 1–2 MB). 25 MB gives 10× headroom even at high bitrate.
- Cost: $0.006/min inherited from Whisper pricing page (as of 2026-09-04). Must be updated
  if OpenAI changes pricing. `STT_COST_PER_MIN` should be an env var or settings constant.
- `openai_request_timeout_s = 120s`: inherited from existing LLM provider config. For Whisper,
  100 min of audio processes in ~10–20s; 120s is generous for any plausible teach-back.

**Q6 — Concurrent safety?**
- Multiple concurrent audio uploads are independent (each reads its own `UploadFile`, calls
  Whisper separately, writes its own DB row).
- `accumulate_cost()` uses Redis `INCRBYFLOAT` (atomic) — safe under concurrent requests.
- No shared in-process state in `WhisperProvider`. Client instance may be shared across requests
  (the provider is stateless except for the `AsyncOpenAI` client, same pattern as LLM provider).

---

## Files Changed

| File | Action | Notes |
|------|--------|-------|
| `CLAUDE.md` | Update | Replace "No STT in MVP" rule with precise scoped rule |
| `apps/api/app/config.py` | Update | Add `stt_model`, `stt_max_file_mb`, `stt_cost_per_min` |
| `apps/api/app/providers/stt/__init__.py` | New | Package init |
| `apps/api/app/providers/stt/whisper.py` | New | WhisperProvider class |
| `apps/api/app/modules/assessment/service.py` | Update | Add `transcribe_and_score_audio()` |
| `apps/api/app/modules/assessment/router.py` | Update | Add audio endpoint, update `__all__` |
| `apps/api/tests/unit/test_f2_4_voice_teachback_stt.py` | New | Unit tests |
| `apps/api/tests/test_teachback_endpoint.py` | Update | Update STT-ban comment text (assertions unchanged) |
| `apps/api/tests/test_assessment_stub_contracts.py` | Update | Update comment text (assertions unchanged) |
| `apps/api/tests/test_t26_api_contract_dev2.py` | Update | Update comment text (assertions unchanged) |
| `docs/dev3-assessment-tracker.md` | Update | Mark F2-4 complete |

---

## Test Plan

New test file: `apps/api/tests/unit/test_f2_4_voice_teachback_stt.py`

| # | Test | Phase | What it asserts |
|---|------|-------|-----------------|
| 1 | `test_audio_endpoint_accepts_upload` | GREEN | POST to audio endpoint with valid WAV → 200 |
| 2 | `test_audio_endpoint_413_on_oversized_file` | GREEN | File > stt_max_file_mb → 413 |
| 3 | `test_whisper_provider_uses_settings_model` | GREEN | WhisperProvider reads settings.stt_model, no literal |
| 4 | `test_transcription_failure_returns_200_fallback` | GREEN | WhisperProvider raises → 200, score_source="fallback" |
| 5 | `test_cost_accumulated_after_transcription` | GREEN | accumulate_cost called with non-zero cost |
| 6 | `test_raw_audio_not_stored` | GREEN | No Supabase Storage call, only DB row insert |
| 7 | `test_audio_endpoint_score_source_llm_on_success` | GREEN | Successful path → score_source="llm" |
| 8 | `test_whisper_provider_no_hardcoded_model` | GREEN | "whisper-1" literal not in whisper.py source |
| 9 | `test_typed_submit_guard_still_passes_no_transcript` | GREEN | TeachbackSubmission has no transcript field |

All tests must be RED before implementation and GREEN after.
