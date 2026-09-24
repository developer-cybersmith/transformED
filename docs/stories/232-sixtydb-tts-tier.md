---
id: "232"
title: "TTS: add 60db.ai as new primary tier (60db → Sarvam → Azure → Browser)"
status: "in-progress"
sprint: null
story_points: 3
baseline_commit: "main@HEAD"
owner: Dev1
priority: P2
blocker_ref: "GitHub issue #232"
---

# Story 232 — 60db.ai TTS Tier (audio-only)

## Context & Scope Boundary

**Why this story exists:** GitHub issue #232 asks for 60db.ai to be added as a new
primary TTS tier ahead of the existing Sarvam → Azure → Browser fallback chain,
per the research in `docs/proposals/2026-09-19-platform-changes-scope.md` (Draft
Story C). Rollout shape locked by the issue: additional tier, never a hard
cutover — matches this chain's existing "never hard-fails" philosophy.

**Corrected scope vs. the original issue text (verified live, 2026-09-21):**
issue #232 stated "60db returns word-level timestamps natively... included in
this issue's scope, not deferred." A real, live call to
`POST https://api.60db.ai/tts-synthesize` (real API key, real voice_id) returned
a JSON object with exactly two top-level keys — `audioContent` (base64 LINEAR16
PCM) and `conditioning` (voice-adapter/emotion metadata) — **no timing/timestamp
field of any kind**. Every timing-related keyword (`timestamp`, `timing`, `word`,
`align`, `start_ms`, `end_ms`, `start_time`, `end_time`) was searched for in the
raw response body: zero hits. The claim traces to earlier public-web research,
exactly the category of source this same issue elsewhere warns is unreliable
("do not implement against the publicly-documented shape — it's wrong"). This
story is **audio-only** — no word-level timestamps exist to wire anywhere.

Also found live and worth recording: the 60db skill's own reference docs describe
the response as nested under `{"result": {"audioContent": ...}}`; the real,
live shape has `audioContent` and `conditioning` at the **top level**, no
`result` wrapper. The parser below matches the verified live shape as primary,
with a defensive fallback to the documented (possibly stale) `result`-wrapped
shape, since only one live response was observed and API responses can vary
by input.

**What this story does:**
1. Adds `SixtyDbTTSProvider` (`apps/api/app/providers/tts/sixtydb.py`),
   implementing the existing `TTSProvider` ABC — audio bytes only, timestamps
   always `[]` (nothing to return, per the finding above).
2. Inserts it as the new first tier in `_synthesize_with_fallback()`
   (`graph.py`): **60db → Sarvam → Azure → Browser**. Sarvam and Azure's own
   provider classes are unchanged — only their position in the chain moves.
3. Adds `sixtydb_api_key`, `sixtydb_voice_id`, `sixtydb_model`,
   `sixtydb_speed`, `sixtydb_enhance` to `config.py` — all optional
   (`None`/sensible default), so a deployment with no 60db key configured
   degrades to today's exact behavior (60db call fails auth, falls through to
   Sarvam) rather than breaking.
4. Adds `"sixtydb"` to the frozen `AudioProvider` enum (`schemas/lesson.py`,
   `packages/shared/types/lesson.ts`, `packages/shared/lesson_package.schema.json`)
   — **flagged for the required 4-developer review before merge** (CLAUDE.md
   frozen-contract rule); this story's diff includes the change, not the sign-off.
5. Fixes the pre-existing, unrelated `.env.example` gap in the same file: adds
   missing `SARVAM_*`/`AZURE_TTS_*` entries, removes/corrects the stale
   `ELEVENLABS_*` entry.
6. New cost-tracking placeholder: 60db publishes no per-character price (only a
   wallet-credit model) — `COST_PER_CHAR` uses Sarvam's rate ($0.00002/char) as
   a conservative, explicitly-unconfirmed placeholder, registered as **D168**
   (`docs/DEFECT-REGISTER.md`) per CLAUDE.md binding rule 5 (a documented
   limitation must carry a register ID).

**What this story does NOT do:**
- Does not implement any word-level timestamp / caption-accuracy work — see
  the corrected-scope note above.
- Does not remove Azure or Sarvam from the chain, and does not promote 60db
  beyond "additional tier ahead of Sarvam" — matches the issue's explicit
  "never a hard cutover" decision, confirmed with the user (Option B of two
  presented: 60db → Sarvam → Azure → Browser, all four tiers retained).
- Does not gate on, or block on, the two non-code prerequisites named in the
  proposal doc (native-speaker Indic TTS quality review; written data-residency
  answer from 60db) — those gate *promotion* to sole-primary, not adding an
  A/B tier, per Draft Story C's own text ("can start in parallel").
- Does not add a `sixtydb_sample_rate` setting — the REST `/tts-synthesize`
  endpoint takes no `sample_rate` request field (confirmed against the skill's
  own request-body table); output is natively 48kHz over REST, hardcoded in
  the WAV-wrapping step, matching the skill's documented "REST native = 48000 Hz."
- Does not implement the WebSocket or streaming transports — REST one-shot
  only, matching Sarvam/Azure's existing one-shot-per-segment call pattern.

## Story

**As** the content pipeline,
**I want** 60db.ai available as a new primary TTS tier ahead of Sarvam,
**so that** lessons can use 60db's narration quality when available, while
falling back through the existing Sarvam → Azure → Browser chain exactly as
today whenever it isn't (no key configured, API failure, or empty response).

## Acceptance Criteria

### Functional
- [x] **AC 1.** `SixtyDbTTSProvider.synthesize(text, voice_id)` implements
  `TTSProvider`, applies circuit breaker (`"sixtydb"` key) and the same
  `@with_retry(max_attempts=3)` pattern as Sarvam/Azure, returns
  `(audio_bytes, [])`.
- [x] **AC 2.** Text over 5000 chars is chunked (sentence-boundary preferred,
  word-boundary fallback for an oversized single sentence — same approach as
  Sarvam's `_chunk_narration_text`, `max_chars=5000`), one `/tts-synthesize`
  request per chunk, sequential (not concurrent — same per-key rate-limit
  reasoning as Sarvam).
- [x] **AC 3.** Each response body is parsed defensively: split on newlines
  (NDJSON-tolerant), each non-empty line parsed as JSON; `audioContent` is read
  from the top level first (verified live shape), falling back to
  `result.audioContent` if the top-level key is absent (documented shape,
  unverified for variance) — raises a clear `RuntimeError` if neither shape
  yields an `audioContent` value.
- [x] **AC 4.** All decoded base64 PCM chunks (raw LINEAR16, no WAV header) are
  concatenated as raw bytes (valid for PCM, unlike complete-WAV-file
  concatenation), then wrapped in exactly one WAV header at 48000 Hz / mono /
  16-bit at the end.
- [x] **AC 5.** `synthesize()` always returns `(audio_bytes, [])` — the empty
  list documented as "60db's TTS response carries no timing data (confirmed
  live, 2026-09-21) — see Context & Scope Boundary," not left as an
  unexplained empty default like Sarvam/Azure's (theirs is "deferred", this
  one is "confirmed absent").
- [x] **AC 6.** `config.py` gains `sixtydb_api_key: str | None = None`,
  `sixtydb_voice_id: str | None = None`, `sixtydb_model: str = "60db-quality"`,
  `sixtydb_speed: float = Field(default=1.0, ge=0.5, le=2.0)`,
  `sixtydb_enhance: bool = True`. Missing key/voice_id raises inside the
  provider (clear `ValueError`), caught by `_synthesize_with_fallback`'s
  existing `except Exception` — falls through to Sarvam exactly like an Azure
  auth failure does today. No crash for a deployment with no 60db key set.
- [x] **AC 7.** `_synthesize_with_fallback()` tries 60db first, Sarvam second,
  Azure third, browser last — same "log + fall through" shape as the existing
  Sarvam→Azure transition; returns `(audio_bytes, "sixtydb", cost)` on success.
- [x] **AC 8.** `AudioProvider` gains `"sixtydb"` in `schemas/lesson.py`,
  `packages/shared/types/lesson.ts`, `packages/shared/lesson_package.schema.json`
  — all three edited together, comment on each noting the 4-developer review
  requirement before merge.
- [x] **AC 9.** `.env.example` gets `SARVAM_API_KEY`, `SARVAM_VOICE_ID`,
  `SARVAM_NARRATION_PACE`, `AZURE_TTS_KEY`, `AZURE_TTS_REGION`,
  `AZURE_TTS_VOICE` (all currently missing), `SIXTYDB_API_KEY`,
  `SIXTYDB_VOICE_ID`, `SIXTYDB_MODEL`, `SIXTYDB_SPEED`, `SIXTYDB_ENHANCE`; the
  stale `ELEVENLABS_API_KEY` line is removed (matches `config.py`'s own
  "deprecated, replaced by Sarvam" note — the var itself still exists in
  `config.py` as an inert optional field, only the `.env.example` line is
  stale/misleading and is what this AC fixes).
- [x] **AC 10.** `docs/DEFECT-REGISTER.md` gains a **D168** entry for the
  unconfirmed 60db per-character cost rate (placeholder = Sarvam's rate).

### Tests
- [x] **AC 11.** New `apps/api/tests/unit/test_tts_providers_sixtydb.py`:
  success (single chunk), success (multi-chunk >5000 chars, PCM concatenation
  correctness), top-level `audioContent` shape, fallback `result.audioContent`
  shape, malformed-response `RuntimeError`, circuit-breaker-open rejection,
  missing key/voice_id `ValueError`, retry-then-succeed. Real fixture PCM/WAV
  bytes, no live network calls — same conventions as
  `test_tts_providers.py`.
- [x] **AC 12.** `test_tts_node.py` gains: 60db-succeeds-first case,
  60db-fails-falls-to-sarvam case, 60db-not-configured-falls-to-sarvam case.

### Process
- [x] **AC 13.** Guard-test survey run (CLAUDE.md rule) before implementation:
  `grep -rn "test_.*tts\|test_no_hardcoded\|test_dunder_all" apps/api/tests/` —
  results listed in Dev Agent Record.
- [x] **AC 14.** Full gating-scope regression
  (`tests/unit tests/integration -m "not postgres"`) shows zero new failures
  vs. `main`. `ruff check .`, `ruff format --check`, `mypy app` clean vs. `main`.
- [x] **AC 15 (partial — see note).** All 6 CLAUDE.md review layers now
  complete across Review Rounds 2-3 (Blind Hunter, Edge Case Hunter,
  Acceptance Auditor, Scale & Load Hunter, Story Quality, Test Coverage, AC
  Completeness, Process Integrity — 8 ran total, the 6 CLAUDE.md names among
  them all present). **Still outstanding, cannot be satisfied by this story
  alone:** because this diff touches a frozen contract (AC 8), a PR reviewed
  by all 4 developers per CLAUDE.md's frozen-contract rule is also required
  before merge — checked `[x]` for the review-layer portion this story CAN
  complete, not for the human sign-off it cannot.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one narration segment's TTS
   synthesis call — same unit Sarvam/Azure already handle today. Segment length
   range is unchanged by this story (still bounded upstream by
   `max_narration_chars_per_lesson`, Story 3-45's cap). 60db's own per-request
   limit (5000 chars) is 10x Sarvam's (500 chars), so the chunking path this
   story adds will trigger far less often in practice than Sarvam's does today,
   but is implemented unconditionally (never assume "it'll always fit").
2. **Fixed budgets vs. variable input.** Two: (a) 60db's 5000-char/request cap
   — explicit chunk-and-concatenate, never silent truncation, same discipline
   as Sarvam's 500-char handling. (b) The $3.00/lesson cost ceiling — 60db's
   real per-character price is **not published** (wallet-credit billing only);
   this story uses Sarvam's rate as an explicit, documented, unconfirmed
   placeholder (D168) rather than guessing a number with no traceable
   justification or silently treating 60db calls as free.
3. **Scope of every limit.** Per-request (60db's char cap) and per-lesson (cost
   ceiling) — both unchanged in scope from the existing Sarvam/Azure tiers;
   this story adds a third provider under the same two limit types, not a new
   limit type.
4. **Unbounded reads/writes.** None introduced. `SixtyDbTTSProvider` is a pure
   HTTP-call class with no Supabase/Redis reads beyond the circuit-breaker
   state Sarvam/Azure already read identically (keyed by the new `"sixtydb"`
   string, same `circuit:{provider}:*` key shape).
5. **Inherited caps re-derived?** N/A — new provider, nothing inherited. The
   circuit breaker's `FAILURE_THRESHOLD`/`RECOVERY_TIMEOUT_SECONDS` constants
   are reused unchanged (correct: they're provider-agnostic breaker mechanics,
   not a 60db-specific number that needed re-deriving).
6. **Check-then-act under concurrency.** No new risk: `guard_breaker()`'s
   atomic Redis accounting (already used identically by Sarvam/Azure) is reused
   verbatim for the `"sixtydb"` key — a fourth independent breaker key sharing
   the same already-concurrency-safe mechanism, not a new code path.

**The one-line test, answered:** the failure this story could introduce if done
wrong is a **silent one** — if 60db's response shape ever drifted and the
parser guessed wrong, it could either crash the whole node (bad, but loud — not
this failure class) or, worse, silently swallow a real error and report
`cost_usd=0.0`/wrong provider attribution while actually billing the wallet.
AC 3's explicit dual-shape parse + hard `RuntimeError` on a genuinely
unrecognized shape (never a silent default-to-empty-audio) is what prevents the
quiet-wrongness failure mode this codebase has already been burned by once
(the ~90k-character-window defect named in `CLAUDE.md`).

## Tasks

### Task 1 — Guard-test survey (AC 13)
- [x] 1.1 Run the CLAUDE.md-mandated grep across `apps/api/tests/`; list results.

### Task 2 — RED
- [x] 2.1 Write `test_tts_providers_sixtydb.py` against the desired provider
  shape; confirm failing (module doesn't exist yet).
- [x] 2.2 Write the 3 new `test_tts_node.py` cases; confirm failing.

### Task 3 — GREEN: provider + config
- [x] 3.1 `apps/api/app/providers/tts/sixtydb.py` (AC 1-5).
- [x] 3.2 `config.py` settings (AC 6).

### Task 4 — GREEN: chain wiring + frozen contract
- [x] 4.1 `_synthesize_with_fallback()` reorder (AC 7).
- [x] 4.2 `AudioProvider` enum, 3 files (AC 8) — flag 4-dev review requirement.
- [x] 4.3 `.env.example` fix (AC 9).
- [x] 4.4 `docs/DEFECT-REGISTER.md` D168 entry (AC 10).

### Task 5 — GREEN: tests green, full regression
- [x] 5.1 Confirm Task 2's tests pass (AC 11, 12).
- [x] 5.2 Full regression + ruff/format/mypy (AC 14).

### Task 6 — Review
- [x] 6.1 6-layer review complete (AC 15) — 4-developer frozen-contract sign-off still outstanding (not a task this story can perform).

### Task 7 — Commit
- [x] 7.1 Story-first commit (this file alone).
- [ ] 7.2 Implementation commit(s).
- [ ] 7.3 `docs/dev1-tracker.md` entry referencing #232.

## Dev Agent Record

### Debug Log
- Live verification call made 2026-09-21 against `https://api.60db.ai/tts-synthesize`
  (real key/voice_id, short test sentence) — see Context & Scope Boundary for
  the full corrected-scope finding. Raw response: single JSON object,
  top-level `audioContent` + `conditioning` keys, zero timing-keyword hits.
- **AC 13 guard-test survey (Acceptance Auditor review finding: was checked
  `[x]` without the required grep output actually recorded here — fixed).**
  `grep -rln "test_.*tts\|test_no_hardcoded\|test_dunder_all" apps/api/tests/`:
  `test_dna_fusion.py`, `test_dna_profile.py`, `test_ces_baseline.py`,
  `test_dna_growth.py`, `test_ces.py`, `test_email_provider.py` (all
  content-pipeline/DNA/CES/email guard tests — unrelated to `providers/tts/`,
  confirmed unaffected by inspection, not run); `test_tts_providers_sixtydb.py`,
  `test_tts_node.py`, `test_sarvam_chunking.py`, `test_breaker_accounting.py`,
  `test_node_return_shape.py`, `test_audio_duration_s3_38.py` (all directly
  relevant — run explicitly, see Completion Notes for pass counts);
  `tests/conftest.py` (false-positive match — the grep hit its own docstring
  text mentioning "test_tts_node.py" as a cross-reference, not an actual
  guard-test assertion).

### Completion Notes

Implemented `SixtyDbTTSProvider` (`apps/api/app/providers/tts/sixtydb.py`) as
a new `TTSProvider` — REST `/tts-synthesize`, chunked at 5000 chars/request,
dual-shape NDJSON parsing (verified top-level `audioContent`, defensive
`result.audioContent` fallback), raw-PCM concatenation wrapped in one WAV
header at 48kHz/mono/16-bit, circuit breaker + retry matching Sarvam/Azure.
Wired into `_synthesize_with_fallback()` (`graph.py`) as the new first tier:
60db → Sarvam → Azure → Browser. Added `sixtydb_*` settings to `config.py`
(all optional/defaulted so an unconfigured deployment degrades gracefully).
Added `"sixtydb"` to the frozen `AudioProvider` enum in `schemas/lesson.py`,
`packages/shared/types/lesson.ts`, `packages/shared/lesson_package.schema.json`
— flagged for the required 4-developer review. Fixed `.env.example`'s
pre-existing gap (missing Sarvam/Azure vars, stale ElevenLabs entry) in the
same change. Registered **D168** for the unconfirmed 60db cost-per-char
placeholder.

Full gating-scope regression (`tests/unit tests/integration -m "not postgres"`):
**1514 passed, 6 skipped, 86 deselected, zero failures** before the review
round; re-run clean after the review-round fixes (see below). `ruff check`,
`ruff format --check`, and `mypy app` (repo-wide) all clean vs. `main` (mypy's
4 findings are pre-existing, in files this story never touches — corrected
from an earlier "3" miscount here, see Review Round 3 below).

### Review Round — /code-review, high effort (2026-09-21)

5 findings, all real or reasonably accepted-as-documented:

1. **CONFIRMED, HIGH, FIXED** — a 200 OK response with an empty/whitespace-only
   body (all chunks or one chunk) previously fell through silently: zero
   NDJSON lines meant nothing was appended to `pcm_chunks`, no error raised,
   and `_wrap_pcm_as_wav(b"")` still produced a valid-looking (but silent)
   WAV header — undetectable by `_synthesize_with_fallback`'s `if audio_bytes:`
   check. Exactly the "quiet wrongness" this story's own Scale & Load section
   was written to prevent. **Fix:** raise `RuntimeError` if a chunk's response
   yields zero parsed audio pieces. New test:
   `test_sixtydb_empty_response_body_raises_instead_of_silent_empty_audio`.
2. **CONFIRMED, HIGH, FIXED** — missing `sixtydb_api_key`/`sixtydb_voice_id`
   (the documented, intended default state for any deployment that hasn't
   configured 60db yet — AC 6) raised inside `_synthesize_inner`, which
   `guard_breaker` wraps; `ValueError` isn't classified as a client/infra
   error, so every call recorded a real circuit-breaker failure — 5 calls
   (one lesson with 5+ segments) within 120s would open the `"sixtydb"`
   circuit and fire a Sentry "Circuit breaker OPENED" alert for a config
   choice, not an outage. **Fix:** moved both checks into `synthesize()`,
   before `guard_breaker` is entered — `is_circuit_open`/`record_failure` are
   now never called for this case. New test:
   `test_sixtydb_unconfigured_raises_before_guard_breaker_no_failure_recorded`.
3. **CONFIRMED, MEDIUM, FIXED** — the cost-ceiling downshift record
   (`graph.py`, cost-ceiling branch) still hardcoded `"sarvam/azure"` as the
   tier being skipped, even though 60db is now tried (and skipped) first.
   **Fix:** updated to `"sixtydb/sarvam/azure"`; updated the one test
   asserting the literal string.
4. **PLAUSIBLE, LOW, accepted not fixed** — `_chunk_text` duplicates
   `sarvam.py`'s `_chunk_narration_text` (only `max_chars` differs). Not
   extracted into a shared utility: this story's stated scope explicitly
   keeps `sarvam.py` untouched, and every `providers/tts/*` file is already
   independently self-contained by this codebase's own established pattern.
   Documented in `_chunk_text`'s own docstring (a future chunking fix must be
   applied to both copies) rather than silently left unexplained.
5. **CONFIRMED, LOW, FIXED** — the `_default_sixtydb_unconfigured` autouse
   fixture (docstring included) was duplicated verbatim in both
   `test_tts_node.py` and `test_audio_duration_s3_38.py`. **Fix:** shared
   implementation moved to `tests/conftest.py` as a plain (non-autouse)
   `sixtydb_unconfigured_default()` context manager; each file now has a
   thin 3-line autouse wrapper. Kept non-autouse at the conftest level
   deliberately, so `test_tts_providers_sixtydb.py`'s own dedicated tests
   (which exercise the real class directly) are unaffected.

Re-verification after fixes: `test_tts_providers_sixtydb.py` (11 tests, 2 new),
`test_tts_node.py`, `test_audio_duration_s3_38.py`, `test_sarvam_chunking.py`,
`test_breaker_accounting.py`, `test_node_return_shape.py`, `test_tts_providers.py`
— **116 passed**. Full gating-scope regression re-run — see Change Log.

### Review Round 2 — `/bmad-code-review` (4-layer: Blind Hunter, Edge Case
Hunter, Acceptance Auditor, Scale & Load Hunter), 2026-09-21

Ran on the fully-staged diff (13 files, including the two new files
`git diff HEAD` alone would have missed — staged first for a complete diff).
Findings triaged below; the two most serious were confirmed independently by
two different layers each, which is why they're rated HIGH.

1. **CONFIRMED, HIGH, FIXED (found independently by both Edge Case Hunter and
   Scale & Load Hunter, with the latter providing exact arithmetic)** —
   `@with_retry(max_attempts=3)` decorated `_synthesize_inner` as a whole, so
   a transient failure on chunk N re-sent (and would re-bill, per 60db's
   wallet-credit model) every already-succeeded chunk 1..N-1, while cost was
   computed once from `len(text)` regardless of how many real HTTP calls were
   made. Scale & Load Hunter's worked example: one retried chunk on a real
   ~4,000-char segment undercounts recorded cost by ~2x against the
   $3.00/lesson ceiling — reports success while silently under-billing, the
   exact failure class `docs/SCALE-CONTRACT.md` was written to catch. **Fix:**
   extracted the per-chunk HTTP call into a new `_post_chunk` method,
   individually `@with_retry`-decorated; `_synthesize_inner` itself is no
   longer retried, so a retry only ever resends the one chunk that failed.
   `guard_breaker` still records exactly one outcome per `synthesize()` call
   (Story 2-32 AC-3 preserved — nested retry does not change this). New test:
   `test_sixtydb_retry_on_second_chunk_does_not_resend_first_chunk`. Also
   registered **D169**: the identical structural bug is pre-existing (not
   introduced by this story) in `sarvam.py`, discovered as a byproduct of
   this review — out of this story's scope to fix (Sarvam's file is
   deliberately untouched), so registered for a future story instead of
   silently left unrecorded.
2. **CONFIRMED, MEDIUM, FIXED** — the empty-text guard (`if not chunks: raise
   ValueError`) still lived inside the `guard_breaker`-wrapped body, so an
   empty-text call recorded a real breaker failure for a caller bug, not a
   provider outage — the same class of issue as (and missed by) the first
   review round's fix for missing `api_key`/`voice_id`. **Fix:** moved the
   check into `synthesize()`, before `guard_breaker` is entered, alongside
   the other two config-precondition checks. New test:
   `test_sixtydb_empty_text_raises_before_guard_breaker_no_failure_recorded`.
3. **CONFIRMED, MEDIUM, FIXED (Edge Case Hunter)** — `wave.writeframes()`
   does not validate frame alignment; a truncated/corrupted PCM buffer whose
   byte length wasn't a multiple of channels×sample_width would silently
   produce a "valid-looking" but subtly wrong WAV file. **Fix:** explicit
   `len(combined_pcm) % frame_size` check before wrapping, raises
   `RuntimeError` on misalignment. New test:
   `test_sixtydb_misaligned_pcm_length_raises_runtime_error`.
4. **CONFIRMED, LOW, FIXED (Edge Case Hunter)** — `b64decode()` without
   `validate=True` silently drops non-base64-alphabet characters instead of
   raising; a corrupted/garbled response would decode to wrong-length garbage
   PCM rather than fail loudly. **Fix:** added `validate=True`. New test:
   `test_sixtydb_invalid_base64_raises_instead_of_silently_dropping_chars`.
5. **CONFIRMED, LOW, FIXED (Acceptance Auditor, AC 8)** — the frozen-contract
   review-flag comment was added to `schemas/lesson.py` and `lesson.ts` but
   not to `packages/shared/lesson_package.schema.json`, only 2 of the 3 files
   AC 8 requires. **Fix:** added a `"$comment"` to the JSON Schema's
   `audio_provider` enum matching the other two files' wording.
6. **CONFIRMED, LOW, FIXED (Acceptance Auditor, AC 13)** — the guard-test
   survey was checked `[x]` without its required grep output ever being
   recorded in the Debug Log. **Fix:** added the actual `grep -rln` output
   and per-file disposition to the Debug Log (see above).
7. **CONFIRMED, LOW, strengthened not code-fixed (Scale & Load Hunter)** —
   the pre-existing `max_narration_chars_per_lesson` cap's 80%-of-ceiling
   headroom arithmetic (D78) was derived against Sarvam's real rate and never
   re-derived now that 60db (unconfirmed, different billing model) is the
   first tier tried. Same root cause as D168, not a separate code change —
   **D168's register entry was expanded** to name this explicitly and its
   trigger now also covers re-deriving the 120,000-char cap once 60db's real
   rate is confirmed.
8. **PLAUSIBLE, LOW, considered and reverted (Blind Hunter)** — flagged
   `settings.sixtydb_voice_id or ""` at the `_synthesize_with_fallback` call
   site as a "confusing double-indirection" against `synthesize()`'s own
   `voice_id or self._voice_id_default` fallback. Attempted a simplification
   (`settings.sixtydb_voice_id` passed directly) but reverted it: the ABC's
   `synthesize(text: str, voice_id: str)` is non-Optional, so passing the raw
   `str | None` would be a real `mypy` violation. Left as-is with a comment
   explaining why, since the "fix" would have traded a harmless style nit for
   a real type-safety regression.
9. **Considered, not acted on** — Blind Hunter's concern that the NDJSON
   parser assumes compact single-line JSON and could break on a
   pretty-printed response: refuted by this story's own live verification
   call, which returned genuinely compact single-line JSON, not
   pretty-printed — evidence outweighs the theoretical concern. Edge Case
   Hunter's oversized-single-"word"-chunk edge case: inherited verbatim from
   `sarvam.py`'s identical chunker (out of scope, same reasoning as finding
   4 in Review Round 1) and fails loud (413 → caught → falls through to
   Sarvam) rather than silently, so it doesn't violate the Scale Contract's
   one-line test even though it's a real latent gap. Both Blind Hunter's and
   Edge Case Hunter's "unbounded chunk count / no overall per-segment time
   budget" findings: real, but the same shape already exists (worse, at
   Sarvam's smaller 500-char limit) in production today — not a new
   regression this story introduces, and fixing it well is a broader
   per-node-timeout design decision out of this story's scope.

Re-verification after Round 2 fixes: `test_tts_providers_sixtydb.py` (15
tests, 4 new) — all pass. `ruff check`/`ruff format --check` clean on all
re-touched files; `mypy` was run scoped to touched files only in this round
(3 pre-existing findings visible at that scope) — **Review Round 3 caught
that this violated CLAUDE.md binding rule 1 ("verification scope = CI
scope") and found a 4th pre-existing error (`providers/stt/whisper.py`) only
visible under the full repo-wide `mypy app` command.** Full gating-scope
regression re-run — see Change Log.

### Review Round 3 — the 4 remaining CLAUDE.md layers (Story Quality, Test
Coverage, AC Completeness, Process Integrity), 2026-09-22

Round 2 ran only the `/bmad-code-review` skill's 4 built-in layers. This
round supplies the 4 CLAUDE.md names not covered by that skill (per
CLAUDE.md's own text: "only Blind Hunter and Scale & Load appear in both
lists... Story Quality, Test Coverage, AC Completeness and Process Integrity
must be supplied by the invoking prompt") — completing all 6 required layers.

**Process Integrity: PASS, no findings.** Provider abstraction, no-hardcoded-
models, node-return-shape, frozen-contract consistency (all 3 files, honestly
flagged), Defect Register format, and the guard-test survey all independently
re-verified against the real code/commits, not the story's prose.

**AC Completeness: 11 COVERED, 3 PARTIAL, 0 MISSING.** AC 8 (frozen enum),
AC 9 (`.env.example` contents), and AC 10 (D168 register entry) each have a
real underlying artifact but no *explicit test assertion* — reasonable for
AC 10 (a prose registry entry), but AC 8 and AC 9 were closeable with a
trivial test. **Fixed:** added
`test_narration_audio_provider_accepts_sixtydb` (`test_lesson_schema.py`,
validates both the Pydantic model and the raw JSON schema) and
`test_env_example_has_tts_chain_vars_and_no_stale_elevenlabs`
(`test_env_example_consistency.py`, asserts all 11 new keys present and
`ELEVENLABS_*` absent).

**Test Coverage: solid, 3 minor gaps, no mock-echo false confidence found.**
Every branch in `sixtydb.py` has a dedicated exercising test; the reviewer
mentally reverted the per-chunk-retry fix and confirmed
`test_sixtydb_retry_on_second_chunk_does_not_resend_first_chunk` would
actually catch the regression. **Fixed:** `test_sixtydb_missing_voice_id_raises_value_error`
now also asserts `is_circuit_open`/`record_failure` are never called (parity
with its `api_key` sibling test); `test_sixtydb_success_produces_nested_narration_entries`
(`test_tts_node.py`) now asserts the actual `cost` value passed to
`accumulate_cost`, not just `audio_provider`.

**Story Quality: PASS, one factual discrepancy found and fixed.** Story-First
Gate genuinely chronological (verified via `git show --stat` on the story-first
commit — one file, no code); every AC spot-checked against the real diff, not
rubber-stamped; all 15 ACs concrete and falsifiable; every claimed command
re-run independently and matched — **except** `mypy`: the story claimed "3
pre-existing findings," but an independent repo-wide `mypy app` run (matching
CLAUDE.md binding rule 1, "verification scope = CI scope") found **4** —
`providers/stt/whisper.py` was invisible in every prior run because those
runs were scoped to only the files this story touches, not the full app.
Confirmed via a clean check of `main` at the merge-base: `main` already has
all 4, so this is not a new regression, only a miscount in this story's own
prose. **Fixed:** corrected "3" → "4" everywhere it appeared in this file.

**Byproduct finding, out of scope, registered not fixed:** while adding this
round's new tests to two shared, pre-existing test files
(`test_lesson_schema.py`, `test_env_example_consistency.py`), the full run of
`test_env_example_consistency.py` surfaced that its own pre-existing generic
guard (`test_env_example_matches_settings_defaults_or_is_a_documented_exception`)
**already fails on `main`** — `.env.example`'s `CES_WEIGHT_*` values drifted
from `config.py`'s real defaults, unrelated to anything this story touches.
Not caught by CI because this test file lives in the advisory bucket
(`continue-on-error: true`), exactly the trap CLAUDE.md warns about ("a green
checkmark does NOT mean the advisory bucket is clean"). Registered as
**D170**, per CLAUDE.md's own rule for a pre-existing-on-main failure ("note
it... If yes [pre-existing], note it in the PR description") — not fixed
here, since it's a CES calibration question with no relationship to TTS.

Re-verification after Round 3 fixes: `test_lesson_schema.py` (35 tests, 1
new), `test_tts_providers_sixtydb.py` (15 tests, assertions strengthened),
`test_tts_node.py` (assertions strengthened), `test_env_example_consistency.py`
(1 new test; the pre-existing D170 failure remains, correctly, since it's out
of scope) — all pass except the pre-existing D170 case. `mypy app`
(repo-wide, corrected scope): **4** pre-existing errors, zero new. Full
gating-scope regression re-run — see Change Log.

### Review Round 4 — independent PR reviewer (fresh agent, zero prior
context, given only PR #240's URL), 2026-09-22

Rounds 1-3 were all authored by the same identity (this story, its
implementation, and every review round so far — the reviewer explicitly
flagged this: "self-review wearing role labels... not independent review").
This round used a genuinely fresh agent with no memory of Rounds 1-3's
conclusions, asked to review PR #240 from scratch as a skeptical senior
engineer and independently re-run every verification claim rather than
trust the story's prose.

**Verdict: Comment-only / cannot approve for merge as-is** — correctly so;
the frozen-contract 4-developer sign-off is a hard organizational gate no
amount of code review satisfies, and this PR itself says so.

**Findings, both real and both fixed:**

1. **CONFIRMED, MEDIUM, FIXED** — `_synthesize_with_fallback`'s except clause
   logged every 60db failure at WARNING with a full traceback, including the
   expected/common "not configured" `ValueError` case. Since 60db is tried
   FIRST, this meant a WARNING + traceback on every single narration segment
   in every deployment that hasn't yet set `SIXTYDB_API_KEY`/`SIXTYDB_VOICE_ID`
   — i.e. every deployment today — directly contradicting this story's own
   "degrades to today's exact behavior" claim. Neither this story's own 3
   review rounds nor the earlier `/code-review` pass caught it. **Fix:** added
   a specific `except ValueError` branch (the only exception type
   `SixtyDbTTSProvider.synthesize()` raises for config-precondition failures)
   logging at DEBUG with no traceback; genuine failures still hit the
   `except Exception` branch at WARNING+`exc_info`. New test:
   `test_sixtydb_not_configured_logs_quietly_not_a_warning_with_traceback`
   (asserts via `caplog` that no WARNING-or-above record mentions "60db" in
   this path, and the DEBUG record carries no `exc_info`).
2. **CONFIRMED, LOW, FIXED** — `tests/conftest.py`'s
   `sixtydb_unconfigured_default` docstring justified the fixture by claiming
   the missing-config `ValueError` would reach `guard_breaker` and attempt a
   real Redis connection — stale, since Round 2 had already moved that check
   before `guard_breaker` is entered. **Fix:** corrected the docstring to
   state the fixture's actual remaining value (explicit, ambient-env-state-
   independent test behavior) rather than the now-false original claim.
3. **CONFIRMED, MEDIUM, FIXED (process gap, not a code bug)** — two of this
   story's own "accepted, not fixed" review findings were closed without the
   `D-nn` register ID CLAUDE.md's binding rules require: the `_chunk_text`
   duplication (Round 1 finding 4) violates binding rule 5 (no register ID
   at all), and the unbounded-chunk-count finding (Round 2 finding 9) was
   explicitly closed using "matches existing pattern in Sarvam" — the exact
   justification binding rule 6 names and forbids. Both are real: this
   story applied CLAUDE.md's rules inconsistently even while applying them
   correctly elsewhere (D168-D170). **Fix:** registered **D173** (chunker
   duplication) and **D174** (unbounded chunk count / no per-segment time
   budget, cross-referencing Sarvam's identical, worse, previously-unregistered
   gap), and added inline `D173`/`D174` comment references at both code
   sites, matching how D168 is already referenced in `COST_PER_CHAR`'s
   comment.

**Findings assessed and not acted on:** the reviewer's core organizational
point — self-review across 3 rounds is not a substitute for the 4-developer
sign-off — is correct and already disclosed (AC 15, this file's Change Log);
no code action closes it, only the actual human review CLAUDE.md requires.

Re-verification after Round 4 fixes: `test_tts_node.py`,
`test_tts_providers_sixtydb.py`, `test_audio_duration_s3_38.py` (61 tests,
1 new) — all pass. `ruff check`/`ruff format --check` clean; `mypy app`
(repo-wide) — 4 pre-existing/0 new (unchanged). Full gating-scope regression
re-run: **1522 passed, 6 skipped, 86 deselected, zero failures** (up 1 from
Round 3's 1521 — the new log-level test).

### Merge + Review Round 5 — real human reviewer (Developer-2-max) + a merge
conflict with `main`, 2026-09-22

PR #240 attracted its first genuinely independent HUMAN review (not an
agent), and `main` advanced (PR #238, chapter-context form) creating a real
merge conflict. Both handled in this round.

**Merge:** `origin/main` merged in. Only real conflict: `docs/dev1-tracker.md`
(a "Last updated" line both branches touched) — resolved by combining both
notes. `apps/api/app/modules/content/pipeline/graph.py` auto-merged cleanly
(PR #238's changes and this story's are in disjoint regions of that file).
**Real ID collision found and fixed:** PR #238's own Story S5-3 independently
registered **D171**/**D172** for unrelated findings, colliding with this
story's own D171/D172 (Round 2/3). Per the register's own established
collision convention (the later-merging entries are renumbered), this
story's two entries were renumbered to **D173**/**D174** everywhere — the
register, this story file, and the two inline code comments in `sixtydb.py`.
**Also found as a merge-quality issue (not a conflict, but silently wrong):**
this story's own new tests still used the pre-236-rename `narration_scripts`
override key in `_base_state(...)` calls; the merge correctly combined both
branches' text with no conflict markers, but story 236's `narration_scripts`
→ `narration_scripts_final` rename meant those overrides silently stopped
taking effect (the full 2-segment default state was used instead of the
intended 1-segment override) — caught immediately by 2 tests failing after
the merge, not a silent runtime bug, but exactly the "clean merge, wrong
semantics" trap this codebase's own binding rules warn about. Fixed all 5
call sites. Also found: the shared `sixtydb_unconfigured_default()` test
fixture (`conftest.py`) raised bare `ValueError`, which no longer matched
`graph.py`'s newly-narrowed `except SixtyDbNotConfiguredError:` (see below) —
fixed to raise the same subclass the real provider raises.

**Human reviewer findings (Developer-2-max, PR #240 comment) — 5 findings,
all confirmed real:**

1. **CONFIRMED, HIGH, FIXED** — `except ValueError:` in
   `_synthesize_with_fallback` was too broad: `json.JSONDecodeError` and
   `binascii.Error` (raised deep inside `_post_chunk` for a genuinely
   CORRUPTED live response) are both real `ValueError` subclasses, so a live
   provider-corruption bug would be silently mislabeled "60db not
   configured" at DEBUG with no traceback — hiding a real, actionable bug
   behind a factually wrong diagnosis. **Fix:** new `SixtyDbNotConfiguredError`
   subclass, raised only by the three deliberate config/caller-bug checks in
   `synthesize()`; `graph.py` now catches that specific subclass instead of
   bare `ValueError`. New tests:
   `test_sixtydb_genuine_corruption_still_logs_loudly_not_mislabeled`
   (graph-level) proves a real `binascii.Error` still logs at WARNING with a
   traceback and is never mislabeled.
2. **CONFIRMED, HIGH, FIXED** — when a multi-chunk segment has
   already-succeeded (already-paid-for, per 60db's wallet-credit billing)
   chunks followed by a chunk that exhausts all retries, the real spend on
   the successful chunks was never recorded anywhere — `_synthesize_with_fallback`
   falls through to Sarvam, whose cost is the only one ever accumulated
   against the $3.00/lesson ceiling. The opposite-direction gap from
   D168/D169's double-billing concern (that one over-counts on retry; this
   one under-counts on permanent failure). **Fix:** new
   `SixtyDbPartialSpendError(RuntimeError)` carrying `partial_cost_usd`,
   raised by `_synthesize_inner` when `chars_completed > 0` at the point of
   failure; `graph.py` catches it specifically, calls `accumulate_cost`
   with the partial amount, then falls through exactly like any other
   failure. New tests: `test_sixtydb_partial_spend_raised_when_later_chunk_fails_permanently`
   (provider-level) and `test_sixtydb_partial_spend_recorded_before_falling_back_to_sarvam`
   (graph-level, asserts the actual `accumulate_cost` call).
3. **CONFIRMED, LOW, acknowledged not changed** — branch is named
   `feature/232-sixtydb-tts-tier`, not the `sprint4/s4-9-{slug}` pattern
   CLAUDE.md's Sprint Task Branch Rule names. Correct per the rule's letter.
   Not renamed: matches the identical precedent already set by issue #236's
   own branch (`feature/236-narration-post-planner-ordering`, also merged
   under this naming style), and this branch was created before S4-9 existed
   as a tracker entry — S4-9 was added to `dev1-tracker.md` retroactively to
   document ad hoc work, not the other way around. Renaming an already-open,
   already-reviewed PR's branch now would be disruptive for no functional
   benefit. Flagged in the PR reply rather than silently accepted or acted on.
4. **CONFIRMED, MEDIUM, FIXED** — the PCM frame-alignment check ran only on
   the final CONCATENATED buffer, so two independently truncated pieces
   whose byte-length parities happen to cancel out (51 + 49 = 100, an exact
   multiple of `frame_size=2`) would pass even though both pieces are
   individually corrupted. **Fix:** each piece is now validated immediately
   after decoding, inside `_post_chunk`, before it ever reaches the combined
   buffer — no combination of corrupted pieces can cancel out anymore. The
   original combined-buffer check is kept as defense-in-depth, re-commented
   to reflect it's no longer the primary guard. New test:
   `test_sixtydb_two_misaligned_pieces_that_cancel_out_still_raise`.
5. **CONFIRMED, LOW, FIXED** — `tts_node`'s own docstring still said "Sarvam
   -> Azure -> Browser Speech", not updated when the 60db tier was added,
   even though `_synthesize_with_fallback`'s docstring immediately above its
   definition in the same file was correctly updated at the same time.
   **Fix:** corrected `tts_node`'s docstring; also found and fixed the same
   staleness in `config.py`'s `# Fallback chain: Sarvam → Azure → Browser
   Speech` comment and `sarvam_api_key`'s "primary TTS" description (now
   "fallback #1 TTS (was primary before 60db)") while checking for other
   instances.

Re-verification after Round 5 fixes: `test_tts_node.py` (23 tests, 2 new),
`test_tts_providers_sixtydb.py` (19 tests, 2 new), plus the full merged
suite — all pass. `ruff check`/`ruff format --check` clean; `mypy app`
(repo-wide) — 4 pre-existing/0 new. Full gating-scope regression re-run
after the merge: **1557 passed, 6 skipped, 86 deselected, zero failures**
(up from 1522 pre-merge — includes PR #238's own ~35 new tests).

### File List
- `apps/api/app/providers/tts/sixtydb.py` — NEW.
- `apps/api/app/config.py` — MODIFIED: `sixtydb_*` settings.
- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED:
  `_synthesize_with_fallback()` (60db first tier); cost-downshift label fix.
- `apps/api/app/schemas/lesson.py` — MODIFIED: `AudioProvider` +`"sixtydb"`.
- `packages/shared/types/lesson.ts` — MODIFIED: `AudioProvider` +`"sixtydb"`.
- `packages/shared/lesson_package.schema.json` — MODIFIED: same enum.
- `.env.example` — MODIFIED: added Sarvam/Azure/60db vars, removed stale
  ElevenLabs entry.
- `docs/DEFECT-REGISTER.md` — MODIFIED: **D168** entry (expanded in Round 2),
  new **D169** (Sarvam's pre-existing analogous retry/cost bug), new **D170**
  (pre-existing `.env.example`/`config.py` CES weight drift on `main`, found
  as a Round 3 byproduct), new **D173** (unregistered chunker-duplication
  finding), new **D174** (unregistered unbounded-chunk-count finding, closed
  with a CLAUDE.md-forbidden justification) — both D173/D174 from Round 4.
- `apps/api/tests/unit/test_lesson_schema.py` — MODIFIED: new
  `test_narration_audio_provider_accepts_sixtydb` (AC 8).
- `apps/api/tests/test_env_example_consistency.py` — MODIFIED: new
  `test_env_example_has_tts_chain_vars_and_no_stale_elevenlabs` (AC 9).
- `apps/api/tests/unit/test_tts_providers_sixtydb.py` — NEW.
- `apps/api/tests/unit/test_tts_node.py` — MODIFIED: 3 new fallback-order
  tests, autouse fixture (thinned to conftest wrapper), downshift-label fix.
- `apps/api/tests/unit/test_audio_duration_s3_38.py` — MODIFIED: autouse
  fixture (thinned to conftest wrapper).
- `apps/api/tests/conftest.py` — MODIFIED: shared
  `sixtydb_unconfigured_default()` context manager; now raises
  `SixtyDbNotConfiguredError` (Round 5 fix).
- `docs/stories/232-sixtydb-tts-tier.md` — this file.

**Round 5 additions (same files re-touched, plus none new):**
`sixtydb.py` (+`SixtyDbNotConfiguredError`, +`SixtyDbPartialSpendError`,
per-piece PCM alignment check in `_post_chunk`), `graph.py` (narrowed
except clause, partial-spend handling, 2 stale-docstring fixes),
`config.py` (2 stale fallback-chain comments fixed), `test_tts_node.py`
(+2 tests), `test_tts_providers_sixtydb.py` (+2 tests), `docs/DEFECT-REGISTER.md`
(D171/D172 → D173/D174 renumbering, no new entries this round).

### Change Log
- 2026-09-21: Story file created (story-first commit), branch
  `feature/232-sixtydb-tts-tier`. Scope corrected from the original issue text
  (word-level timestamps dropped — confirmed not to exist via live API call).
- 2026-09-21: Implementation complete. Full gating-scope regression (1514
  passed, zero failures), `ruff check`/`ruff format --check`/`mypy app` clean.
- 2026-09-21: `/code-review` (high effort) — 5 findings, 4 fixed, 1 accepted
  and documented (see Review Round above). Re-verified clean after fixes.
- 2026-09-22: `/bmad-code-review` run — the skill's 4 built-in layers only
  (Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter).
  **Not the full 6-layer gate CLAUDE.md requires**: per CLAUDE.md's own text,
  only Blind Hunter and Scale & Load overlap by name with the 6 required —
  Story Quality, Test Coverage, AC Completeness, and Process Integrity (4,
  not 3 as first noted here) still needed to be supplied separately. 9
  findings triaged from the 4 layers that did run, 6 fixed (including a
  HIGH-severity cost-integrity bug confirmed independently by two layers), 1
  strengthened via the defect register, 2 considered and correctly left
  as-is (see Review Round 2 above). New **D169** registered for an identical
  pre-existing bug discovered in Sarvam's own provider file, out of this
  story's scope to fix. Full gating-scope regression re-run after fixes:
  **1520 passed, 6 skipped, 86 deselected, zero failures**; `ruff
  check`/`ruff format --check` clean; `mypy` (run scoped to touched files
  only — a mistake caught and corrected next round) showed 3 pre-existing
  errors.
- 2026-09-22: Ran the 4 remaining CLAUDE.md-named layers (Story Quality, Test
  Coverage, AC Completeness, Process Integrity) — **all 6 required layers
  now complete.** Process Integrity: clean PASS. AC Completeness: 11
  covered, 3 partial, 0 missing — closed 2 of the 3 partials with new tests
  (`test_narration_audio_provider_accepts_sixtydb`,
  `test_env_example_has_tts_chain_vars_and_no_stale_elevenlabs`). Test
  Coverage: solid, no mock-echo false confidence, 2 minor gaps closed
  (voice_id breaker-not-tripped assertion, 60db cost-value assertion). Story
  Quality: PASS, but caught a real discrepancy — the mypy pre-existing-error
  count was reported as "3" in three places, when an independently-run,
  correctly-scoped **repo-wide** `mypy app` (matching CLAUDE.md binding rule
  1: "verification scope = CI scope") found **4** — `providers/stt/whisper.py`
  was invisible in every prior run because those runs were scoped to touched
  files only. Confirmed via `main` at the merge-base: all 4 pre-exist there
  too, so not a new regression, only a miscount in this story's own prose —
  corrected everywhere it appeared. **Byproduct finding, registered not
  fixed:** adding this round's tests to two shared pre-existing test files
  surfaced that `.env.example`'s `CES_WEIGHT_*` values already drift from
  `config.py`'s real defaults **on `main`**, unrelated to this story —
  registered as **D170** per CLAUDE.md's rule for pre-existing-on-main
  failures. Full gating-scope regression re-run: **1521 passed, 6 skipped,
  86 deselected, zero failures** (up 1 from Round 2's 1520 — the new
  `test_narration_audio_provider_accepts_sixtydb`); repo-wide `mypy app`
  corrected to **4** pre-existing/zero-new.
  Remaining before merge (cannot be satisfied by this story alone): a human
  read of this review's findings/fixes, and the 4-developer sign-off
  required for the frozen `AudioProvider` contract change.
- 2026-09-22: PR #240 opened against `main`. A genuinely independent
  reviewer (fresh agent, no memory of Rounds 1-3, reviewing only PR #240's
  content) found 3 real gaps Rounds 1-3 missed — a log-noise bug (every
  segment in every unconfigured deployment logged a WARNING+traceback for
  the expected "not configured" case), a stale fixture docstring, and 2
  review findings closed without the `D-nn` register ID CLAUDE.md's own
  binding rules 5/6 require (one of them closed using the exact
  justification rule 6 explicitly forbids). All 3 fixed; **D173**/**D174**
  registered. The reviewer's core point — 3 rounds of self-review by the
  same author is not a substitute for the mandated 4-developer sign-off —
  stands and is unchanged: still the one blocker only your team can clear.
  Full gating-scope regression re-run: **1522 passed, 0 failures.**
- 2026-09-22: Merged `origin/main` (PR #238 landed) — one real conflict
  (`docs/dev1-tracker.md`, resolved), one real D-number collision found and
  fixed (**D171/D172 renumbered to D173/D174** — PR #238's own Story S5-3
  independently claimed D171/D172 first), and one merge-quality bug found
  and fixed (this story's tests silently stopped overriding narration
  scripts correctly after story 236's key rename — no conflict marker, just
  silently wrong, caught by 2 failing tests). A real human reviewer
  (Developer-2-max) then left 5 findings on the PR — all 5 confirmed real,
  4 fixed (a `except ValueError` too-broad bug that could mislabel genuine
  response corruption as "not configured"; a partial-spend-never-recorded
  cost-integrity gap, the mirror image of D168/D169's over-counting concern;
  a frame-alignment check that could be defeated by two corrupted pieces
  cancelling out; two stale docstrings/comments), 1 acknowledged and not
  changed (branch naming — matches issue #236's own precedent, reasoned in
  a PR reply rather than silently accepted). Full gating-scope regression
  after the merge and all fixes: **1557 passed, 0 failures.**
