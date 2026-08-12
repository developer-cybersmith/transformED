# Story 3-40 — Langfuse instrumentation audit (environment, session semantics, naming)

**Branch:** `sprint3/s3-40-langfuse-tracing-audit` (stacked on the unmerged
`sprint3/s3-36-package-builder-defensive-fixes` tip — see "Dependency" below).
**Owner:** Dev 1 (Langfuse is explicitly Dev 1's domain per CLAUDE.md §21).
**Trigger:** User instruction — "Install the Langfuse AI skill from
github.com/langfuse/skills and use it to add tracing to this application
following best practices."

## Dependency (why this branches off s3-36, not `main`)

This story's fix to `_synthesize_with_fallback` in
`apps/api/app/modules/content/pipeline/graph.py` (giving `SarvamTTSProvider`/
`AzureTTSProvider` a `lesson_id` so their new tracing can group under the
lesson's trace) sits inside the exact function Story 3-36 (D32+D33) already
modified and has not yet merged to `main`. Branching from `main` would not
apply cleanly against the pre-3-36 version of that function. This branch
stacks on s3-36's tip instead — a disclosed, deliberate exception to the
default "always branch from main" rule, not an oversight. **s3-36 must merge
before (or in the same PR batch as) this branch.**

## Process note — order of work

Code was written before this story file, breaking the letter of the
story-first gate. Reason: the task was "audit existing instrumentation
against best practices," which is inherently exploratory — the concrete
scope (which files, which gaps) was only known after reading the code and
fetching Langfuse's docs fresh, per the Langfuse skill's own "Documentation
First" principle. This file is written to accurately describe what was
found and fixed, not what was planned in advance, and is committed alone,
before the implementation commit, so the two remain separately reviewable —
honoring the spirit of "never mix story and implementation in one commit"
even though the chronological order was inverted this one time.

## Background

`apps/api/app/core/langfuse.py` provides a process-wide `Langfuse` singleton
(`get_langfuse()`), used by `providers/llm/openai.py`,
`providers/embeddings/openai.py`, `providers/image/{openai_image,imagen}.py`,
`providers/tts/{sarvam,azure}.py`, and
`modules/tutor/state_machine/graph.py`. Tracing was already wired end-to-end
for the LLM/embedding providers (Story S0-9 and later hardening); the TTS
and image providers had zero tracing; the tutor FSM's tracing silently
no-op'd since the Langfuse 4.x upgrade (called a removed `.trace()` method,
swallowed at DEBUG level).

Fetched fresh per the Langfuse skill's "Documentation First" principle
(never audit from memory): `best-practices.md`, `sessions.md`,
`environments.md`, plus the actual pinned SDK (4.14.3, installed at
`/private/tmp/story335-venv`) inspected directly via `inspect.signature()`
for `propagate_attributes`, `Langfuse.__init__`, `start_observation`,
`create_event` — every claim below about what the SDK does or does not
accept a kwarg for is verified against that installed version, not assumed
from the docs (the docs describe capabilities of the *latest* SDK, which
this pinned version does not always match — this bit a prior round, see
`_trace_dispatch`'s docstring history, and is why signatures were
re-verified rather than trusted from docs alone this time too).

## What was already correct (unchanged)

- Global singleton (`get_langfuse()`), thread-safe construction, `flush()`
  wired into FastAPI lifespan shutdown.
- Every provider call already wrapped in a `safe_trace`-equivalent
  swallow-and-log pattern (WARNING, not DEBUG) — an observability outage can
  never fail the pipeline, and stays visible in prod logs when it happens.
- `model=`, `usage_details=`, and (where supported) `cost_details=` set on
  every `generation`/`embedding` observation, mirroring the same
  `response.usage` numbers `cost_tracker.py` uses for the real $3.00/lesson
  ceiling — cross-checkable in the Langfuse UI without ever being a second
  source of billing truth.
- `imagen.py`'s security-critical exception sanitization (API key kept out
  of `__context__`) — re-verified unchanged by this story's edits.
- `deterministic_trace_context(langfuse, lesson_id)` grouping every
  provider call for one pipeline run under one trace — this matches
  best-practices.md's own definition of a good trace scope ("one pipeline
  execution... a document comes in, gets chunked, embedded, and stored" is
  given as a textbook example) and needed no change.

## What was fixed

### AC-1 — `environment` was never set; all traces (dev, test, staging,
production) landed under Langfuse's default `"default"` environment,
indistinguishable in every dashboard/filter.
- Added `Settings.langfuse_environment` (`apps/api/app/config.py`),
  validated against Langfuse's own constraint
  (`^(?!langfuse)[a-z0-9-_]+$`, ≤40 chars — a value outside this is
  *silently dropped* by the SDK; the new `field_validator` turns that into
  a loud `ValueError` at settings-load time instead), default
  `"development"`.
- Wired into the `Langfuse(...)` constructor in `core/langfuse.py`
  (`environment=settings.langfuse_environment`) — confirmed as a real
  constructor kwarg on the pinned SDK via `inspect.signature`, not
  assumed.

### AC-2 — Tutor FSM tracing used the wrong trace scope.
`_trace_dispatch` (`modules/tutor/state_machine/graph.py`) reused
`deterministic_trace_context(langfuse, session_id)` — the same mechanism
that correctly groups a *pipeline run* (one bounded execution) — to group
*every dispatch event of an entire tutor session* (state checks,
interventions, quiz turns, potentially 60+ minutes and dozens of events)
into one ever-growing trace. best-practices.md is explicit that this is the
wrong shape: "If multiple [units of work] happen in sequence... that's
where sessions come in. Each step is its own trace, and the session ties
them together... the per-turn model keeps traces small and easy to
navigate." Fixed: each dispatch is now its own trace (no `trace_context` —
a fresh trace per turn), grouped into one Langfuse **session** via
`propagate_attributes(session_id=session_id)` — the SDK's only documented
mechanism for setting the first-class `session_id` attribute (confirmed via
`inspect.signature(propagate_attributes)` on the pinned SDK: `session_id`
is a real kwarg; `start_observation`/`create_event` are not).

### AC-3 — Observation names were provider-and-model-coupled, not
verb-first.
best-practices.md: "Use active language... verb first" and "Try not to
name observations after the AI model used... All filters, evaluators, and
dashboards that reference the name break as soon as you swap models." Renamed:

| File | Before | After |
|---|---|---|
| `providers/llm/openai.py` | `openai.chat` | `generate-chat-completion` |
| `providers/llm/openai.py` | `openai.chat.structured` | `generate-structured-completion` |
| `providers/embeddings/openai.py` | `openai.embeddings` | `generate-embeddings` |
| `providers/tts/sarvam.py` | `sarvam.tts` | `synthesize-speech` |
| `providers/tts/azure.py` | `azure.tts` | `synthesize-speech` (same name — see below) |
| `providers/image/openai_image.py` | `openai.image` | `generate-image` |
| `providers/image/imagen.py` | `imagen.image` | `generate-image` (same name — see below) |
| `modules/tutor/state_machine/graph.py` | `tutor.dispatch_event` | `dispatch-tutor-event` |

Primary/fallback pairs (Sarvam↔Azure TTS, GPT Image↔Imagen) now share one
name each, distinguished by the existing `model=` attribute
(`bulbul-v2`/`azure-neural-tts`, `gpt-image-1-mini`/`imagen-4-fast`) — this
is the doc's own recommended pattern and means a dashboard/evaluator
targeting "speech synthesis calls" or "image generation calls" sees the
whole fallback chain under one stable name instead of two names that must
each be tracked separately.

### AC-4 — Self-audit loop executed against real traces (not mocked).
Two real, end-to-end calls through `OpenAILLMProvider` with real
credentials (no provider mocking), fetched back from Langfuse Cloud via
`GET /api/public/traces/{id}` and inspected directly:
- `b75cb378cd7eb8afae0b0aff9278b08f` — pre-fix baseline run (confirmed
  `model`, `usage_details`, `cost_details`, error-path tracing all work;
  surfaced the `environment` and naming gaps above).
- `9167b700c08d39c22cd0ac1c56520e16` — post-fix verification run, same
  `lesson_id` seed reused across one earlier same-turn Redis-failure retry
  and one clean success (both landed under the deterministic trace_id, as
  designed) — confirmed `name: "generate-chat-completion"` and
  `environment: "development"` both present on the trace and its
  observation.

## Explicitly NOT fixed here (real gaps, deferred — not silently dropped)

- **Span/parent hierarchy.** best-practices.md also asks "is it nested
  correctly? ... instead of leaving tool calls dangling at the trace root."
  Every provider call in this codebase creates its observation as a flat
  sibling directly under the trace root — there is no intermediate
  span-per-phase or span-per-node. Fixing this needs a `parent_span_id`
  threaded through LangGraph state from the point the graph is invoked
  down into each node's provider construction — a real architecture change
  (state schema + every provider call site), not a tracing-call edit. Not
  attempted in this story. **Recommend a `D-nn` DEFECT-REGISTER entry and a
  dedicated follow-up story** per CLAUDE.md binding rule 5 ("a documented
  limitation is NOT an accepted one").
- **`user_id` / per-student attribution.** best-practices.md recommends
  setting `user_id` for per-user cost/performance views. No provider
  currently receives a user/student id at all (only `lesson_id`) — adding
  it needs the same threading-through-state work as the span hierarchy
  gap. Deferred for the same reason.
- **S3-5 ("Pipeline cost attribution in Langfuse")** is a separate,
  already-planned, narrower story (`docs/dev1-tracker.md`) requiring a
  joined `token_cost_usd` field per span. Not touched here — this story's
  scope was the Langfuse-skill's general best-practices audit, not S3-5's
  specific AC.
- **`sarvam_voice_id="meera"`** default is invalid per Sarvam's live API
  (confirmed via a real 400 response). Unrelated to Langfuse tracing —
  flagged as a real blocker for the eventual L1 acceptance run, not fixed
  in this story.

## Scale & Load

1. **Unit of work & range.** One Langfuse observation call (or one trace).
   Min: 1 call (e.g. a single `embed_texts` batch). Typical: ~10–15 calls
   per lesson (11 pipeline nodes × ~1–2 provider calls each). Largest
   measured/plausible: a tutor session running 60+ minutes with dozens of
   dispatch events — previously all forced into ONE ever-growing trace
   (unbounded observation count per trace); AC-2 bounds this to one small
   trace per dispatch, growth is now per-*session* (via Sessions view, an
   aggregate Langfuse already paginates) rather than per-*trace*.
2. **Fixed budgets vs variable input.** `environment` ≤40 chars,
   `[a-z0-9-_]` only — enforced by a `field_validator` at settings-load
   time (explicit `ValueError`, not the SDK's silent-drop behavior).
   `session_id`/`user_id` ≤200 chars per Langfuse's own constraint — not
   independently validated by this codebase; not practically reachable
   today since `session_id` is always an internal UUID, so N/A with reason
   rather than a silent gap.
3. **Scope of every limit.** `environment` is per-deployment (one
   `LANGFUSE_ENVIRONMENT`/`langfuse_environment` value per Railway
   service/process). Trace/session grouping (`lesson_id`, `session_id`) is
   per-entity — one lesson, one tutor session — never global.
4. **Unbounded reads/writes.** None introduced. This story only changes
   fire-and-forget, best-effort SDK calls (already wrapped in
   `safe_trace`); no new database reads or writes.
5. **Inherited caps re-derived.** The tutor's *old* tracing design
   (`deterministic_trace_context` keyed on `session_id`) was itself an
   inherited copy of the pipeline's `lesson_id` pattern, applied to a
   materially different usage shape (multi-turn, open-ended duration vs.
   one bounded execution) without re-deriving whether the assumption still
   held. AC-2 is exactly that re-derivation, done this story.
6. **Concurrency.** No new check-then-act sequences. Each
   `start_observation()`/`create_event()` call is independent; the OTel-based
   SDK owns its own internal buffering/batching. `propagate_attributes` is a
   context manager scoped to a single `with` block per call — no shared
   mutable state between concurrent dispatches or concurrent pipeline node
   calls.

## Verification

- `ruff check` + `ruff format --check` on all 9 touched files: clean.
- `mypy` on all 9 touched files: 0 new errors (5 pre-existing, unrelated
  `unused-ignore` errors in `core/websocket.py` and
  `modules/tutor/state_machine/graph.py:224` — confirmed via `git diff`
  that `websocket.py` is untouched by this story and line 224 is far from
  any edit here).
- Full relevant test suites: `test_langfuse_sdk_contract.py` (13),
  `test_provider_tracing_resilience.py` (8), `test_notification_prefs.py`
  (12 — confirms the rename does not trip its negative
  no-LLM-identifiers-in-this-module assertion), `test_config_settings.py`
  (15), `test_tutor_graph.py` (48), `test_tutor_service.py` (45). **141/141
  passing, 0 regressions.**
- Two real, non-mocked Langfuse Cloud traces fetched and inspected (AC-4).
