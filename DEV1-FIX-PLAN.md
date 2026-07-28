# Dev1 Final Defect-Closure Plan — TransformED AI

**Date:** 2026-07-28
**Owner:** Dev 1 (infra, content pipeline, all 11 nodes, embeddings, provider abstraction, Langfuse)
**Status:** execution-ready plan, pre-implementation

---

## Can we be done with all of this?

Mostly — but not entirely, and it is worth being precise about the boundary. Dev1 can fully close, in code and with tests: the e2e integration test repair, the intra-run state-duplication defect (the real "16x" — it is `return {**state, ...}` re-emitting `operator.add` channels, *not* thread reuse), the MemorySaver thread leak, the narration-script recovery in `package_builder`, the OpenAI-SDK retry classification gap plus its circuit-breaker and SDK-double-retry consequences, the dead structure-detection LLM block, the `GET /lessons` select narrowing, the S3-6 documentation, and the S4-4 tracker correction. What Dev1 **cannot** close: (a) BUG B is only half a fix — the frontend has no browser-speech path and `AudioTimeline.tsx` auto-skips any segment with an empty `audio_url`, so the student-visible 0:00-quiz symptom stays until Dev2 ships a virtual-playback-clock story; (b) the tutor FSM `state_change` broadcast, CES-state gating and `ws.ts` contract are Dev4's, and `session_id` identity is Dev2+Dev4 joint; (c) S4-4 cannot honestly be marked done — `_get_user_key` fails to decode real Supabase tokens (missing `audience`, no ES256/JWKS branch) so the limiter silently keys on IP, and `RATE_LIMIT_STORAGE_URL` is unset across 2 replicas; (d) three things need a **live run** and cannot be certified from source: the PostgREST JSONB-path `select=` string against the real project, the S1-6 deletion's effect on short PDFs (`short.pdf`, `dense_text.pdf` — the LLM branch *is* reachable below ~6,666 chars, contrary to the "100% dead" claim), and re-measured cost/Langfuse baselines after the duplication fix (current $/lesson figures are inflated ~4x on TTS). So: **Dev1's own backlog can reach zero; the system-level bugs cannot be declared closed without two Dev2 stories, one Dev4 hand-off, and three live verifications.**

---

## DECISIONS LOCKED (2026-07-28)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| 1 | Branching | **3 branches, grouped by risk** | (1) harness+BugA, (2) BugB+cleanup, (3) BugC alone |
| 2 | Structure validation | **Build Story 2-17 properly** | Reverses "delete the dead block". Phase 5 grows. |
| 3 | 2-17 sequencing | **Boundary-quality metric FIRST** | New story before 2-17: add section metric to `tests/evals/scoring.py` |
| 4 | S4-4 rate limiting | **Full fix** (JWT decode + Redis store) | Needs `RATE_LIMIT_STORAGE_URL` provisioned per env — may touch India-region migration |
| 5 | Bunny.net | **Per-lesson video, REVISION ONLY** | Interactive player on first watch; flat video for re-watch. NEW FEATURE WORK — not in this close-out. |

### Scope impact
Original plan: 5 stories. After decisions 2+3+4: **~7 stories**. Decision 5 adds a **separate feature track** (not counted here).

### Decision 5 — required follow-ups BEFORE any video code is written
1. **Rewrite `docs/decisionupdate.md` §7** — it currently states the opposite ("not a per-lesson generated video", "no video file"), still marked CONFIRMED. Leaving it is how this becomes tomorrow's audit finding.
2. **Add the video/transcoding layer to `CLAUDE.md`'s locked stack** — absent today.
3. **Re-cost it.** The ~$2/month figure assumed *encode once*. Per-lesson means transcode+store *every* lesson for the subset that gets rewatched. Re-check against the $3.00/lesson ceiling.
4. **Design the render path.** Nothing exists: slides are React (title+bullets+AI image), so this needs headless-browser slide→frame rendering + ffmpeg mux + Bunny upload, running outside the ARQ `job_timeout` budget (pipeline is already 5–15 min, `max_jobs=5`).
5. **Dev2 hand-off** — a revision-mode player that plays the video instead of the interactive timeline.
6. **4-dev review** — this changes the locked stack.

> **Not on the bug-close-out critical path.** Track separately; do not let it block Sprint 2 close-out.

---

## Scope: what this plan closes

1. **e2e test harness repair + hardening** — `_QuizBatchLLM` branch (already applied, green), dead-branch cleanup, non-vacuous assertions.
2. **BUG A (real root cause):** `return {**state, ...}` in 18 node-return sites doubling all six `operator.add` channels → 2⁴ = 16x per clean run. Plus `_FAN_OUT_STATE_KEYS` missing `"tier"`.
3. **BUG A hygiene:** per-attempt LangGraph `thread_id` + `adelete_thread` eviction (memory bound, not the 16x fix).
4. **BUG B (backend half):** `_fallback_narration(script)` + recovery source; `_index_by_segment_id` `KeyError` hardening.
5. **BUG C:** `with_retry` classifies OpenAI SDK exceptions; `max_retries=0` + explicit timeouts; circuit-breaker accounting moved to logical-call granularity; cost-ceiling `RuntimeError` stops counting as provider ill-health.
6. **S1-6:** delete the unreachable-for-long-docs structure-validation LLM block.
7. **GET /lessons:** narrow `select`, lift `subject` + `estimated_duration_mins`.
8. **S3-6:** document dormancy; do not delete, do not wire.
9. **S4-4:** either fix per-user keying + Redis store, or record it honestly as PARTIAL.
10. **S1-7 / S2-15:** verified REAL; add standing guard tests; fix the two fail-opens found (byte-naive embed truncation, unpriced-model cost bypass).

---

## Explicitly out of scope (and whose it is)

| Item | Owner | Why it is not Dev1's |
|---|---|---|
| Tutor FSM `state_change` broadcast | **Dev 4** | 7-state tutor + WebSocket handlers are Dev4 per §21 |
| CES-state gating (CES only in TEACHING) | **Dev 4** | Guard rules live in the tutor state machine |
| `packages/shared/types/ws.ts` contract | **Dev 4** (+§16 4-dev sign-off) | Frozen Week-1 contract |
| `session_id` identity | **Dev 2 + Dev 4** joint | Spans player client and WS handler |
| Browser-speech / virtual playback clock in `AudioTimeline.tsx` | **Dev 2** | BUG B is not student-visible without it |
| `retryAudio()` re-fetch on signed-URL expiry | **Dev 2** | S2-26 remounts the same expired URL |
| Assessment module factory adoption (`service.py:496,932`, `dna_profile.py:93`) | **Dev 3** | Direct `OpenAILLMProvider` construction outside the pipeline |
| Tutor `state_machine/graph.py` `{**state,...}` returns + un-evicted MemorySaver | **Dev 4** | Same latent bug, different module |
| Story 2-17 boundary-only structure validation | Dev1, **deferred** | Gated on an eval metric that does not yet exist |

**§16 four-dev sign-off required for:** nothing in this plan. Confirmed: no `packages/shared/*` and no `supabase/migrations/*` file is touched. Two things were *considered* and rejected precisely to avoid the gate — emitting `audio_path` alongside `audio_url` (`additionalProperties:false` on `Narration`/`Slide`), and adding list-response types to `types/lesson.ts`. If Phase 6 option (b) is later chosen for chunk idempotency it needs a new migration → gate applies.

---

## Execution plan

### PHASE 0 — Safety net: repair and harden the e2e integration test

*Rationale: this is the only test that drives the real compiled graph. Every subsequent phase is verified through it. It must be green, non-vacuous, and offline before anything else moves.*

**BMAD:** one story — `docs/stories/2-28-e2e-harness-repair-and-duplication-guards.md`. Story-only commit, pushed, then implementation. 5-agent `/bmad-code-review` before merge.

| # | Change | Shape | Test | Effort |
|---|---|---|---|---|
| 0.1 | `apps/api/tests/integration/test_howto_pipeline_e2e.py:~191, ~227` — add `_QuizBatchLLM` dispatch branch (**already applied, verified `2 passed in 4.12s`**) | `if name == "_QuizBatchLLM": return _QuizBatchLLM(questions=[_QuizQuestionLLM(...) for n in range(3)])`, option text distinct per `n` | file re-run green | S |
| 0.2 | Same file — **delete** the now-dead `_QuizQuestionLLM` dispatch branch; keep the import (the new branch constructs it) | remove branch only | tripwire `AssertionError` remains the only path for unmocked formats | S |
| 0.3 | Same file — make the fixture narration script **segment-specific** (currently identical for every segment, so BUG B assertions cannot fail for the right reason) | `f"Narration for {section_id}: ..."` | n/a (enabler) | S |
| 0.4 | Same file — improve the tripwire message and guard `provider.complete` | `provider.complete = AsyncMock(side_effect=AssertionError("e2e fake only mocks complete_structured"))` | n/a | S |
| 0.5 | Same file — add **function-scoped** autouse `_reset_compiled_graph` fixture (snapshot + restore `g._compiled_graph`) | `@pytest.fixture(autouse=True)` — *not* module-scoped; module scope would leak a spied graph between tests | fixture itself | S |
| 0.6 | Same file — add the duplication assertions to the existing happy-path test. **These fail today; that is the point.** | per-segment `2 <= len(seg["quiz"]) <= 3`; global `len(qids) == len(set(qids))`; total `sum(len(s["quiz"])) == 3 * len(segments)`; **and** spy `_LessonPlanLLM`'s prompt: `count("- segment_id=") == len(segments)` | RED now, GREEN after Phase 1 | M |
| 0.7 | Delete stale `apps/api/tests/integration/__pycache__/test_tmp_rerun_probe.cpython-313-pytest-9.1.1.pyc` (the `.py` **does not exist** — do not `git rm` it) | file delete | n/a | S |

> **Sequencing note:** 0.6 makes a currently-green file red. Land 0.6 in the **same PR** as Phase 1, or `xfail` it with an explicit issue reference. Do not merge it alone.

Verification command (system Python cannot even collect):
`apps/api/.venv/Scripts/python.exe -m pytest tests/integration/test_howto_pipeline_e2e.py -q`

---

### PHASE 1 — BUG A: stop nodes re-emitting reducer channels (the actual 16x)

*Rationale: measured, causally proven. `segment_summaries` 15 → 240, `quiz_questions` 45 → 720, 48 quiz per segment. Four post-fan-in nodes each double all six channels. Thread reuse cannot produce 16x — `max_tries=3` caps it at 3x.*

**BMAD:** story `docs/stories/2-29-pipeline-state-duplication-fix.md`, alone-commit first. 5-agent review.

| # | Change | Shape | Test | Effort |
|---|---|---|---|---|
| 1.1 | `apps/api/app/modules/content/pipeline/graph.py` — strip `**state,` from **18** return sites: 250, 427 (multiline spreads in `extract_node` — the naive `return {**state, ` regex misses these), 492, 595, 637, 723, 779, 965, 1194, 1394, 1491, 1685, 3063, 3187, 3316, 3421, 3575, 3894 | `return {"lesson_plan": lesson_plan, "progress_pct": 38.0}` etc. — each node returns only keys it owns | `grep -n "\*\*state" graph.py` → zero hits in node bodies | M |
| 1.2 | `graph.py:3904` — `_FAN_OUT_STATE_KEYS = ("lesson_id","user_id","book_id","tier")` | `Send()` payload **replaces** state, so `state.get("tier")` in all six Phase-1 nodes currently always resolves to `T2`, silently disabling the S2-LM3/4/5 tier bands | assert a T1 lesson produces T1 quiz-count band | S |
| 1.3 | Source-level guard | test walking `pipeline/**/*.py`: no function returns a dict literal containing `**state` | new `tests/unit/test_node_return_shape.py` | S |
| 1.4 | Per-node return-key assertions (fast documentation) | `set(await tts_node(state)) == {"audio_assets","progress_pct"}` × 4 nodes | unit | S |
| 1.5 | TTS spend guard | mock `_synthesize_with_fallback`, assert called **exactly once per distinct segment_id** | unit | S |
| 1.6 | Phase-1 canary at `lesson_planner_node` (~1175, **before** the cache-hit read at 1181) | `if len({s["segment_id"] for s in summaries}) != len(summaries): logger.error(...)` — fires *before* any GPT-4o token is spent, and replaces the misleading `segment count mismatch` RuntimeError at 1297 | caplog test asserting detection precedes spend | S |
| 1.7 | Second canary at `tts_node` entry (~3035) on `narration_scripts` | same one-line distinct-vs-total check — only place duplicated narration is caught before paid synthesis | caplog test | S |
| 1.8 | Residual canary in `package_builder_node`, **after** the `"package_builder" in node_outputs` early return, quiz + glossary only, **exact keys** | `(segment_id, data["question_id"])` / `(segment_id, data["term"])` — **no** count bands, **no** `_MAX_ENTRIES_PER_SEGMENT_HINT` (jargon has no per-segment cap; a band guarantees false positives, and `LoggingIntegration(event_level=ERROR)` turns each into a Sentry issue) | healthy run with 8 glossary terms logs **nothing** | S |
| 1.9 | e2e regression (0.6 flips GREEN) + full-suite baseline check | expect the same 32 pre-existing failures (`test_dna_growth`, `test_onboarding_content`, `test_tutor_service`) — no more, no fewer | full run | S |

**Cost note for the PR body:** this reduces real TTS spend ~4x. Every existing $3.00/lesson calibration and Langfuse cost baseline is inflated and must be re-measured before drawing any ceiling conclusions.

---

### PHASE 2 — BUG A hygiene: per-attempt thread_id + MemorySaver eviction

*Rationale: **not** the 16x fix. It bounds steady-state memory growth and removes a stale-accumulator vector. Land after Phase 1 so it is not mistaken for the cure.*

**BMAD:** fold into the Phase 1 story as a clearly-labelled second AC block, or a small sibling story `2-30`. Either is defensible; folding is cheaper and keeps the "this is hygiene, not the fix" framing intact.

| # | Change | Shape | Test | Effort |
|---|---|---|---|---|
| 2.1 | `graph.py:~4089` — `run_pipeline(..., attempt: str = "")`; compute the nonce **inside the body** (a `uuid4()` default arg evaluates once at import and defeats the fix) | `run_token = f"t{attempt or 0}-{uuid4().hex[:8]}"`; `thread_id = f"{lesson_id}::{run_token}"`; log at INFO with `lesson_id` | patch `ainvoke`, call twice with one `lesson_id`, assert thread_ids differ and both start `f"{lesson_id}::"` | S |
| 2.2 | `apps/api/app/workers/jobs/content_pipeline.py:89` — pass `attempt=f"{ctx['job_id']}:{ctx.get('job_try',1)}"` | **TRAP:** `router.py:271` pins `_job_id=f"pipeline:{lesson_id}"` — `job_id` alone is byte-identical across retries. `job_try` must be in the token. | worker-level test: two `content_pipeline_job` invocations for one lesson → two distinct thread_ids | S |
| 2.3 | `graph.py` — `_discard_checkpoint_thread(graph, thread_id)` helper + `try/finally` around `ainvoke` | `getattr` guard, `except Exception: logger.warning(...)` — must never mask the pipeline exception or a `CancelledError` | see 2.4 | S |
| 2.4 | Eviction tests | **Do not** assert `hasattr(cp,"adelete_thread")` — `BaseCheckpointSaver` defines it (raises `NotImplementedError`), so it can never fail. Use a behavioral round-trip. **Never index** `storage`/`writes`/`blobs` (they are `defaultdict`s; indexing materializes keys) — use `thread_id not in saver.storage` and `not [k for k in saver.writes if k[0]==thread_id]`. Bind `saver` **before** any `_compiled_graph = None`. | unit + failure-path + cancellation-path | M |
| 2.5 | Comment at the thread_id construction site | "resume must be rebuilt on durable Supabase `node_outputs`, never on MemorySaver" | n/a | S |

**Invariant to state explicitly in the story:** `attempt` scopes **only** the LangGraph `thread_id`, **never** the `merge_lesson_job_node_output` key space. All seven tests in `test_phase1_checkpoint_idempotency.py` depend on keys being `f"{node}:{section_id}"`; attempt-scoping them would re-bill every section on an ARQ retry against the $3.00 ceiling.

**Note:** this bounds growth *across* lessons, not *within* one run (per-superstep blobs are unpruned until the `finally`, ×5 concurrent jobs). If an OOM is intra-run, the real fix is keeping `raw_text`/`extracted_images`/base64 URIs out of checkpointed channels — track separately.

---

### PHASE 3 — BUG B: recover the narration script (backend half only)

**BMAD:** story `docs/stories/2-31-narration-script-recovery.md`. Its ACs must **not** claim any player-visible change.

| # | Change | Shape | Test | Effort |
|---|---|---|---|---|
| 3.1 | `graph.py:3499-3503` — `def _fallback_narration(script: str = "")` | returns `{"script": script, "audio_url": "", "audio_provider": "browser", "timestamps": []}` | `_fallback_narration("hello")["script"] == "hello"` | S |
| 3.2 | `graph.py:~3626` — add `narration_script_by_id = _index_by_segment_id(state.get("narration_scripts", []), label="narration_scripts")` (**no** `value_key` — entries are flat) | **TRAP:** lift **only** `entry["script"]`. Never spread the flat entry — `Narration` is `extra="forbid"` and `LessonPackage.model_validate` at 3865 is deliberately uncaught, so a spread turns graceful degradation into a total post-spend failure. | see 3.5 | S |
| 3.3 | `graph.py:~3732-3734` — replace the `if narration is None:` branch | `raw = (narration_script_by_id.get(segment_id) or {}).get("script"); recovered = raw if isinstance(raw,str) and raw.strip() else ""` ; `_fallback_narration(recovered)`; keep `degraded.append(...)`; warn when empty | 3.5 | S |
| 3.4 | `graph.py:3617` — `_index_by_segment_id` uses `item.get(value_key)` not `item[value_key]` | closes the AC-5 "one bad item never crashes the node" gap its own docstring promises | test: `audio_assets` entry lacking `"data"` → node completes, segment degraded, no `KeyError` | S |
| 3.5 | Tests in `apps/api/tests/unit/test_package_builder_node.py` (**not** the e2e file — `_base_state()` at :183-199 has no `narration_scripts`, so the fix is inert in every existing unit test) | Add derived `NARRATION_SCRIPTS = [{"segment_id": a["segment_id"], "script": a["data"]["script"], ...} for a in AUDIO_ASSETS]` (flat shape) and wire into `_base_state`. Cases: (a) missing `sec_1` audio → recovers **sec_1's own** script; (b) absent from both → `""` + warning; (c) whitespace-only → `""`; (d) missing `"data"` → no crash; (e) duplicate `segment_id` → last wins, no warning storm; (f) still in `package_builder_degraded`. All marked `@pytest.mark.unit` **and** `@pytest.mark.asyncio` (`--strict-markers` + `-m unit` silently deselects unmarked tests and still reports green). | M |
| 3.6 | Fix the `_fallback_narration` docstring | Downgrade "factually wrong" → "imprecise about `script`". Name functions, **not** line numbers. | n/a | S |

**Honest framing required in the story:**
- The **real production repro** is the `tts_node` cache-hit replaying a persisted `node_outputs["tts_node"] = []`. `tts_node`'s per-segment `except` already preserves `entry["script"]`, so the two index key sets are otherwise identical by construction — without this framing the fix reads as a no-op.
- `narration_generator_node` returns `{"narration_scripts": []}` at 2852/2864/2918 (no summary / LLM failure / pacing-guard reject). In those cases **there is no script to recover**. Consider sourcing from `plan_seg["summary"]` as a second fallback, or accept the gap explicitly.
- **Do NOT claim a timestamp benefit or a quiz-boundary risk.** `audio_url == ""` → `AudioTimeline.tsx:76` `hasAudio` false → immediate `handleEnded()`; `timeupdate` never fires, so `timestamps` are never read.
- Existing packages already built with a blank script are **not repaired** — `package_builder_node` cache-hits at 3575 and returns the stored dict verbatim. Affected lessons need their `package_builder` checkpoint cleared.

**Hand-off to Dev2 (file as a separate story, hard prerequisite for calling BUG B closed):**
- *Story 2a — virtual playback clock (S/M, this is what kills the 0:00 symptom):* three-way branch on `hasAudio` / `!hasAudio && script.trim()` / `!hasAudio && !script`; `setInterval(100)` accumulator advancing **only** while `status === 'PLAYING'`, calling `processTimeUpdate` — it must **never** call `handleEnded()` (`processTimeUpdate`'s own boundary check at :54-59 already fires the quiz; a second call hits the `quizFiredForSegment` branch and `advanceSegment()`s past an open quiz). Call `setAudioDuration(timestamps.at(-1).end_ms)`. Absorb `seekRequestMs` or declare seek disabled. **Mandatory AC:** the S2-26 never-stuck test at `AudioTimeline.component.test.tsx:64-83` is re-pointed at an empty-script fixture (it currently uses a full 60-word script and asserts synchronous `'QUIZ'` — it will fail).
- *Story 2b — browser SpeechSynthesis (M, enhancement):* layered on the working clock; clock remains source of truth.

---

### PHASE 4 — BUG C: OpenAI retry classification (+ its two blast-radius fixes)

*Rationale: highest blast radius. Cannot ship as a "classification-only S change" — enabling retries changes retry×breaker×cost behavior simultaneously. Effort is **M–L**.*

**BMAD:** story `docs/stories/2-32-openai-retry-classification.md`. This one **must** be its own story — it is the only phase where the fix, if landed naively, makes an outage worse.

| # | Change | Shape | Test | Effort |
|---|---|---|---|---|
| 4.1 | `apps/api/app/core/retry.py` — `_status_of(exc)` + `classify(exc)` | `httpx.HTTPStatusError → exc.response.status_code`; `openai.APIStatusError → exc.status_code` read off the **INSTANCE** (`InternalServerError` has **no class-level `status_code` attribute at all** — not `None`, absent; use `getattr(exc,"status_code",None)`). Match on **base** classes only. `openai.APIConnectionError` covers `APITimeoutError` by inheritance (it is **not** a `builtins.TimeoutError`). Any 4xx not in `_make_status_error`'s map (405/408/413/418/451) arrives as a **bare `APIStatusError`**. | parametrized `classify()` unit tests | M |
| 4.2 | Guard the vendor import | `try: import openai; _OPENAI_STATUS=(openai.APIStatusError,); _OPENAI_CONN=(openai.APIConnectionError,) except Exception: _OPENAI_STATUS=_OPENAI_CONN=()` — empty tuples make `isinstance` a safe no-op. **TRAP:** `tests/conftest.py:17-32` stubs `openai` with a `MagicMock`; `isinstance(x, <MagicMock>)` raises `TypeError`. Also keeps `tts/sarvam.py`, `tts/azure.py` importable without the SDK. | `classify()` correct when `sys.modules['openai']` is a MagicMock | S |
| 4.3 | Retryable set | `{408, 429, 500, 502, 503, 504}` + generic `500 <= s <= 599` (CDN 520/522/524 fold into `InternalServerError`). **Do not** add 409 (non-idempotent double-charge). **Do not** retry `APIResponseValidationError` (status 200, code bug). Note the honest trade: 524 usually means upstream *completed and billed* — we accept duplicate billing over a dead lesson. | `classify(520) is RETRY`; 409 not retried; validation-error not retried | S |
| 4.4 | `max_retries=0` + explicit timeout at **all three** clients: `llm/openai.py:56`, `embeddings/openai.py:48`, `image/openai_image.py:57` | **TRAP:** SDK default is `max_retries=2` → naive fix = **9 HTTP requests** per logical call and up to 3×600 s hangs vs `arq_job_timeout_s`. Use `timeout=httpx.Timeout(settings.openai_request_timeout_s, connect=5.0)` — a **bare float sets connect=120 s too**, worse than the 5 s default. Give image its own `openai_image_request_timeout_s` (~180 s) from the start. | assert `client.max_retries == 0` per provider (kwargs-subset, not exact-tuple) | S |
| 4.5 | `config.py` — new timeout fields + extend the validator at :389 | `openai_request_timeout_s * 3 <= arq_job_timeout_s - extract_timeout_cap_s` (only **300 s** headroom exists today; 3×120 s does not fit — pick ~60 s for chat/embeddings) | extend `test_timeout_contract.py` | S |
| 4.6 | **Circuit-breaker granularity.** Split each provider method: public wrapper owns `is_circuit_open` / `record_success` / `record_failure`; private `@with_retry`-decorated `_x_once()` owns only the Langfuse span + SDK call. | **TRAP:** `record_failure` currently sits *inside* the retried body (`llm/openai.py:131,204`, `embeddings:132`, `image:113`). Today the Bug-C abort accidentally guarantees 1 increment/logical call; after the fix it is 3, against 5-failures/120 s → **two flaky-but-successful calls + one blip = circuit open for 600 s with zero real failures**, and Phase-1 fan-out makes the race real. | **the** regression test: 3 retried 429s → `record_failure` awaited **exactly once**, SDK `call_count == 3` | M |
| 4.7 | `is_provider_health_failure(exc)` | `status = _status_of(exc); if status is None: return isinstance(exc, _TRANSPORT_ERRORS); return status not in _NON_RETRYABLE` — **must** return `False` for bare `ValueError`/cost-ceiling errors, or our own bugs open the breaker | `is_provider_health_failure(ValueError()) is False` | S |
| 4.8 | **Cost-ceiling misclassification.** Move `_maybe_accumulate_cost` **out** of the retried body into the public wrapper (after `record_success`), or introduce `CostCeilingExceeded(RuntimeError)` classified non-health, non-retryable. | `llm/openai.py:229` and `embeddings:150` raise **after** a paid success; today that records a provider failure. `check_ceiling` is a **level** check, so every subsequent call for that lesson re-raises → 5 in seconds → global 600 s outage across all lessons, teachback scorer and DNA profile (shared `_PROVIDER_KEY="openai"`). | ceiling breached → `record_failure` NOT awaited, `call_count == 1` | M |
| 4.9 | Exactly-once observability | one Langfuse generation and one cost accumulation per **logical** call regardless of attempts | test: succeeds on attempt 3 → `accumulate_cost` awaited once, `start_observation` called once | S |
| 4.10 | `CircuitOpenError(RuntimeError)` in `circuit_breaker.py`; classify → ABORT, log at WARNING | avoids `logger.exception` Sentry noise and stops the breaker RuntimeError masking the real 503 (`raise ... from last_exc`) | unit | S |
| 4.11 | Fix the misleading existing test: `tests/unit/test_image_providers.py:113-118` **and** `:131` | it feeds a hand-built `httpx.HTTPStatusError(503)` into a mocked openai client — a type the SDK **never** raises, so it passes while proving nothing. Swap to real `openai.InternalServerError(msg, response=httpx.Response(503, request=req), body=None)` **and** change `pytest.raises(httpx.HTTPStatusError)` → `pytest.raises(openai.InternalServerError)`, else the test errors. | `call_count == 2` + `record_failure` once | S |
| 4.12 | Test helpers in `tests/unit/test_retry.py` | `_openai_status_error(code, headers=...)` mirroring `_make_status_error` (<500 → mapped subclass, ≥500 → `InternalServerError`); `httpx.Response` **must** carry `request=`. `APIConnectionError(request=...)` is **keyword-only**; `APITimeoutError(request)` is **positional**. | — | M |
| 4.13 | Scope: include `image/openai_image.py` | third broken site not in the original brief. **Keep the attempt budget honest:** with `max_retries=0`, `max_attempts=2` is a *drop* from today's 3 effective HTTP attempts — either raise to 3 or state the trade in the PR. | node-level Imagen cascade test unchanged | S |
| 4.14 | Widen coverage to `tts/azure.py`, `tts/sarvam.py`, `image/imagen.py` | Azure/Sarvam raise httpx, which **already** retries today → they already triple-count against the same threshold and are mis-tuned in production **right now**. §14 requires TTS never hard-fails. | mirror 4.6 per provider | M |

**Deliberately NOT done:** `Retry-After` honoring is a **separate story** — it deviates from the §14 backoff formula, needs an explicit cap decision and HTTP-date policy. **Do not** write date-string assertions (`Wed, 21 Oct 2026` is in the future today and flips to the past later).
**Deliberately NOT done:** the `tts/sarvam.py` "docstring bug" — re-read `sarvam.py:11-15`: it says the quota RuntimeError is **not** retryable, and `retry.py` agrees. There is no bug. Do not file it.

---

### PHASE 5 — S1-6: delete the dead structure-validation LLM block

**BMAD:** story `docs/stories/2-27-remove-dead-structure-llm-validation.md`, alone-commit first.

| # | Change | Shape | Test | Effort |
|---|---|---|---|---|
| 5.1 | **Live check before merge** | run the S2-14 harness over `tests/fixtures/eval_pdfs/short.pdf` and `dense_text.pdf` **with and without** the branch; paste section counts/titles into the story | manual, recorded | S |
| 5.2 | `graph.py` — delete **499-559** (not 502-559) | the proposal's replacement snippet re-includes the rule-based block; applied at 502 it runs `detect_headings` **twice** and leaves `rule_sections` unused (ruff **F841** → CI fail). Delete 435-458 (`_STRUCTURE_SYSTEM_PROMPT`, `_build_structure_prompt`) and the local `get_llm_provider` / `DocumentStructure` imports at 469-470. Keep `coalesce_sections`. | `ruff check` clean | S |
| 5.3 | Replacement guard test | keep the `patch.dict("sys.modules", {"app.providers.llm.openai": fake})` pattern and assert `fake.OpenAILLMProvider.assert_not_called()`. **TRAP:** patching `app.providers.llm.factory.get_llm_provider` is **vacuous** once the import is deleted. Two cases: raw_text > 6666 chars **and** < 6666 chars, both asserting full-text preservation. | new | S |
| 5.4 | Test cleanup | rewrite `test_structure_node.py:113, :192, :261` + drop dead helpers/docstring; delete `test_pipeline_tier1.py:172, :211, :250, :296` + `_make_llm_sections`/`_make_llm_provider_patch`; in the e2e file remove **only** the `if name == "DocumentStructure"` branch and confirm the fallthrough | full re-run | M |
| 5.5 | Docs (implementation commit, not the story commit) | `dev1-tracker.md`: mark S1-6 `[ ] ... (DESCOPED 2026-07-28)` — **do not** retitle it to duplicate S1-5 and **do not** leave `[x]` against three ACs no code satisfies ("LLM corrects at least one misdetection", `@with_retry` applied, Langfuse token span). Update Quick Status Dashboard **and** header date per the tracker rule. Story 1-3 artifact: reopen the two deferrals at :110-111 whose rationale was "LLM validation compensates". Story 2-17 Change Log: gate revive on *"`tests/evals/scoring.py` gains a boundary-quality metric first"* — S2-14 is already `done` and its scoring measures nothing about sections, so the naive gate can never fire. | n/a | S |

**Honest framing:** the block is unreachable only for `raw_text > ~6,666` chars. For short docs (how-to PDFs — the exact class the e2e test uses) it is **live and adopted today**. Justify deletion as *"2-16's `coalesce_sections` now covers the short-doc case"*, not as *"provably unreachable"*. Cost saving is ~$0.0013–0.0015/lesson (~0.05% of ceiling) — **sell it as 8–20 s of latency + dead-code removal, not as a cost fix.**

---

### PHASE 6 — Smaller items

**BMAD:** one story `docs/stories/2-33-dev1-cleanup-batch.md` covering 6.1–6.5 (each is a few lines with independent tests); 6.6/6.7 are docs-only and can ride along.

| # | Item | Change | Test | Effort |
|---|---|---|---|---|
| 6.1 | **GET /lessons** | `content/router.py:381` — `select("*")` → `_LIST_COLUMNS_META = "lesson_id,status,title,created_at,completed_at,subject:content->metadata->>subject,estimated_duration_mins:content->metadata->>estimated_duration_mins"`. Add optional `subject`/`estimated_duration_mins` to `LessonStatusResponse` with float coercion. **Also populate them in `get_lesson`** from `resp.content.metadata` — otherwise the detail endpoint returns `null` for data it is holding while the list shows a value. **Drop the bare `except Exception` fallback** (it double-loads the DB during a blip, returns 200 with silently-missing fields, and hides a permanent degradation behind a warning). Verify the select string with one live curl before merge. **Do not** touch `packages/shared/types/lesson.ts` — frozen, and it has no list-response type anyway. | assert `select.call_args[0][0] == _LIST_COLUMNS_META`; assert `.eq("user_id", sub)` retained; fixture row **with** the values (existing row has neither, so a null-only test proves nothing); AC-7 regression: `sign_storage_path` / `_resolve_lesson_content` called **zero** times and `"content" not in` items | S |
| 6.2 | **S3-6 docs** | `media/router.py` docstring: dormant, "not *cleanly* reachable (client would have to reverse-parse bucket+path out of the signed URL)". `content/router.py:99` comment: **three** lists must stay in sync (`_ALLOWED_BUCKETS`, these literals, `core/storage.py::REQUIRED_BUCKETS`). Tracker S3-6: record **three** options with real costs — (1) raise `expires_in` (one line, cheapest, needs a security call), (2) per-asset re-sign by `(lesson_id, segment_id, asset)` resolving the path server-side from `lessons.content` (no schema change, no §16 gate), (3) bulk re-fetch (N+M **blocking** `create_signed_url` calls on the event loop at `router.py:365` — do not recommend without `asyncio.to_thread`). Record that emitting `audio_path` is **off the table** (`additionalProperties:false`). Note S3-6's AC already said backend-only. | existing media router tests stay green and are **not** deleted | S |
| 6.3 | **S1-7 P1 fix** | `graph.py:851-862` — replace `text[: _MAX_EMBED_INPUT_TOKENS * 4]` with a tiktoken round-trip (`enc.decode(enc.encode(text)[:cap])`). Char-based truncation assumes ~4 chars/token — **false for Devanagari** (~1–1.5 tokens/char), so a Hindi chapter 400s the entire embedding batch. Also drop the `len(text)//4` fallback when `token_count` is NULL. | oversized non-Latin chunk → API input ≤8000 real tokens, DB `content` unchanged | S |
| 6.4 | **S1-7 P2** | `chunk_node` is **not** DB-idempotent: `chunks.chunk_id` is `gen_random_uuid()` PK with no unique on `(chapter_id, chunk_index)`, so `.upsert()` degrades to INSERT; and the checkpoint write at 713-716 swallows failures then returns success → ARQ retry inserts a **second** `chapters` row + orphaned duplicate chunks. Fix (b): deterministic `uuid5(chapter_id, chunk_index)` ids in the payload — **no migration**, so no §16 gate. Stop swallowing the checkpoint-write failure. | retry after a swallowed checkpoint write → exactly one `chapters` row | M |
| 6.5 | **S2-15 fail-open** | `providers/llm/openai.py:34-37` — `_COST_PER_1K` has only `gpt-4o`/`gpt-4o-mini`; `_maybe_accumulate_cost` (218-221) **returns early on a pricing miss**, skipping `accumulate_cost` *and* `check_ceiling`. So `LLM_LESSON_PLANNER=o1-mini` — the exact case the `o1-` prefix exists for — silently disables the $3.00 ceiling on the most expensive node. Add `o1-mini` pricing, or fail closed when `lesson_id is not None`. Add a startup dispatchability check calling `get_llm_provider` on all four `settings.llm_*` values so a Claude/Gemini swap fails at boot, not 8 minutes into a paid job. | unpriced model does not bypass `check_ceiling`; boot fails on undispatchable alias | S |
| 6.6 | **S2-15 guard** | `tests/unit/test_provider_factory_adoption.py` — walk `app/modules/content/pipeline/**/*.py` with `re.compile(r"app\.providers\.llm\.openai|OpenAILLMProvider")`. **Not** pinned to `graph.py` — `pipeline/nodes/` already exists and CLAUDE.md mandates node extraction there; a filename-pinned test would report compliance it no longer checks. | new test | S |
| 6.7 | **S4-4 tracker** | **Option B (recommended for this batch):** keep ⚠️ PARTIAL and state the real status — limiter + 429 handler + `Retry-After` done; per-user keying **non-functional** (`rate_limit.py:35-44` decodes without `audience="authenticated"` and has no ES256/JWKS branch, so real Supabase tokens raise and it falls back to IP — verified `InvalidAudienceError`); `RATE_LIMIT_STORAGE_URL` unset across 2 replicas (already P0-3 in `infra-requirements-sprint3-4.md:263`). Bump header date only. **Option A** (fix `_get_user_key` to mirror `dependencies.py:80-105`, set the Redis URL, fix the token fixture to include `aud`) then mark `[x]` + dashboard 45→46 / Partial 1→0. Use real anchors: header **line 6**, dashboard **lines 17-25** (Sprint 4 = 23, Totals = 25), S4-4 block **711-715**, slowapi row **760** (it is in "Ahead-of-Schedule Wins", not a deferred-infra table). | if Option A: 6 requests one JWT → 6th is 429 with `Retry-After`; different JWT still 202 | S / M |

---

## One story or several?

**Several — five stories, plus two Dev2 hand-offs.** They are genuinely independent defects with independent blast radii and independent rollback needs; bundling them would make the 5-agent review's AC-Completeness layer unauditable and would let a Bug-C circuit-breaker regression ride in on a Bug-B merge. But they share one test-infrastructure dependency (`test_howto_pipeline_e2e.py`), so Phase 0 **must** land first and every later story states it as a prerequisite. The one justified merge is Phase 2 into Phase 1: the thread_id/eviction work touches the same function and the same story's ACs, and separating it invites the reader to believe the retry axis was the 16x fix.

| Story | Phases | Effort |
|---|---|---|
| `2-28-e2e-harness-repair-and-duplication-guards` | 0 | M |
| `2-29-pipeline-state-duplication-fix` (incl. thread_id hygiene) | 1 + 2 | M |
| `2-31-narration-script-recovery` | 3 | S–M |
| `2-32-openai-retry-classification` | 4 | **L** |
| `2-27-remove-dead-structure-llm-validation` | 5 | M |
| `2-33-dev1-cleanup-batch` | 6 | M |

Per story: story file committed **alone** → pushed → verified chronologically first on the branch → RED tests → implementation → `/bmad-code-review` with **all 5** agent layers (Story Quality, Blind Hunter, Test Coverage, AC Completeness, Process Integrity) → merge. Note `/bmad-code-review` runs 3 layers by default; a PR listing fewer than 5 must be rejected.
**Branching:** memory records that Sprint 2 uses a single shared branch, overriding CLAUDE.md's per-task rule — confirm with the user before creating six branches.

---

## Traps to avoid

1. **Dev2's "skip Phase 1 if `last_node` says it completed" — UNSAFE.** The accumulated reducer state lives only in the process-local MemorySaver. After a worker restart or a different worker picking up the retry, `lesson_planner` and `package_builder` run with empty `segment_summaries`/`quiz_questions` and ship a structurally valid, content-empty lesson. Measured: re-dispatching Phase 1 costs **zero** extra LLM calls (93 → 93) because Supabase checkpoints absorb it. Skipping buys nothing.
2. **Do not blank the Phase-1 cache-hit returns to `{}`** (`graph.py:2159`, `2786`). With a fresh `thread_id` those returns are the **only** path by which cached work reaches `package_builder`. Blanking them ships a quiz-less lesson.
3. **The `min(len, 6000)` / coverage-guard "fix" for S1-6 causes data loss** — the LLM must verbatim-echo bodies; any window-based patch silently truncates section bodies. Delete the block; do not patch it.
4. **`ctx["job_id"]` is not a uniquifier.** `router.py:271` pins `_job_id=f"pipeline:{lesson_id}"` — byte-identical across every retry. The fix ships green (tests exercise the `uuid4` default) while production stays broken. `job_try` must be in the token.
5. **`uuid4()` as a default argument value** evaluates once at import and defeats the whole fix. Compute inside the body.
6. **Bug C trips the circuit breaker ~3× faster** unless `record_failure` moves outside the retried region. Two flaky-but-successful calls + one blip = 600 s global outage across all lessons and the student-facing teachback path.
7. **Bug C without `max_retries=0` = 9 HTTP requests** per logical call and up to 30–90 minutes of hang against `arq_job_timeout_s`. And a **bare float** `timeout=` also sets `connect=120 s`, destroying the SDK's 5 s connect guard — strictly worse for the hang it was added to prevent.
8. **`InternalServerError.status_code` does not exist on the class** (not `None` — absent). Reading it off the class `AttributeError`s; reading it via a duck-typed `getattr` on the class silently misclassifies every 5xx.
9. **`hasattr(cp, "adelete_thread")` is a false canary** — `BaseCheckpointSaver` defines it raising `NotImplementedError`, so it can never fail. And `storage`/`writes`/`blobs` are `defaultdict`s: indexing them in an assertion **creates** the key.
10. **`assert pkg2["segments"] == pkg1["segments"]` is vacuous** — `package_builder` cache-hits at `3575` and returns run 1's dict verbatim. Assert on spy-captured run-2 state instead.
11. **Spreading the recovered narration entry** into `Narration` (`extra="forbid"`) turns graceful degradation into a total post-spend `ValidationError` at the uncaught `model_validate` (3865). Lift `["script"]` only.
12. **`test_image_providers.py:102` proves nothing** — it feeds `httpx.HTTPStatusError` into a mocked OpenAI client, a type the SDK never raises. Fix the exception **and** the `pytest.raises` line at `:131`.
13. **`-m unit` + `--strict-markers` silently deselects unmarked tests** and still reports green. Every new test needs `@pytest.mark.unit` and `@pytest.mark.asyncio`.
14. **`patch("app.providers.llm.factory.get_llm_provider"); assert not called` is vacuous** once the import is deleted, and misses a re-added direct `OpenAILLMProvider` import. Use the `sys.modules` fake.
15. **A filename-pinned source-grep guard stops guarding** the day a node moves to `pipeline/nodes/`. Walk the directory.
16. **Do not "fix" `tts/sarvam.py`.** Its docstring and code agree that the quota `RuntimeError` must not be retried. Making `RuntimeError` retryable would also make the circuit-open `RuntimeError` retryable — a serious regression.
17. **BUG B does not fix the 0:00 quiz.** Ship it framed as package fidelity, or it will be reported as "didn't work".

---

## Definition of done

**Code**
- [ ] `grep -n "\*\*state" apps/api/app/modules/content/pipeline/graph.py` → zero hits inside node bodies (all 18 sites, incl. the multiline spreads at 250/427)
- [ ] `_FAN_OUT_STATE_KEYS` includes `"tier"`
- [ ] `run_pipeline` builds a per-invocation `thread_id`; `content_pipeline_job` passes `job_try`; `adelete_thread` runs in a `finally`
- [ ] `_fallback_narration(script)` + guarded recovery; `_index_by_segment_id` uses `.get(value_key)`
- [ ] `classify()` in `core/retry.py` with guarded vendor import; `max_retries=0` + `httpx.Timeout(..., connect=5.0)` on all three OpenAI clients
- [ ] `record_failure`/`record_success` at logical-call granularity in **all six** providers; cost-ceiling errors excluded from provider health
- [ ] Dead structure-validation LLM block deleted; `ruff check` clean
- [ ] `GET /lessons` narrow select (no `except Exception` fallback); `get_lesson` populates the same two fields
- [ ] Token-space embed truncation; deterministic chunk ids; checkpoint-write failure no longer swallowed
- [ ] `o1-mini` priced (or fail-closed) + startup dispatchability check

**Tests**
- [ ] `test_howto_pipeline_e2e.py` green with the quiz-count, unique-`question_id`, and **lesson_planner-prompt segment-count** assertions
- [ ] Node return-shape guard + source-level `**state` guard green
- [ ] `package_builder` recovery suite (6 cases) green, all marked `unit` + `asyncio`
- [ ] 3-retried-429s → **exactly one** `record_failure`; ceiling breach → **zero** `record_failure`, `call_count == 1`
- [ ] `max_retries == 0` asserted per provider; `classify()` correct under the conftest `MagicMock` stub
- [ ] Thread-eviction behavioral test (no `defaultdict` indexing, `saver` bound before reset) + failure + cancellation variants
- [ ] `test_image_providers.py` uses real `openai.InternalServerError` in **both** the raise and the `pytest.raises`
- [ ] Full suite: **exactly** the 32 pre-existing unrelated failures — no more, no fewer

**Live verification (cannot be certified from source)**
- [ ] PostgREST JSONB-path `select=` accepted by the real project (one curl)
- [ ] S1-6 deletion run over `short.pdf` + `dense_text.pdf`, before/after section counts pasted into the story
- [ ] Cost + Langfuse baselines **re-measured** post-fix; PR notes prior figures were ~4x inflated on TTS

**Process**
- [ ] Each of the 5 stories: story file is the chronologically **first** commit on its branch, pushed alone
- [ ] Each PR carries a Senior Developer Review section listing **all 5** agent layers
- [ ] `docs/dev1-tracker.md`: checkbox + `— ✓ 2026-07-28`, Quick Status Dashboard (lines 17–25) and Totals updated, header date (line 6) updated — in the same response
- [ ] Confirmed and recorded: **no** `packages/shared/*` or `supabase/migrations/*` file touched → §16 gate not triggered

**Hand-offs filed (required before any of these bugs is called system-closed)**
- [ ] Dev2 Story 2a — virtual playback clock (incl. the mandatory S2-26 test re-point)
- [ ] Dev2 Story 2b — browser SpeechSynthesis
- [ ] Dev2 — `retryAudio()` must re-fetch, not remount an expired URL
- [ ] Dev3 — assessment module factory adoption (`service.py:496,932`, `dna_profile.py:93`) + stale `dna_profile.py:11` docstring
- [ ] Dev4 — tutor `state_machine/graph.py`: same `{**state,...}` pattern (7 sites) and an un-evicted MemorySaver in the **long-lived API process**
- [ ] S4-4 recorded honestly as PARTIAL, or fixed and marked done — not marked done as-is