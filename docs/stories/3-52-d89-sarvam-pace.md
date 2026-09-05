# Story 3-52 — D89: Sarvam narration pace too fast (default 1.0 unset)

**Branch:** `sprint3/s3-52-d89-sarvam-pace` (from `main`).
**Owner:** Dev 1.
**Trigger:** a real stakeholder watched a real generated lesson play and reported the narration
speed as "very fast."

## Context

Root-caused before this story (not re-derived here): Sarvam's real Bulbul v2 TTS API (verified
against Sarvam's actual API docs, not assumed) supports a `pace` request parameter — `double`,
optional, default `1.0`, valid range `0.3` to `3.0` for `bulbul:v2` — that controls speaking
speed, lower is slower.

`apps/api/app/providers/tts/sarvam.py`'s real synthesize request payload (the `json={...}` dict
passed to `client.post(_SARVAM_TTS_URL, ...)` inside `_synthesize_inner`) currently sends only:

```python
json={
    "inputs": batch,
    "speaker": voice_id,
    "target_language_code": "en-IN",
},
```

No `pace` field at all. Every lesson therefore synthesizes at Sarvam's raw `1.0` default, which
is what the stakeholder heard as "very fast" in real playback. This is the same class of defect
as D67 (`sarvam_voice_id` default) and D74 (chunking/response-shape) found in this file: a real
parameter Sarvam's API actually supports, never wired up because nothing in the existing test
suite exercises real subjective playback quality — mocks assert response *shape*, not audio
*character*.

## The fix

Narrow, targeted fix for the one reported and root-caused issue — pace only.

1. **`apps/api/app/config.py`** — add a new tunable Settings field next to the other Sarvam
   settings (`sarvam_voice_id`), matching this file's own "everything tunable via env var, never
   hardcoded" convention:

   ```python
   sarvam_narration_pace: float = Field(
       default=0.85,
       ge=0.3,
       le=3.0,
       description=(
           "Sarvam Bulbul v2 `pace` parameter for narration synthesis -- controls "
           "speaking speed (lower is slower; Sarvam's own valid range for bulbul:v2 "
           "is 0.3-3.0, default 1.0). Sarvam's raw 1.0 default read as 'very fast' in "
           "real stakeholder playback (D89); 0.85 is a reasoned, moderately-slower "
           "starting value, not an exact scientifically-derived one -- tune via env "
           "var without a code change, same as sarvam_voice_id above."
       ),
   )
   ```

2. **`apps/api/app/providers/tts/sarvam.py`** — add `"pace": self._narration_pace` to the
   synthesize request payload. `SarvamTTSProvider.__init__` already reads `get_settings()` once
   and stores the fields it needs on `self` (`self._api_key = settings.sarvam_api_key`) rather
   than re-reading settings per call — the new field follows the exact same established pattern
   (`self._narration_pace = settings.sarvam_narration_pace` in `__init__`, referenced as
   `self._narration_pace` inside `_synthesize_inner`), not a second, inconsistent
   settings-access pattern.

## What this does NOT do

- Does not touch `pitch`, `loudness`, `temperature`, or any other Sarvam parameter — pace only,
  the one issue actually reported and root-caused.
- Does not touch `_chunk_narration_text` / `_batched` (D74, already correct, unrelated).
- Does not touch `docs/DEFECT-REGISTER.md` or `docs/dev1-tracker.md` — registered centrally by
  the coordinator.
- Does not change `AzureTTSProvider` (the fallback) — Azure's own speed control is a separate
  parameter on a separate real API and is out of scope for this narrowly-targeted fix.

## Scale & Load

1. **Unit of work & range.** One TTS synthesis request (one batched HTTP call to Sarvam's
   `/text-to-speech` endpoint, already batched/chunked per D74). This change adds one constant
   float field to an existing JSON payload — no new unit of work, no new range.
2. **Fixed budgets vs variable input.** N/A — `pace` is a tunable speech-rate ratio, not a
   budget that a variable input can exceed. It is validated at the Settings layer (`ge=0.3,
   le=3.0`, Sarvam's own real documented range) so a misconfigured env var fails fast at process
   startup (pydantic-settings validation error) rather than reaching Sarvam and 400ing per-request.
3. **Scope of the limit.** Per-deployment — one env var, one value, applied to every narration
   synthesis request across every lesson and every user; there is no per-user or per-instance
   override in this story's scope.
4. **Unbounded reads/writes.** N/A — no new read or write path; the field is read once at
   `SarvamTTSProvider.__init__` (same as `sarvam_voice_id`) and added to the same payload dict
   already being sent for every batch.
5. **Inherited caps re-derived.** N/A — no cap is inherited or reused here; `0.85` is a new,
   reasoned default introduced by this story (explicitly documented above as reasoned, not
   scientifically exact), not a value carried over from an earlier, differently-scoped design.
6. **Concurrency.** N/A — `self._narration_pace` is set once in `__init__` and read-only
   thereafter; no shared mutable state, no check-then-act sequence introduced.

## Verification

- RED-GREEN via the Edit tool: add a test asserting the real synthesize request payload includes
  `"pace": <the configured value>`, mocking settings the same way the existing tests in
  `apps/api/tests/unit/test_tts_providers.py` already do (`patch("app.config.get_settings")`,
  `mock_settings.return_value.<field> = ...`). Revert the `pace` line via the Edit tool, confirm
  the new test fails (`"pace"` absent from the payload dict), restore, confirm green.
- Run the full `test_tts_providers.py` file — confirm zero existing tests broke. None of the
  existing tests assert full-dict payload equality (they index specific keys, e.g.
  `call.kwargs["json"]["inputs"]`), so adding a key is not expected to require any other test
  change; verified directly rather than assumed.
- Full repo-wide regression (`python3 -m pytest -q` from `apps/api`) — zero new failures against
  the pre-change baseline.
- `ruff check` / `ruff format` / `mypy` clean on both touched files.


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
