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
- [ ] **AC 1.** `SixtyDbTTSProvider.synthesize(text, voice_id)` implements
  `TTSProvider`, applies circuit breaker (`"sixtydb"` key) and the same
  `@with_retry(max_attempts=3)` pattern as Sarvam/Azure, returns
  `(audio_bytes, [])`.
- [ ] **AC 2.** Text over 5000 chars is chunked (sentence-boundary preferred,
  word-boundary fallback for an oversized single sentence — same approach as
  Sarvam's `_chunk_narration_text`, `max_chars=5000`), one `/tts-synthesize`
  request per chunk, sequential (not concurrent — same per-key rate-limit
  reasoning as Sarvam).
- [ ] **AC 3.** Each response body is parsed defensively: split on newlines
  (NDJSON-tolerant), each non-empty line parsed as JSON; `audioContent` is read
  from the top level first (verified live shape), falling back to
  `result.audioContent` if the top-level key is absent (documented shape,
  unverified for variance) — raises a clear `RuntimeError` if neither shape
  yields an `audioContent` value.
- [ ] **AC 4.** All decoded base64 PCM chunks (raw LINEAR16, no WAV header) are
  concatenated as raw bytes (valid for PCM, unlike complete-WAV-file
  concatenation), then wrapped in exactly one WAV header at 48000 Hz / mono /
  16-bit at the end.
- [ ] **AC 5.** `synthesize()` always returns `(audio_bytes, [])` — the empty
  list documented as "60db's TTS response carries no timing data (confirmed
  live, 2026-09-21) — see Context & Scope Boundary," not left as an
  unexplained empty default like Sarvam/Azure's (theirs is "deferred", this
  one is "confirmed absent").
- [ ] **AC 6.** `config.py` gains `sixtydb_api_key: str | None = None`,
  `sixtydb_voice_id: str | None = None`, `sixtydb_model: str = "60db-quality"`,
  `sixtydb_speed: float = Field(default=1.0, ge=0.5, le=2.0)`,
  `sixtydb_enhance: bool = True`. Missing key/voice_id raises inside the
  provider (clear `ValueError`), caught by `_synthesize_with_fallback`'s
  existing `except Exception` — falls through to Sarvam exactly like an Azure
  auth failure does today. No crash for a deployment with no 60db key set.
- [ ] **AC 7.** `_synthesize_with_fallback()` tries 60db first, Sarvam second,
  Azure third, browser last — same "log + fall through" shape as the existing
  Sarvam→Azure transition; returns `(audio_bytes, "sixtydb", cost)` on success.
- [ ] **AC 8.** `AudioProvider` gains `"sixtydb"` in `schemas/lesson.py`,
  `packages/shared/types/lesson.ts`, `packages/shared/lesson_package.schema.json`
  — all three edited together, comment on each noting the 4-developer review
  requirement before merge.
- [ ] **AC 9.** `.env.example` gets `SARVAM_API_KEY`, `SARVAM_VOICE_ID`,
  `SARVAM_NARRATION_PACE`, `AZURE_TTS_KEY`, `AZURE_TTS_REGION`,
  `AZURE_TTS_VOICE` (all currently missing), `SIXTYDB_API_KEY`,
  `SIXTYDB_VOICE_ID`, `SIXTYDB_MODEL`, `SIXTYDB_SPEED`, `SIXTYDB_ENHANCE`; the
  stale `ELEVENLABS_API_KEY` line is removed (matches `config.py`'s own
  "deprecated, replaced by Sarvam" note — the var itself still exists in
  `config.py` as an inert optional field, only the `.env.example` line is
  stale/misleading and is what this AC fixes).
- [ ] **AC 10.** `docs/DEFECT-REGISTER.md` gains a **D168** entry for the
  unconfirmed 60db per-character cost rate (placeholder = Sarvam's rate).

### Tests
- [ ] **AC 11.** New `apps/api/tests/unit/test_tts_providers_sixtydb.py`:
  success (single chunk), success (multi-chunk >5000 chars, PCM concatenation
  correctness), top-level `audioContent` shape, fallback `result.audioContent`
  shape, malformed-response `RuntimeError`, circuit-breaker-open rejection,
  missing key/voice_id `ValueError`, retry-then-succeed. Real fixture PCM/WAV
  bytes, no live network calls — same conventions as
  `test_tts_providers.py`.
- [ ] **AC 12.** `test_tts_node.py` gains: 60db-succeeds-first case,
  60db-fails-falls-to-sarvam case, 60db-not-configured-falls-to-sarvam case.

### Process
- [ ] **AC 13.** Guard-test survey run (CLAUDE.md rule) before implementation:
  `grep -rn "test_.*tts\|test_no_hardcoded\|test_dunder_all" apps/api/tests/` —
  results listed in Dev Agent Record.
- [ ] **AC 14.** Full gating-scope regression
  (`tests/unit tests/integration -m "not postgres"`) shows zero new failures
  vs. `main`. `ruff check .`, `ruff format --check`, `mypy app` clean vs. `main`.
- [ ] **AC 15.** 6-agent `/bmad-code-review` completed before merge — **and**,
  because this diff touches a frozen contract (AC 8), a PR reviewed by all 4
  developers per CLAUDE.md's frozen-contract rule, in addition to the 6-agent
  review. Both are merge blockers this story cannot itself satisfy — recorded
  here as an explicit open item, not silently assumed done.

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
- [ ] 1.1 Run the CLAUDE.md-mandated grep across `apps/api/tests/`; list results.

### Task 2 — RED
- [ ] 2.1 Write `test_tts_providers_sixtydb.py` against the desired provider
  shape; confirm failing (module doesn't exist yet).
- [ ] 2.2 Write the 3 new `test_tts_node.py` cases; confirm failing.

### Task 3 — GREEN: provider + config
- [ ] 3.1 `apps/api/app/providers/tts/sixtydb.py` (AC 1-5).
- [ ] 3.2 `config.py` settings (AC 6).

### Task 4 — GREEN: chain wiring + frozen contract
- [ ] 4.1 `_synthesize_with_fallback()` reorder (AC 7).
- [ ] 4.2 `AudioProvider` enum, 3 files (AC 8) — flag 4-dev review requirement.
- [ ] 4.3 `.env.example` fix (AC 9).
- [ ] 4.4 `docs/DEFECT-REGISTER.md` D168 entry (AC 10).

### Task 5 — GREEN: tests green, full regression
- [ ] 5.1 Confirm Task 2's tests pass (AC 11, 12).
- [ ] 5.2 Full regression + ruff/format/mypy (AC 14).

### Task 6 — Review
- [ ] 6.1 6-agent `/bmad-code-review` (AC 15).

### Task 7 — Commit
- [ ] 7.1 Story-first commit (this file alone).
- [ ] 7.2 Implementation commit(s).
- [ ] 7.3 `docs/dev1-tracker.md` entry referencing #232.

## Dev Agent Record

### Debug Log
- Live verification call made 2026-09-21 against `https://api.60db.ai/tts-synthesize`
  (real key/voice_id, short test sentence) — see Context & Scope Boundary for
  the full corrected-scope finding. Raw response: single JSON object,
  top-level `audioContent` + `conditioning` keys, zero timing-keyword hits.

### Change Log
- 2026-09-21: Story file created (story-first commit), branch
  `feature/232-sixtydb-tts-tier`. Scope corrected from the original issue text
  (word-level timestamps dropped — confirmed not to exist via live API call).
