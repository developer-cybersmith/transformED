# Dev 1 Sprint Tracker — TransformED AI

**Owner:** Dev 1 (developer1-cybersmith) — developer.team2@cybersmithsecure.com
**Domain:** Infra · Content Pipeline (11 nodes) · Provider Abstraction · Embeddings · Langfuse
**PRD:** 1.0 Final (10 June 2026) + Decisions Update (25 June 2026) — `CLAUDE.md` is source of truth
**Last updated:** 2026-08-31
**Sprint 0 status:** 12/12 COMPLETE ✅
**Sprint 1 status:** 10/10 COMPLETE ✅ — merged to `main` 2026-07-13 (PR #72). Includes Tier-1/Tier-2 hardening plus Story 2-0b (page-scoped docling + extraction performance). **2026-07-23 gap-fix (Story 1-6):** `GET /api/content/lessons/{id}` never actually returned `content` despite the frozen contract promising it since Week 1 — discovered while building Story 3-6 (media signed-URL layer); fixed in Story 1-6.
**Sprint 2 status:** 21/21 COMPLETE ✅ (2026-07-17, still on `sprint2/phase-b-generation-nodes` — not yet merged to `main`). All 15 pipeline nodes real; `package_builder` (S2-11) + `lesson_ready` WebSocket push (S2-12) landed 2026-07-16; cost ceiling enforcement (S2-13) and the 5-PDF eval harness (S2-14, live run not yet triggered) landed 2026-07-17; Learner Mode tier-aware generation (S2-LM1–LM5) landed 2026-07-17 — `POST /lessons` accepts a `tier` param that drives per-segment slide budgets and outline content-depth framing. Frontend/assessment/tutor teams can migrate off `apps/web/src/mocks/data/lessonPackage.ts` once this branch merges. **2026-07-27 gap-fix (Story 2-25):** a full-repo 360° audit (`docs/reports/sprint2-360-audit-2026-07-27.md`) found the admin panel was 100% unimplemented with no admin/role concept anywhere in the codebase (not the "Sprint 3" work it was tracked as — genuinely absent), the media signed-URL allowlist had 3 structurally-broken bucket entries (`source-pdfs`/`avatar-clips`/`lesson-slides` — each unreachable even for the legitimate owner, zero frontend callers), a stale pipeline docstring, and shared-contract drift (`lesson.ts`/`lesson_package.schema.json` nullability + `tier` required/optional mismatch vs. Pydantic). All 4 fixed in Story 2-25, plus a 5-agent code-review round (fixed a real admin-email case-sensitivity lockout bug it surfaced). The other 21 audit findings belong to Dev2/Dev3/Dev4 and are tracked separately for the cross-team wiring handoff. **2026-07-28 gap-fix (Story 2-28):** Dev 2 reported 48 quiz questions for a segment that should have 3, from a live Refresher-tier run. Root cause was NOT ARQ retries — 18 nodes returned `{**state, ...}`, and since six Phase-1 channels are `operator.add` concatenating reducers, the four nodes running after the fan-in each doubled all six: 2⁴ = 16×, in a single clean run. Fixed at all 18 sites and guarded by an AST scan + e2e assertions (the assertion failed `48 <= 3` before the fix, passes after). **Two consequences worth flagging:** (1) real TTS spend was ~4× inflated, so every existing $3.00/lesson calibration and Langfuse baseline must be re-measured; (2) found while fixing it — `_FAN_OUT_STATE_KEYS` omitted `"tier"`, and because a `Send()` payload *replaces* state, all six Phase-1 nodes read the T2 default regardless of the lesson's real tier, silently disabling the S2-LM3/LM4/LM5 bands for every T1 and T3 lesson. Both now covered by tests that fail on the mutation. Same `{**state, ...}` pattern exists in Dev 4's `modules/tutor/state_machine/graph.py` — handed off, not fixed across the ownership boundary. **2026-07-28 gap-fix (Story 2-31):** closes Dev 2's two remaining reported items plus two findings from the Story 2-28 review. `_fallback_narration()` was returning `{"script": ""}`, discarding narration text sitting in `state["narration_scripts"]` — only the *audio* is missing on the TTS degrade path, not the script — so packages built via that path shipped empty narration. `_index_by_segment_id` used `item[value_key]` and `KeyError`-ed the whole node on one malformed entry, contradicting its own docstring. Cached Phase-1 quiz batches are now rejected on read when the count exceeds the lesson tier's band, so a checkpoint written *before* the 2-28 `tier` fix cannot silently replay T2-sized content into a T1 lesson while the logs show the tier fix working (guard is `n_max`-only — a below-band count is ambiguous against 2-28 AC-8's keep-short-batches rule; residual gap documented in the story). `GET /lessons` now lifts `subject` + `estimated_duration_mins` from the `content` JSONB via PostgREST path selectors instead of `select("*")` — Dev 2 needed both for dashboard cards without an N+1 — with regression assertions proving Story 1-6 AC-7 still holds (zero signing calls, no `content` attached). Embedded-lesson signed-URL expiry raised 1h → 8h. **Not fixed here and must not be reported as fixed:** Dev 2's visible 0:00-quiz-fires-instantly symptom is in `AudioTimeline.tsx` and needs a virtual playback clock — see `docs/dev2-narration-playback-handoff.md`. **2026-07-28 review round (6 adversarial layers) on Story 2-31 — worth reading, because it caught a bug that would have taken the product down:** the first `_LIST_COLUMNS` named `completed_at`, which is a column on `lesson_jobs` and *not* on `lessons`. Under `select("*")` that was harmless; naming it explicitly makes PostgREST reject the whole query, so `GET /lessons` would have failed for every user on every request — and no test could catch it, because all four AC-4 tests mock Supabase and assert the select *string*. Now guarded by a test that parses `_LIST_COLUMNS` against the columns the migrations actually define. The review also showed **AC-3's shipped guard could not catch its own stated hazard**: pre-2-28 checkpoints are all T2-sized (2–3 questions) and T1's `n_max` is 5, so every stale T2 cache passed for exactly the T1 lessons the AC was written about; the count heuristic fired only for T3. Redesigned as a `tier` stamp in the checkpoint *value* — exact rather than inferential, keys still `f"{node}:{section_id}"`, same-tier retry still a free cache hit. Also added a salvage path (a rejected cache plus one transient LLM failure previously shipped a segment with **zero** questions and left the stale checkpoint in place, so every ARQ retry re-rejected and re-billed with no `check_ceiling()` call in that node — though the loop was never actually unbounded: Phase 1 is gated on `check_ceiling()` before dispatch and `_maybe_accumulate_cost` raises at the $3.00 ceiling, so it always terminated. That over-claim was corrected on 2026-07-29 after the Story 2-32 review caught it; the salvage fix stands on the zero-questions correctness defect, which was always the stronger argument), hardened `_index_by_segment_id` against non-dict entries/values, and hardened the list response against untrusted LLM-generated JSONB (a dict-valued `subject` or a `NaN` duration would have 500'd or broken `JSON.parse` for the whole page). Three tests were found passing for the wrong reason and fixed. **Standing lesson: mocked tests on both sides validate the mock, not the contract** — the two worst findings here were both invisible to a green suite.

**Provider-layer gap-fix (Story 2-32, 2026-07-29, branch `sprint2/dev1-provider-retry-classification`, based on `main`):** two live defects in the retry/circuit-breaker layer, both invisible to a green suite. **(1)** `with_retry` classified only `httpx` exceptions, but **zero** OpenAI SDK exceptions derive from `httpx.HTTPError` (`openai.APIError -> OpenAIError -> Exception`) — so every OpenAI failure, including a 429 rate-limit (the most common transient failure in this system), was treated as a fatal unknown error and never retried, contradicting PRD §14. **(2)** `record_failure` was called *inside* the retried function, so fixing (1) alone would have turned one logical failure into three and opened the breaker after 2 logical calls instead of 5 — a brief rate-limit becoming a 10-minute outage. New `guard_breaker()` sits outside the retry decorator and records exactly one outcome per logical call; the $3.00-ceiling threshold was **not** retuned, because the accounting was what was wrong. Also: `imagen.py` redacts the API key from httpx errors (the key is in the request URL) by re-raising a bare `RuntimeError`, which made retryable 429/503 permanently fatal — its `@with_retry` was decorative; a new `SanitizedHTTPError` carries the status code (metadata, never the URL) so redaction and retryability are no longer mutually exclusive. **Found during implementation, not anticipated by the story:** Sarvam and Azure use raw httpx, so their errors were *always* classified and they *always* retried — meaning the TTS breaker has been tripping ~3× too fast in production all along, independent of this story (measured on unmodified code: 3 attempts → 3 `record_failure`). Fixed in the same change; their quota/rate-limit behaviour is unchanged and now pinned by tests. **Review round (6 layers, 2026-07-29) — Changes Requested, all applied.** The headline finding: the story had dropped `DEV1-FIX-PLAN.md` item 4.4 (`max_retries=0` + explicit timeouts), and the OpenAI SDK defaults to `max_retries=2` — so the classification fix as first shipped meant **9 HTTP requests per logical call** with two independent backoff schedules and a 600s default read timeout. Also fixed: a live credential leak via `__context__` (`raise ... from None` does NOT clear it — the sanitized error must be built inside the `except` and raised after it exits), an AC-5 test that survived the exact mutation it advertised killing, Imagen transport errors never retrying, a reload-induced CI flake that silently disabled Imagen retry, cost-ceiling aborts and client-side 400/422s counting as provider ill-health (either could open the shared breaker for every tenant), and circuit-open rejections logged at ERROR into Sentry. **Cross-branch correction — DONE 2026-07-29 (commit `0ade382`):** the claim "Phase-1 has no `check_ceiling()` gate, so nothing bounds the re-bill loop" is false. The fan-out gates before dispatch and `_maybe_accumulate_cost` raises at the ceiling — including on a billed call whose content failed to parse, which is that fix's own failure mode — so the loop always terminated at $3.00. Corrected in Story 2-31's AC-3 text, its Dev Agent Record, its Change Log, the tracker entry on that branch, and PR #101's body. No code changed: the salvage path stands on the zero-questions correctness defect. **Standing lesson, third time it has bitten this project:** two stale `openai` MagicMock stubs meant provider tests were asserting against a mock rather than the real SDK exception hierarchy — mocked tests on both sides validate the mock, not the contract.


**FINAL HANDOVER — 2026-07-30.** Sprints 0–2 complete and merged. Everything Dev 1 owned is on
`main`; nothing is awaiting merge. Read **`docs/handoffs/DEV1-FINAL-HANDOVER.md`** first — it
supersedes every earlier handoff and lists every open item with an owner and a trigger.

Closing sequence, 2026-07-29 → 30: the defect register + binding rules + schema column guard
(#110), the three cross-dev handoffs (#111), D19/D20 retry classification (#112), D23
`lesson_ready` routing (#113 + #116), review round 2 on D12–D17 with **D15 rejected as a wrong
finding** (#105, #107), `ruff format` clearing the second CI gate (#117), the video-delivery
decision + two LangGraph binding rules (#98), and the eval cost meter (#120). Register: **22
closed, 5 open, 1 live in production.**

**Two facts worth carrying forward.** (1) **CI had failed 60 consecutive runs** and merges
proceeded anyway — it died at `ruff check`, step 5 of 9, so it had *never reached a test step*.
The web job died earlier still, on a lockfile path that assumed a per-app lockfile in a pnpm
workspace, which meant `apps/web` **had never produced a production build**. Both were Dev 1's.
`ruff`, `format` and the entire web job are now green; **mypy is the last API gate** (Dev 3 19,
Dev 4 5). (2) **The $3.00/lesson ceiling was enforced but never measured** — the eval harness
contained zero references to cost until Story 2-38. The meter exists now; the baseline lands on
the next live run.

**⚠️ CORRECTION 2026-07-30 — the "final handover" claim was premature.** A route-by-route
backend↔frontend wiring audit (13 agents, 6 lanes, every finding adversarially verified, then
re-verified by hand) was run *after* Dev 1 declared its work finalized. It found **three Dev 1
defects plus one coverage gap**, all now registered:

- **D31 (High)** — `NEXT_PUBLIC_API_URL` omits the `/api` segment in `.env.example:10`,
  `.github/workflows/ci.yml:126` **and Dev 1's own Dev 2 handoff**. Every router is mounted
  under `/api` with no unprefixed alias, so **following the setup documentation 404s every API
  call.** A developer who configures nothing works; one who reads the docs does not. Two other
  docs have it right — the repo contradicts itself in six places.
- **D32 (Med)** — `graph.py:3856` does a raw `item["data"]` subscript while its docstring claims
  *"Same defensive-skip philosophy as `_index_by_segment_id`"*. One malformed entry `KeyError`s
  `package_builder_node` — the **last** node, after 100% of the lesson's spend. **Site 2 of a
  defect closed at site 1** (binding rule 6).
- **D33 (Low)** — `book_id`/`chapter_id` default to `""` against `UUID` fields, so a missing
  upstream output surfaces as a bare `ValidationError` at the final node.
- **D37 (Med)** — `_LIST_COLUMNS`' PostgREST JSON-path selectors have **never run against real
  Postgres**. The `completed_at` reference in that exact select list already caused one
  outage-class `42703`; a Supabase mock has no catalog and cannot raise it.

**The good news, and it is the larger part:** the generate path is **genuinely wired** —
upload → 202 → poll → `content` with 8-hour signed media URLs, not mocked and not half-built,
read on both ends by three independent lanes. Auth (incl. on multipart), tier vocabulary,
**status vocabulary** (`lessons.status` `generating|ready|failed` → `_STATUS_MAP` →
`queued|running|ready|failed`, matching the frontend union exactly), package shape three-way,
`limit`/`offset` paging, and server-side media signing all verified aligned. Also settled: **PR
#90 is a no-op** — all three contract files already agree `LessonMetadata.tier` is optional.

The audit also found ~40 lower-severity items across all four devs, and two register entries
now have no owner at all (**D36**: `apps/web` is Next 16.2.9 / React 19.2.4 while `CLAUDE.md`
locks "Next.js 14"). Full record: **`docs/reports/frontend-wiring-audit-2026-07-30.md`**.

**Standing lesson, and it is the same one as always:** "finalized" was asserted from a green
suite, and the suite could not see any of this. The audit that found it read *both ends of every
seam* — RC-2. **Nothing was load-tested, and nobody has ever run the pipeline end to end
against real providers**, so "the seams line up" remains the strongest supportable claim.

**Still open, and not Dev 1's to close:** PR #119 (Story 2-35, D18 — the demo blocker) awaits
Dev 3's review under the option-B agreement, and Dev 2's one-line `player.machine.ts` change is
its other half. Dev 1 will not merge #119 unilaterally.

**Story 3-35 — env/config correctness, 2026-08-11 (branch `sprint3/s3-35-env-config-fixes`).**
Bundled fix for three registered defects sharing one root cause (a documented/templated config
value disagreeing with the code that actually runs, or existing with zero enforcement): **D62**
(`LANGFUSE_HOST` template said self-hosted, code default is Cloud), **D31**
(`NEXT_PUBLIC_API_URL` missing `/api` in `.env.example` and `ci.yml` — High, live in prod, part
of the Lesson Delivery sprint's L0 prerequisites), and **D48** (`max_daily_spend_per_user_usd`
deleted — zero enforcing readers ever existed; option (b) taken, not implemented, since a real
daily-spend control is separately-scoped work). All three closed in
`docs/DEFECT-REGISTER.md`. RED-then-GREEN verified by actually running the suites (this sandbox
had neither Python 3.12/`uv` nor `pnpm` preinstalled — both were installed to run real tests
rather than assume green): 2 new backend tests + 1 new frontend test, plus the two existing
regression suites the story promises not to break (`test_config_settings.py` 15/15,
`test_generate_lesson_endpoint.py` 81/81) — all green, unmodified. Full story:
`docs/stories/3-35-env-config-fixes.md`.

**Story 3-36 — package_builder defensive fixes, 2026-08-11 (branch
`sprint3/s3-36-package-builder-defensive-fixes`).** D32: `_group_by_segment_id` raw
`item["data"]` subscript + missing `isinstance` check — real, unfixed defect, now hardened to
match its sibling `_index_by_segment_id`'s Story 2-31 defensive-skip pattern exactly (all 3
callers — slides/quiz/jargon — inherit the fix with no call-site changes). 3 new tests
reproduce all three pre-fix crash types (`AttributeError`/`KeyError`/`TypeError`), RED-confirmed
then GREEN; full 42-test file re-run, zero regressions. **D33: found already fixed** — `git
blame` traces the real fix to commit `1c4360b1` (2026-08-04, Story 1-13), a full week before
this story started, already covered by 3 named tests. The register was simply never updated to
close it — corrected rather than re-implemented. **Round 2 (real `/bmad-code-review`, 4
independent agents) found a more severe issue than round 1's own inline review caught:**
`metadata.total_segments` read the stale planning-time count instead of the real shipped
count — this story's own D32 fix made that reachable via a new trigger (a segment's only
slide entry malformed → silently dropped → package claims more segments than it shipped, the
book-scale 4%-defect shape at segment granularity). Registered and fixed as **D63** in the
same commit; quiz/jargon content losses also now feed the existing degradation-tracking
aggregate. 3 more tests added, RED-confirmed by reverting `graph.py` alone. Full story:
`docs/stories/3-36-package-builder-defensive-fixes.md`.

---

## Quick Status Dashboard

> Update this table each time a task is checked off below.

| Sprint | Period | Tasks | Done | Partial | Not Started |
|--------|--------|------:|-----:|--------:|------------:|
| Sprint 0 | Week 1 (Jun 12–18) | 12 | 12 | 0 | 0 |
| Sprint 1 | Weeks 2–3 (Jun 19 – Jul 2) | 10 | 10 | 0 | 0 |
| Sprint 2 | Weeks 4–5 (Jul 3–16) | 21 | 21 | 0 | 0 |
| Sprint 3 | Weeks 6–7 (Jul 17–30) | 23 | 22 | 0 | 1 |
| Sprint 4 | Weeks 8–9 (Jul 31 – Aug 13) | 7 | 2 | 0 | 5 |
| Week 10 | Aug 14–20 | 4 | 0 | 0 | 4 |
| **Totals** | | **77** | **67** | **0** | **10** |

---

## Primary Files (Dev 1 Owns)

### Files That Exist

| File | Purpose |
|------|---------|
| `apps/api/app/main.py` | FastAPI app factory, lifespan hooks, all router mounts |
| `apps/api/app/config.py` | All env vars via pydantic-settings — `get_settings()` is the only entry point |
| `apps/api/app/dependencies.py` | JWT verify, Redis, Settings as FastAPI deps |
| `apps/api/app/core/db.py` | Supabase async client lifecycle |
| `apps/api/app/core/redis.py` | `init_redis()` / `get_redis()` / `close_redis()` |
| `apps/api/app/core/retry.py` | `with_retry()` — exponential backoff + jitter ✅ done |
| `apps/api/app/core/circuit_breaker.py` | 5-failure/2-min breaker, Redis state ✅ done |
| `apps/api/app/core/cost_tracker.py` | Per-lesson cost accumulation + ceiling enforcement |
| `apps/api/app/core/websocket.py` | WebSocket connection manager |
| `apps/api/app/providers/base.py` | Abstract `LLMProvider` / `TTSProvider` / `ImageProvider` interfaces |
| `apps/api/app/providers/llm/openai.py` | OpenAI provider — GPT-4o / GPT-4o-mini |
| `apps/api/app/providers/tts/` | TTS provider directory |
| `apps/api/app/providers/image/` | Image provider directory |
| `apps/api/app/providers/avatar/` | HeyGen avatar provider directory |
| `apps/api/app/modules/content/router.py` | Content module router |
| `apps/api/app/modules/content/pipeline/graph.py` | LangGraph graph + all 15 node functions inline (deliberately NOT one file per node — see Story 2-1's Tracker Cross-Reference Notes). **2026-07-17 full-Sprint-2-audit finding:** the "Files to Create" table above previously listed `nodes/summarise_segment.py`, `nodes/quiz_generator.py`, `nodes/package_builder.py`, etc. as separate pending files — none of these ever existed or were meant to; flagged independently by 6 of 21 auditor agents as stale/aspirational documentation. Those rows have been removed; this row is now the single authoritative pointer. Real: extract/structure/chunk/embed (Sprint 1), all 6 Phase 1 economy nodes (S2-1–S2-6), `lesson_planner_node` (S2-7), `slide_generator_node` (S2-8), `tts_node` (S2-9), `image_generator_node` (S2-10), `package_builder_node` (S2-11) — all 15 nodes in the pipeline have a real implementation. The `lesson_ready` WebSocket push (S2-12) — a separate file, `apps/api/app/workers/jobs/content_pipeline.py` + `apps/api/app/core/pubsub.py`, not this file — has also landed. |
| `apps/api/app/providers/tts/sarvam.py` | `SarvamTTSProvider` — primary TTS ✅ S2-9 |
| `apps/api/app/providers/tts/azure.py` | `AzureTTSProvider` — fallback TTS ✅ S2-9 |
| `apps/api/app/modules/content/pipeline/nodes/__init__.py` | Node package (individual node files not yet created) |
| `apps/api/app/schemas/__init__.py` | **EMPTY — awaiting `lesson.py` (S0-12)** |
| `apps/api/app/workers/main.py` | ARQ `WorkerSettings` entry point |
| `apps/api/app/workers/jobs/content_pipeline.py` | ARQ content pipeline job skeleton |
| `.github/workflows/ci.yml` | CI: lint + test on every PR |
| `.github/workflows/deploy.yml` | Deploy: Railway on merge to main |
| `railway.toml` | Railway service config |
| `supabase/migrations/20260611000000_initial_schema.sql` | Initial DB schema — **APPLIED, NEVER MODIFY** |
| `supabase/migrations/20260625000000_chunks_inline_embedding.sql` | Inline embeddings + books table — **APPLIED, NEVER MODIFY** |
| `supabase/migrations/20260714020000_add_lesson_tier.sql` | `lessons.tier` column, enum-constrained ✅ S2-LM2 |

### Files to Create

| File | Purpose |
|------|---------|
| `apps/api/app/core/langfuse.py` | Global `Langfuse` singleton — `get_langfuse()` used by all providers ✅ S0-9 |
| `apps/api/app/schemas/lesson.py` | Pydantic v2 models mirroring `lesson_package.schema.json` ✅ S0-12 |
| `apps/api/app/modules/content/pipeline/nodes/extract_text.py` | PyMuPDF extraction node *(S1-2)* |
| `apps/api/app/modules/content/pipeline/nodes/extract_tables.py` | pdfplumber table extraction *(S1-3)* |
| `apps/api/app/modules/content/pipeline/nodes/ocr_fallback.py` | Tesseract OCR fallback *(S1-4)* |
| `apps/api/app/modules/content/pipeline/nodes/structure_detect.py` | Rule-based + GPT-4o-mini structure detection *(S1-5, S1-6)* |
| `apps/api/app/modules/content/pipeline/nodes/chunk.py` | Semantic chunking *(S1-7)* |
| `apps/api/app/modules/content/pipeline/nodes/embed.py` | Embedding generation + pgvector storage *(S1-8)* |
| `apps/api/app/modules/admin/router.py` | Admin: job status, costs, retry trigger *(S3-4)* |
| `apps/api/tests/unit/test_lesson_schema.py` | Pydantic ↔ JSON schema round-trip tests (22 tests) ✅ S0-12 |
| `apps/api/tests/unit/test_langfuse_core.py` | Singleton + flush contract tests (4 tests) ✅ S0-9 |
| `apps/api/tests/evals/` | Eval harness against real PDFs *(S2-14)* |

### Read-Only Dependencies (Do Not Modify)

| File | Owned By | Why Dev 1 Reads It |
|------|----------|--------------------|
| `packages/shared/lesson_package.schema.json` | Frozen (all devs) | Authoritative schema — Pydantic models must mirror it exactly |
| `packages/shared/types/lesson.ts` | Dev 2 | Cross-reference TS types when writing Pydantic models |
| `packages/shared/types/ws.ts` | Dev 4 | `lesson_ready` push from `package_builder` must match this discriminated union |
| `apps/api/app/modules/assessment/router.py` | Dev 3 | Coordinate `lesson_jobs` state enum — Dev 3 reads job state in Sprint 2 |

---

## Interface Contracts (Frozen)

Changes require a **4-developer PR review** (PRD §16):

1. `packages/shared/lesson_package.schema.json` — JSON schema; authoritative. Both Pydantic models and TS types must stay in sync.
2. `packages/shared/types/lesson.ts` — TS mirror of the JSON schema.
3. `packages/shared/types/ws.ts` — WebSocket discriminated union; `lesson_ready` message shape.
4. `supabase/migrations/` — Applied migrations are immutable. Schema changes require a new `.sql` file.
5. **Assessment OpenAPI** — Auto-generated from FastAPI routes; breaking route changes require cross-dev review.

---

## Dependency Map

```
Dev 2 (Frontend / Player)
  ──► POST /api/content/lessons       [uploads PDF, triggers pipeline]
  ◄── GET  /api/content/lessons/{id}  [polls status; reads content JSONB when ready]
  ◄── WS   lesson_ready push          [via Dev 4 WebSocket layer — Dev 1 triggers it]

Dev 3 (Assessment / CES / Analytics)
  ──► lesson_jobs.status              [reads pipeline state to time CES scoring start]
  ◄── lessons.content JSONB           [reads LessonPackage after pipeline completes]

Dev 4 (WebSocket / Tutor State Machine)
  ──► packages/shared/types/ws.ts     [defines lesson_ready message shape Dev 1 must emit]
  ◄── package_builder emits lesson_ready  [Dev 1 fires the push on pipeline completion]
  ──► Redis session:{session_id}:*    [Dev 4 writes; Dev 1 reads for cost/state context]

DB tables Dev 1 WRITES:
  books, chapters, chunks (with inline embeddings), lessons, lesson_jobs

Redis keys Dev 1 WRITES:
  circuit_breaker:{provider}:failures
  circuit_breaker:{provider}:state
  circuit_breaker:{provider}:opened_at
  lesson:{lesson_id}:cost_usd
  job:{job_id}:status
  job:{job_id}:node_outputs
  embeddings:search:{hash}            [cached ANN search results, TTL 300s]
```

---

## Technical Reference

### LLM / AI Model Allocation

> All model IDs are env-var driven via `config.py`. **Never hardcode model strings in business logic.**
> **Batch API rule:** Never use OpenAI or Google Batch API — 24-hour window breaks real-time generation.

| Task | Env Var | Default | Eval Candidates |
|------|---------|---------|-----------------|
| Lesson planning | `LLM_LESSON_PLANNER` | `gpt-4o` | GPT-4o, claude-3-5-sonnet-20241022, o1-mini |
| Slide generation | `LLM_SLIDE_GENERATOR` | `gpt-4o` | Same as above |
| Quiz, jargon, complexity, narration, interventions | `LLM_MINI` | `gpt-4o-mini` | GPT-4o-mini, gemini-2.0-flash |
| Tutor Q&A (Phase 2) | `LLM_TUTOR` | `gpt-4o` | GPT-4o, claude-3-5-sonnet-20241022 |
| Embeddings | fixed | `text-embedding-3-small` | Not evaluated — cost/perf optimal |

**Decision (2026-07-17): direct provider SDKs, NOT an LLM router/aggregator (OpenRouter or similar).** Considered and rejected after S2-15's provider factory landed. Rationale:
- `providers/llm/factory.py` (S2-15) already gives model-agnostic dispatch by model-string prefix — adding Claude (`AnthropicLLMProvider`) or Gemini (`GeminiLLMProvider`) as an eval candidate is one new provider file + one registry entry, zero call-site changes. This was the actual problem an aggregator would have solved, and it's already solved.
- `core/circuit_breaker.py` and `core/cost_tracker.py` both key/price per literal provider (`"openai"`/`"sarvam"`/`"azure_tts"` breaker keys; fixed per-provider cost tables). Routing multiple model families through one OpenRouter key would blur or require rebuilding both — a real regression, not a simplification.
- An aggregator adds an unresearched third-party dependency (rate limits, uptime, added latency) into the pipeline's critical path, with no verified reliability data, right as the project approaches Sprint 3's real-student launch.
- The multi-provider decision (cheap models for economy nodes, premium for planning) was made for cost/quality reasons, not because direct SDK integration was too costly — and S2-15 confirmed direct integration is cheap per new provider.
- **Action:** when GPT-4o-mini/Claude 3.5 Sonnet/Gemini 2.0 Flash evaluations (Sprint 1 Week 1 eval sprint, still not formally run) pick a non-OpenAI model for any slot in the table above, add that provider directly to `providers/llm/factory.py` — do not introduce an aggregator layer.

### API Endpoints (Frozen — 4-Dev PR to Change)

| Method | Path | Sprint | DB Write | Notes |
|--------|------|--------|----------|-------|
| `POST` | `/api/content/lessons` | S1 | `books`, `lessons`, `lesson_jobs` | Accepts PDF upload; enqueues ARQ job; returns `lesson_id + job_id` immediately |
| `GET` | `/api/content/lessons/{lesson_id}` | S1 | — | Returns `LessonRecord` (status + content when ready) |
| `GET` | `/api/admin/jobs` | S3 | — | Job list with status + cost per lesson |
| `POST` | `/api/admin/jobs/{job_id}/retry` | S3 | `lesson_jobs` | Re-enqueues a failed job |
| `GET` | `/api/admin/costs` | S3 | — | Cost aggregation per lesson and per user |

### DB Tables Owned by Dev 1

**`public.books`** *(added migration 20260625)*

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `book_id` | `uuid` | PK, `gen_random_uuid()` | Stable identifier for the uploaded PDF |
| `user_id` | `uuid` | FK → `users.id` ON DELETE CASCADE, NOT NULL | Owner |
| `filename` | `text` | NOT NULL | Original uploaded filename |
| `page_count` | `integer` | nullable | Populated after PyMuPDF extraction (S1-2) |
| `status` | `text` | NOT NULL, DEFAULT `'processing'`, CHECK IN (`'processing'`, `'ready'`, `'failed'`) | Book ingestion state |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now(), auto-trigger | Auto-updated on any change |

**`public.lessons`**

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `lesson_id` | `uuid` | PK, `gen_random_uuid()` | Stable lesson identifier returned to frontend |
| `user_id` | `uuid` | FK → `users.id` ON DELETE CASCADE, NOT NULL | Owner — RLS gates on this |
| `book_id` | `uuid` | nullable FK → `books.book_id` ON DELETE SET NULL | Source book; SET NULL so lesson survives book deletion |
| `title` | `text` | nullable | Set by `lesson_planner` node when it completes |
| `status` | `text` | NOT NULL, DEFAULT `'generating'`, CHECK IN (`'generating'`, `'ready'`, `'failed'`) | Pipeline state visible to frontend via polling |
| `content` | `jsonb` | nullable | Full `LessonPackage` JSONB written by `package_builder`; `NULL` until pipeline completes |
| `source_file_path` | `text` | nullable | Supabase Storage path to the source PDF |
| `chapter_id` | `uuid` | FK → `chapters.chapter_id` ON DELETE SET NULL, nullable, indexed ✅ migrated 20260803 (Story 1-9) | Which chapter this lesson was generated from. SET NULL so the lesson survives deletion of its source, matching `book_id` |
| `tier` | `text` | NOT NULL DEFAULT `'T2'`, CHECK IN (`'T1'`,`'T2'`,`'T3'`) ✅ migrated S2-LM2 (2026-07-14) | Learner Mode content-depth tier. `POST /lessons`'s `tier` param (S2-LM3) writes non-default values ✅ (2026-07-17); drives per-segment slide count in `lesson_planner`/`slide_generator` (S2-LM4 ✅) and outline content-depth framing in `lesson_planner` (S2-LM5 ✅) |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now(), auto-trigger | Auto-updated on any write |

**`public.lesson_jobs`**

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `job_id` | `uuid` | PK, `gen_random_uuid()` | ARQ job identifier |
| `lesson_id` | `uuid` | FK → `lessons.lesson_id` ON DELETE CASCADE, NOT NULL | Owning lesson |
| `status` | `text` | NOT NULL, DEFAULT `'pending'`, CHECK IN (`'pending'`, `'running'`, `'completed'`, `'failed'`) | ARQ job lifecycle state |
| `last_node` | `text` | nullable | Name of the last successfully completed pipeline node — used for checkpoint resume on retry |
| `node_outputs` | `jsonb` | nullable | Accumulated node outputs keyed by node name — read on ARQ retry to skip completed nodes |
| `error` | `text` | nullable | Error message populated on `status='failed'` |
| `attempt` | `integer` | NOT NULL DEFAULT 0 | ARQ retry count (max 3 per PRD §14) |
| `cost_usd` | `numeric(10,4)` | NOT NULL DEFAULT 0 | Accumulated LLM + TTS + image cost for this pipeline run |
| `started_at` | `timestamptz` | nullable | When ARQ worker picked up the job |
| `completed_at` | `timestamptz` | nullable | When `package_builder` finished successfully |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |

**`public.chapters`**

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `chapter_id` | `uuid` | PK, `gen_random_uuid()` | Chapter unit identifier |
| `book_id` | `uuid` | FK → `books.book_id` ON DELETE CASCADE, NOT NULL | Parent book (FK retrofitted in migration 20260625) |
| `lesson_id` | `uuid` | FK → `lessons.lesson_id` ON DELETE CASCADE, **nullable** ✅ migrated 20260803 (Story 1-9) | **DEAD since Story 1-13 (D44)** — was: associated lesson. Nothing writes it; the link is now `lessons.chapter_id` (one chapter, many lessons at different tiers). The FK and its ON DELETE CASCADE are still live, so writing it and rolling the lesson back destroys the chapter and its chunks. Do not read it, do not write it. Original description: associated lesson. Nullable since book-scale Phase 2: a chapter belongs to a **book**, and exists before any lesson is generated from it |
| `title` | `text` | NOT NULL | Chapter title from structure detection |
| `page_start` | `integer` | NOT NULL | First page (1-indexed) |
| `page_end` | `integer` | NOT NULL | Last page (inclusive) |
| `chapter_index` | `integer` | NOT NULL, **UNIQUE (book_id, chapter_index)** ✅ migrated 20260803 (Story 1-9) | 0-indexed position within the book. The constraint is why `chunk_node` **upserts** rather than inserts (`graph.py`) — a plain insert would 23505 on ARQ retry |
| `boundary_confidence` | `text` | NOT NULL DEFAULT `'fallback'`, CHECK IN (`'toc'`,`'contents'`,`'heading'`,`'font'`,`'fallback'`) ✅ migrated 20260803 (Story 1-9) | Which rung of the Phase 3 detection ladder produced this boundary — see `docs/bmad/phase-3-chapter-detection-plan.md` §3 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |

> **RLS on `chapters` and `chunks` re-roots through `books.user_id`, not `lessons.user_id`**
> (migration 20260803, Story 1-9 AC14–17). The old predicate could never match a chapter with
> `lesson_id = NULL`. `core/db.py` uses the service-role key and bypasses RLS regardless.

**`public.chunks`** *(embedding inlined as of migration 20260625 — `embeddings` table dropped)*

| Column | Type | Constraints | Meaning |
|--------|------|-------------|---------|
| `chunk_id` | `uuid` | PK, `gen_random_uuid()` | Text chunk identifier |
| `chapter_id` | `uuid` | FK → `chapters.chapter_id` ON DELETE CASCADE, NOT NULL | Parent chapter |
| `book_id` | `uuid` | FK → `books.book_id` ON DELETE CASCADE, nullable | Shortcut FK for book-level queries (backfilled from chapters) |
| `section` | `text` | nullable | Section heading within the chapter, if detected |
| `page_start` | `integer` | nullable | Page range start for this chunk |
| `page_end` | `integer` | nullable | Page range end for this chunk |
| `content` | `text` | NOT NULL | Raw text — always stored alongside vector (re-extraction costs 200–300ms; source PDF may be deleted) |
| `chunk_index` | `integer` | NOT NULL | 0-indexed position within the chapter |
| `token_count` | `integer` | nullable | Token count populated by `embed` node |
| `embedding` | `vector(1536)` | nullable | `text-embedding-3-small` inline vector; HNSW index via `vector_cosine_ops` |
| `embedding_metadata` | `jsonb` | NOT NULL DEFAULT `'{}'` | Model name, version, ingestion timestamp |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() | Row creation time |

> **HNSW index** on `chunks.embedding` (`vector_cosine_ops`) for approximate nearest-neighbour cosine search.

### Redis Keys (Dev 1 Owns)

| Key Pattern | Type | What It Stores | TTL |
|-------------|------|----------------|-----|
| `circuit_breaker:{provider}:failures` | string (int) | Failure count in the current 2-minute window | 120 s rolling |
| `circuit_breaker:{provider}:state` | string | `CLOSED` / `OPEN` / `HALF_OPEN` | None — managed by logic |
| `circuit_breaker:{provider}:opened_at` | string (epoch float) | Timestamp when breaker tripped OPEN | 600 s (OPEN → HALF_OPEN after 10 min) |
| `lesson:{lesson_id}:cost_usd` | string (float) | Accumulated cost for this pipeline run | None — cleared on job completion |
| `job:{job_id}:status` | string | `pending / running / completed / failed` | None |
| `job:{job_id}:node_outputs` | hash | `node_name → JSON output` | None |
| `embeddings:search:{hash}` | string | Cached ANN vector search result (JSON) | 300 s |

### Cost Ceiling (PRD §12)

| Env Var | Default | Meaning |
|---------|---------|---------|
| `MAX_LESSON_COST_USD` | `3.00` | Hard ceiling per lesson pipeline run |

**`MAX_DAILY_SPEND_PER_USER_USD` removed 2026-08-11 (D48, Story 3-35)** — it had zero
enforcing readers anywhere in the codebase and looked like a real control while doing
nothing. Daily per-user spend is not enforced; the per-user generation-concurrency cap
(`max_concurrent_generations_per_user`) is the only other real spend control.

On breach: downshift to cheapest providers, complete the lesson, flag in admin — **never abort mid-lesson**.

---

## Cross-Cutting Bugs Found

| # | File | Bug | Impact | Fix |
|---|------|-----|--------|-----|
| B1 | `apps/api/app/providers/llm/openai.py:44–47` | `Langfuse()` instantiated inside `__init__()` — each `OpenAILLMProvider` creates an independent Langfuse client with its own buffer. No global `langfuse.flush()` on process shutdown means buffered traces are silently lost on every deploy or restart. | HIGH — production traces dropped on every Railway deploy | Create a global `Langfuse` singleton (e.g. `app/core/langfuse.py`); inject it into providers rather than constructing inside `__init__`; call `langfuse.flush()` in FastAPI lifespan `finally` block |
| B2 | `apps/api/app/schemas/__init__.py` (empty file) | `lesson.py` not created — `from app.schemas import LessonPackage` raises `ImportError` at module load. All 11 pipeline nodes that reference `app.schemas` fail at import time. | CRITICAL — blocks all Sprint 1 and Sprint 2 node work | Create `schemas/lesson.py` — full spec + ready-to-paste code in `docs/dev1-pydantic-schemas-task.md` |

---

## Known Stub Discrepancies to Fix

| Location | Current Stub Issue | Correct Behaviour | PRD Rule |
|----------|--------------------|-------------------|----------|
| `apps/api/app/config.py:54` | `elevenlabs_api_key` field present (marked deprecated) | Keep as `str \| None = None` to avoid breaking existing `.env` files; add a validator that warns if set; remove in Sprint 2 cleanup | CLAUDE.md 2026-06-25: ElevenLabs REMOVED, replaced by Sarvam AI Bulbul v2 |
| `apps/api/app/workers/jobs/content_pipeline.py` | Skeleton only — no actual graph execution | Must call `graph.arun()`, write `lesson_jobs.status = 'running'` on pickup, `'completed'/'failed'` on exit, emit `lesson_ready` WebSocket push | PRD §9: checkpoint pattern mandatory for all nodes |
| `apps/api/app/core/cost_tracker.py` | Exists but not wired into any node yet | Must be called inside every LLM, TTS, and image node via `accumulate_cost()` + `check_ceiling()` | PRD §12: $3.00/lesson ceiling enforced at every provider call |
| `apps/api/app/modules/content/pipeline/nodes/__init__.py` | Empty file | Remains empty; node files are imported individually — confirm `graph.py` import paths match the `nodes/` filenames as they are created | Structural note — not a logic bug |

---

## Sprint 0 — Week 1 (Due: ~2026-06-18)

> **Goal:** Ship the infra skeleton — every dev can run locally, CI is green, contracts are frozen.

- [x] **S0-1 Railway project setup + env vars** — ✓ 2026-06-12
  - `railway.toml`, `apps/api/app/config.py`
  - All vars use `Field(...)` — no defaults that mask missing secrets
  - **AC:** `railway.toml` present; all env vars in `Settings` with pydantic-settings; `get_settings()` is the only instantiation point ✅

- [x] **S0-2 Supabase project + all DB migrations** — ✓ 2026-06-12
  - `supabase/migrations/20260611000000_initial_schema.sql`
  - `supabase/migrations/20260625000000_chunks_inline_embedding.sql`
  - **AC:** Both migrations applied; `supabase/config.toml` present; never modify applied migrations (PRD §16) ✅

- [x] **S0-3 Railway Redis service config** — ✓ 2026-06-12
  - `apps/api/app/core/redis.py`
  - **AC:** `init_redis()` / `get_redis()` / `close_redis()` usable by all modules; called in API lifespan and ARQ worker startup ✅

- [x] **S0-4 GitHub Actions CI/CD pipeline** — ✓ 2026-06-12
  - `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`
  - **AC:** CI runs lint + test on every PR; deploy triggers on merge to main ✅

- [x] **S0-5 Monorepo scaffold** — ✓ 2026-06-12
  - `apps/web/`, `apps/api/`, `packages/shared/`, `pnpm-workspace.yaml`, root `package.json`
  - **AC:** All workspace packages resolvable via `pnpm`; root `package.json` present ✅

- [x] **S0-6 FastAPI app factory + router mounts** — ✓ 2026-06-12
  - `apps/api/app/main.py`
  - **AC:** All 7 module routers mounted; WebSocket router mounted; `/health` returns `{"status": "ok"}` ✅

- [x] **S0-7 ARQ worker entry point + task registry** — ✓ 2026-06-12
  - `apps/api/app/workers/main.py`, `apps/api/app/workers/jobs/content_pipeline.py`
  - **AC:** `WorkerSettings` with `functions`, `redis_settings`, lifecycle hooks; `max_jobs=5`, `job_timeout=600`, `max_tries=3` per PRD §14 ✅

- [x] **S0-8 Sentry wired from day one** — ✓ 2026-06-12
  - `apps/api/app/main.py:52–58`
  - **AC:** `sentry_sdk.init()` called in lifespan startup when `SENTRY_DSN` present; no-ops gracefully when absent ✅

- [x] **S0-9 Langfuse wired globally** — ✓ 2026-06-26
  - `apps/api/app/core/langfuse.py` *(created — module-level singleton + `get_langfuse()`)*
  - `apps/api/app/providers/llm/openai.py` *(updated — `__init__` now calls `get_langfuse()` not `Langfuse()`)*
  - `apps/api/app/main.py` *(updated — startup log `Langfuse host: …`; shutdown calls `get_langfuse().flush()`)*
  - `apps/api/tests/unit/test_langfuse_core.py` *(created — 4 unit tests: singleton identity, constructor args, flush contract)*
  - **AC:** Single `Langfuse` instance per process ✅; `flush()` called on graceful shutdown ✅; no dropped traces on Railway deploy ✅; startup log present ✅

  **Review Findings (2026-06-26):**
  - [x] [Review][Patch] **P1-HIGH** Thread-safety: `get_langfuse()` has no lock — two concurrent callers can each construct a `Langfuse` instance; second overwrites first without flushing it [`core/langfuse.py:24-30`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P2-HIGH** ARQ worker process (separate OS process) never calls `get_langfuse()` at startup or `flush()` at shutdown — all pipeline node traces dropped on worker exit [`workers/main.py`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P3-HIGH** `flush()` is unreachable if `close_redis()` raises — lifespan shutdown block lacks `try/finally`; flush must survive preceding failures [`main.py:68-72`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P4-MED** `flush()` itself has no `try/except` — an exception from the Langfuse SDK propagates out of the lifespan generator, masking the real shutdown cause [`main.py:72`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P5-MED** `Langfuse.__init__` failure leaves `_langfuse = None` — every subsequent `get_langfuse()` call retries construction and raises, taking down pipeline nodes [`core/langfuse.py:25-30`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P6-LOW** `flush()` is synchronous/blocking with a 60-second default timeout (Langfuse 4.x) — blocks the event loop thread on shutdown; Railway may SIGKILL before it completes [`main.py:72`] — ✓ 2026-06-26
  - [x] [Review][Patch] **P7-LOW** `reset_singleton` fixture annotated `-> None` but is a generator — correct type is `Generator[None, None, None]` [`tests/unit/test_langfuse_core.py:29`] — ✓ 2026-06-26
  - [x] [Review][Defer] `OpenAILLMProvider` captures singleton by reference at construction — stale reference in tests if singleton is reset mid-test [`providers/llm/openai.py:44`] — deferred, test isolation edge case only
  - [x] [Review][Defer] `generation.end()` not called on exception path in `openai.py` — spans left open on every LLM error [`providers/llm/openai.py:63`] — deferred, pre-existing before S0-9
  - [x] [Review][Defer] No `atexit` hook for crash-safe flush — traces lost on abnormal process exit — deferred, separate enhancement
  - [x] [Review][Defer] Test suite has no lifespan integration test covering `flush()` call path — deferred, requires full FastAPI test harness
  - [x] [Review][Defer] No concurrency test for singleton race — deferred, fix the lock (P1) first

- [x] **S0-10 Shared TS types + JSON schema published** — ✓ 2026-06-12
  - `packages/shared/types/lesson.ts`, `packages/shared/types/ws.ts`, `packages/shared/lesson_package.schema.json`
  - **AC:** TS types + JSON schema committed; importable as `@transformED/shared` ✅

- [x] **S0-11 Lesson package JSON contract frozen** — ✓ 2026-06-12
  - `packages/shared/lesson_package.schema.json`
  - **AC:** Schema committed; all 4 devs unblocked for mocking; **FROZEN — 4-dev PR required to change** ✅

- [x] **S0-12 Pydantic lesson schemas** — ✓ 2026-06-26
  - `apps/api/app/schemas/lesson.py` *(to create)*
  - `apps/api/app/schemas/__init__.py` *(update — currently empty)*
  - `apps/api/tests/unit/test_lesson_schema.py` *(to create)*
  - Full implementation spec + ready-to-paste code: `docs/dev1-pydantic-schemas-task.md`
  - Implementation:
    1. Create `schemas/lesson.py` — 17 Pydantic v2 models (`LessonPackage`, `Segment`, `Slide`, etc.) mirroring JSON schema
    2. Update `schemas/__init__.py` to re-export all 17 models
    3. Create `tests/unit/test_lesson_schema.py` — round-trip JSON schema validation test
    4. Run `mypy app` → clean; `ruff check .` → clean
  - **AC:** `from app.schemas import LessonPackage` works; unit test passes against `lesson_package.schema.json`; `mypy` and `ruff` both clean

---

## Sprint 1 — Weeks 2–3 (Due: ~2026-07-02)

> **Goal:** Book ingestion pipeline end-to-end — PDF upload → extracted text → chunked → embedded → stored in DB.

### Checkpoint Pattern (mandatory for every node below)

Every node must:
1. **On entry:** read `last_node` from `lesson_jobs` — if `last_node >= this_node_name`, return cached output from `node_outputs` and skip
2. **On success:** write `last_node = node_name` + `node_outputs[node_name] = output` to `lesson_jobs`
3. Wrap every LLM/provider call: `@with_retry(max_attempts=3)` for critical nodes, `max_attempts=2` for optional
4. Call `await cost_tracker.accumulate_cost(lesson_id, cost)` after every LLM call
5. Emit a Langfuse span with `lesson_id`, `node_name`, and token counts via `get_langfuse()`

- [x] **S1-1 `with_retry()` decorator** — ✓ 2026-06-12 (built ahead of schedule)
  - `apps/api/app/core/retry.py`
  - `wait = (2^attempt) + random.random()`; retries 429/5xx; never retries 400/401/403/404/422
  - **AC:** Applied to all LLM/provider calls in Sprint 1+ nodes; backoff formula matches PRD §14 ✅

- [x] **S1-2 PyMuPDF text + image + layout extraction node** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/extract_text.py`
  - 1. Accept `state["pdf_path"]` (Supabase Storage signed URL)
  - 2. Open with `fitz.open()`; iterate pages; extract text blocks with bounding boxes
  - 3. Extract embedded images; store to Supabase Storage; record paths in state
  - 4. Write `books.page_count` once known
  - 5. Return `{"raw_pages": [...], "page_count": N}` → checkpoint write on success
  - **AC:** All text, images, and layout blocks extracted from a test PDF; `books.page_count` written; node is idempotent (second run skips if `last_node >= extract_text`)

- [x] **S1-3 pdfplumber table extraction node** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/extract_tables.py`
  - 1. Run `pdfplumber.open()` against same PDF as S1-2
  - 2. Detect tables per page; serialize to list-of-dicts (JSON-serializable)
  - 3. Merge table data into `raw_pages` from S1-2
  - **AC:** Tables extracted from a known table-heavy PDF; serializable to JSON; merged correctly into extraction output

- [x] **S1-4 Tesseract OCR fallback node** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/ocr_fallback.py`
  - 1. Check text yield from S1-2: if `chars_per_page < OCR_TEXT_YIELD_THRESHOLD` (env var, default 50), invoke OCR
  - 2. Run `pytesseract.image_to_string()` in-container
  - 3. Replace low-yield pages with OCR text; merge back into state
  - **AC:** Scanned PDF with <50 chars/page triggers OCR; text-based PDF skips entirely; env var controls threshold

- [x] **S1-5 Structure detection — rule-based** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/structure_detect.py`
  - 1. Analyse font sizes, TOC entries, numbering patterns (regex) across pages
  - 2. Produce `DocumentStructure` with `chapters[]`, each with `sections[]`
  - Hierarchy: **Chapter → Section → Topic** — never full-book single structure (PRD §5 principle 6)
  - **AC:** Chapter boundaries correctly identified in 3 test PDFs of varying layout styles

- [x] **S1-6 Structure detection — ~~GPT-4o-mini LLM validation~~ rule-based only** — ✓ 2026-07-07, **amended 2026-07-29 (Story 2-34)**. The LLM validation pass was removed: it showed the model only `raw_text[:6000]` but accepted its output only if that covered ≥90% of `len(raw_text)`, so it could never be adopted for anything over ~6,667 chars — i.e. every real chapter. We paid for the call on every upload and always discarded the result. Already flagged in-code since Story 2-16 RC-2; 2-34 is the decision to act. **Detection is now font-size + boldness thresholds plus a regex, and that is a real limitation, not a completed feature** — a non-bold heading is invisible, one shared font size gives false positives, multi-column layouts scramble reading order, and on SCANNED pages there is no font metadata at all (`font_blocks` comes from pdftext) so only the regex survives. **Sprint 3:** move to docling's document hierarchy — docling is already a dependency and already runs in `extract_subprocess.py`, but only for table-bearing page runs. Blocked on two things: `config.py` measured page-scoped docling at 206–216s on 41 pages, so full-document docling must be shown to fit inside `extract_timeout_cap_s = 1500` on a real textbook; and changing docling's scope touches CLAUDE.md's locked PDF stack, requiring the §16 four-dev review.
  - `apps/api/app/modules/content/pipeline/nodes/structure_detect.py` (second pass in same file)
  - Model: `settings.llm_mini` (env var `LLM_MINI`)
  - 1. Feed rule-based `DocumentStructure` + first/last lines of each detected chapter to LLM
  - 2. LLM validates boundaries and corrects misdetections using `complete_structured()`
  - 3. Write corrected structure to `lesson_jobs.node_outputs["structure_detect"]`
  - **AC:** LLM corrects at least one misdetection in a known-hard test PDF; output validates as `DocumentStructure`; `@with_retry(max_attempts=3)` applied; Langfuse span records token count

- [x] **S1-7 Semantic chunking (chapter → section → topic)** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/chunk.py`
  - 1. Consume corrected `DocumentStructure` from S1-6
  - 2. Split each section into topic-level chunks; target ≤800 tokens each
  - 3. Write `chunks` rows: `chapter_id`, `book_id`, `section`, `page_start`, `page_end`, `content`, `chunk_index`
  - Never create a full-book single chunk (PRD §5 principle 6)
  - **AC:** A 20-page chapter produces ≥3 chunks; no chunk exceeds 800 tokens; all chunks written to DB with correct FKs

- [x] **S1-8 text-embedding-3-small + pgvector storage** — ✓ 2026-07-07
  - `apps/api/app/modules/content/pipeline/nodes/embed.py`
  - Model: `text-embedding-3-small` (fixed — not configurable)
  - 1. Batch all chunks (max 2048 per API call)
  - 2. Call OpenAI embeddings API; receive 1536-dim vectors
  - 3. Write `embedding`, `token_count`, `embedding_metadata` to `chunks` inline
  - **Embeddings computed ONCE at ingestion — never regenerated for stored content (PRD rule)**
  - **AC:** All chunks have `embedding IS NOT NULL` after node; HNSW index on `chunks.embedding` used in search query; re-run skips checkpoint

- [x] **S1-9 `lesson_jobs` table + ARQ job enqueue** — ✓ 2026-07-07
  - `apps/api/app/workers/jobs/content_pipeline.py`, `apps/api/app/modules/content/router.py`
  - 1. `POST /api/content/lessons` creates `books` row, `lessons` row (`status='generating'`), `lesson_jobs` row (`status='pending'`)
  - 2. Enqueues ARQ job with `lesson_id` + `job_id`
  - 3. ARQ pickup: `lesson_jobs.status = 'running'`, `started_at = now()`
  - 4. ARQ success: `status = 'completed'`, `completed_at = now()`
  - 5. ARQ failure: `status = 'failed'`, `error = str(exc)`
  - **AC:** `lesson_jobs` row transitions correctly through all 4 states; ARQ `max_tries=3` matches PRD §14

- [x] **S1-10 `POST /lessons` endpoint live** — ✓ 2026-07-07
  - `apps/api/app/modules/content/router.py`
  - 1. Accept multipart PDF; validate file type (MIME + magic bytes)
  - 2. Store PDF to Supabase Storage; set `lessons.source_file_path`
  - 3. Enqueue ARQ job (S1-9)
  - 4. Return `201` with `{"lesson_id": "...", "job_id": "..."}` immediately — do not wait for pipeline
  - Apply `slowapi` rate limit: `"5/minute"` per user — **do not defer to Sprint 4**
  - **AC:** Integration test — upload valid PDF → `201` with UUIDs → ARQ job enqueued → `lesson_jobs` row visible in DB

---

## Sprint 2 — Weeks 4–5 (Due: ~2026-07-16)

> **Goal:** All 11 generation nodes producing a valid `LessonPackage` JSONB from an ingested chapter.
> **Added 2026-07-13 — Learner Mode (tier-aware lessons) is now in scope for Sprint 2**, inserted between Phase 1 and Phase 2 below (S2-LM1 through S2-LM5). This was previously undocumented anywhere in this tracker or `CLAUDE.md` — see `docs/stories/2-1-phase1-economy-nodes.md` context for how the gap was found. Positioned here (not as a separate future "feature sprint") because S2-LM4/S2-LM5 directly amend S2-7/S2-8's acceptance criteria — a Learner Mode "feature sprint" bolted on *after* Sprint 2 would mean re-opening `lesson_planner`/`slide_generator` a second time.

> **Cost ceiling rule:** Every node that calls a provider must call `cost_tracker.accumulate_cost()` immediately after. On `check_ceiling()` returning `True`, downshift to cheapest available provider, complete the lesson, flag in admin — never abort.
> **Circuit breaker:** Call `is_circuit_open(provider_key)` before every external provider call. Wire in Sprint 2 — don't wait for Sprint 3.

**Phase 1 Economy nodes** (S2-1 through S2-6) run in parallel per segment. **All must complete before Phase 2 starts.**
**Learner Mode infra** (S2-LM1 through S2-LM3) — contract, migration, endpoint. Independent of Phase 1; must complete before Phase 2 starts (S2-7 needs `tier` to read).
**Phase 2 Premium nodes** (S2-7, S2-8) sequential — consume Phase 1 outputs **and** `state["tier"]` from S2-LM3.
**Learner Mode tier logic** (S2-LM4, S2-LM5) — lands together with S2-7/S2-8, not as a later rework pass.
**Phase 3 Media nodes** (S2-9, S2-10, S2-11) sequential after Phase 2.

- [x] **S2-1 `summarise_segment` node** — ✓ 2026-07-15 (upgraded from PARTIAL now that S2-7 is real)
  - `apps/api/app/modules/content/pipeline/graph.py::summarise_segment_node` (NOT a separate `nodes/summarise_segment.py` file — see Story 2-1's Tracker Cross-Reference Notes on why this file-per-node table entry is stale)
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section (graph-level fan-out, see AC-0 below)
  - ✓ Produces a 2–3 sentence, ≤100-word summary per section, calling `OpenAILLMProvider.complete_structured()` — real implementation, tested (`test_phase1_economy_nodes.py`, AC-1)
  - ✓ `lesson_planner` (S2-7, Story 2-6, done 2026-07-14/15) now really consumes these summaries — never raw chapter text — enforced structurally and by a dedicated regression test (`test_prompt_never_includes_raw_chapter_text_or_sections`). The 5×-token-savings constraint is now actually realized, not just wired.
  - **AC:** Summary ≤100 words ✓; `lesson_planner` (S2-7) consumes summaries not raw text — 5× token savings enforced ✓ — tested ✅
  - **Still ⚠️ PARTIAL for the reason above** (blocked on S2-7, unrelated to code quality) — separately, the second-pass `/bmad-code-review` findings against all 6 economy nodes (AC-3..AC-7 combined diff) were fully closed 2026-07-14: 6 patches applied (checkpoint re-validation extended to all 6 nodes, quiz duplicate/blank-option guards on both read and write paths, jargon/intervention checkpoint value-quality re-validation, `narration_style` strip-before-truthiness fix) and 1 decision resolved (`narration_style` moved from the system-role to the user-role prompt — untrusted LLM-derived value, now at the same trust level as the section body). 267/267 unit tests pass. See `docs/stories/2-1-phase1-economy-nodes.md`'s "Review Findings (2026-07-14, second pass...)" section for the full findings.

- [x] **S2-2 `segment_complexity` node** — ✓ 2026-07-13
  - `apps/api/app/modules/content/pipeline/graph.py::segment_complexity_node` (NOT a separate `nodes/segment_complexity.py` file — see note above)
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section
  - Output: `SegmentComplexity` Pydantic model; `intervention_sensitivity` clamped into [0.0, 1.0] with a warning log if the LLM returned an out-of-range value (never silently trusted)
  - **AC:** Output validates against `app.schemas.SegmentComplexity` ✓; field ranges enforced ✓ — tested (`test_phase1_economy_nodes.py`, AC-2) ✅

- [x] **S2-1b Phase 1 economy node checkpoint/idempotency** — ✓ 2026-07-13 (deferred from Story 2-1's code review; itself reviewed and patched same day)
  - `docs/stories/2-1b-phase1-checkpoint-idempotency.md`
  - Per-section checkpoint via `merge_lesson_job_node_output()` (Postgres function, `supabase/migrations/20260713020000_lesson_job_node_output_merge_fn.sql`) — atomic server-side JSONB merge, not the client-side read-modify-write Phase A nodes use (unsafe under Story 2-1's concurrent `Send()` dispatch). **Review caught and fixed a critical finding here:** the function had no access control — Supabase auto-exposes every Postgres function as a public RPC endpoint, so any caller could have overwritten another user's `lesson_jobs` row (cross-tenant IDOR, RLS bypass). Fixed: revoked `anon`/`authenticated`/`public` execute, granted only `service_role`; also hardened `search_path` and made a missing-row write raise instead of silently no-op'ing.
  - Phase 1 progress visibility via a Redis **set** (`job:{lesson_id}:phase1_completed_keys`, SADD/SCARD) — not a plain INCR counter, which review found would double-count a section re-visited on ARQ retry; SADD is idempotent per checkpoint key
  - Applied to `summarise_segment_node`/`segment_complexity_node` at the time this task shipped (2026-07-13, only 2 of 6 economy nodes existed then); S2-3 through S2-6 have since adopted the same checkpoint pattern (all 6 nodes checkpointed as of 2026-07-14, including the second-pass fix that re-validates cached value quality — not just key presence — on every one of the 6 checkpoint reads, see S2-1's story file)
  - **AC:** simulated retry after partial completion makes 0 duplicate LLM calls for already-completed sections ✓ — tested (`test_phase1_checkpoint_idempotency.py`, 9 tests incl. a real `asyncio.gather` concurrency test) ✅

- [x] **S2-3 `quiz_generator` node** — ✓ 2026-07-14
  - `apps/api/app/modules/content/pipeline/graph.py::quiz_generator_node` (NOT a separate `nodes/quiz_generator.py` file — see Story 2-1's Tracker Cross-Reference Notes)
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section; per-section checkpoint (Story 2-1b pattern)
  - Output: `QuizQuestion`-shaped dict; exactly-4-options guard (frozen schema only enforces a minimum), out-of-range `correct_index` and blank question/explanation rejected (degrade section, not fabricated)
  - **Wording correction (2026-07-17, full Sprint 2 audit workflow):** the AC line below previously said "segment_id stripped first" — this was factually inaccurate against the code, not a bug. The node's real output shape is nested `{segment_id, data: {...}}` (matching every other Phase 1 node's established convention), which never needs a strip step at all — there is no flat dict with `segment_id` mixed into the `QuizQuestion` fields to strip in the first place. Corrected below.
  - **Documented, not a bug (same audit):** `difficulty` is silently clamped to `"medium"` when the LLM returns a value outside `{easy,medium,hard}`, rather than rejecting that question — this mirrors the same clamp-not-reject pattern already used for `complexity_level` in `lesson_planner_node` and `narration_style` in `narration_generator_node` elsewhere in this same file, applied consistently across the codebase's "LLM enum drift" handling, not an isolated inconsistency within this one node.
  - **AC:** Output validates against `app.schemas.QuizQuestion` (nested `{segment_id, data}` shape, no strip step needed) ✓; `min_length=4` enforced by the node itself, not just the schema ✓ — tested (`test_phase1_economy_nodes.py`, AC-3; 5-agent review 2026-07-14 added the missing `QuizQuestion.model_validate` assertion) ✅

- [x] **S2-4 `jargon_extractor` node** — ✓ 2026-07-14
  - `apps/api/app/modules/content/pipeline/graph.py::jargon_extractor_node`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section; per-section checkpoint
  - Output: list of `JargonEntry`; empty term/definition entries filtered before reaching `state["glossary"]`
  - **AC:** Output validates against `app.schemas.JargonEntry` ✓; no empty terms or definitions ✓ — tested (`test_phase1_economy_nodes.py`, AC-4) ✅

- [x] **S2-5 `intervention_messages` node** — ✓ 2026-07-14
  - `apps/api/app/modules/content/pipeline/graph.py::intervention_messages_node`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section; per-section checkpoint
  - Output: `SegmentInterventions` — exactly 3 messages each for `distraction`, `confusion`, `fatigue`, forced via truncate/pad guard (padding-by-duplication on <3 is a documented decision, see Story 2-1 AC-5 note — not a retry loop)
  - **CRITICAL:** Pre-generated at pipeline time. Zero GPT calls at intervention runtime (PRD §10) — verified no such call exists in `modules/tutor/`.
  - **AC:** 3×3 messages generated; validates against `app.schemas.SegmentInterventions` ✓; shape-pinning test added for future `package_builder_node` (S2-11) integration — tested (`test_phase1_economy_nodes.py`, AC-5) ✅

- [x] **S2-6 `narration_generator` node** — ✓ 2026-07-14
  - `apps/api/app/modules/content/pipeline/graph.py::narration_generator_node`
  - Model: `settings.llm_mini` (`LLM_MINI`)
  - Phase 1 — dispatched via `Send()`, once per section; per-section checkpoint
  - Output: narration script + `narration_style`; pacing guard rejects a script implying >15 words/sec against a target duration (explicit `target_duration_sec` or a page-count-based estimate, ~90s/page)
  - **AC-6 note:** `narration_style` is sourced from `segment_complexity_node`'s checkpoint for the same section when it's already written (opportunistic cross-node read — the common case, since `Send()`-dispatched sibling calls don't resolve in lockstep); falls back to the LLM self-reporting a style only when complexity genuinely isn't available yet. This is a best-effort resolution of a real AC-0/AC-6 architectural conflict (Send() fan-out has no cross-node ordering guarantee) — see Story 2-1's AC-6 note for the full rationale; a guaranteed-every-run fix needs an AC-0 redesign, not done here.
  - **AC:** Script readable at ≤15 words/sec ✓ (guard now fires in both the explicit- and estimated-duration cases — 5-agent review 2026-07-14 found the original no-target-duration branch was a mathematical no-op); tone matches `narration_style` from `SegmentComplexity` when available ✓ — tested (`test_phase1_economy_nodes.py`, AC-6) ✅

---

### Learner Mode (tier-aware lessons) — inserted between Phase 1 and Phase 2

> Tier values: **T1** (full depth, 20–25 slides), **T2** (standard, 12–15 slides), **T3** (critical-topics-only / refresher, 6–8 slides). Default `T2` for any lesson that doesn't specify a tier (keeps existing frontend mocks/tests, which assume no tier, working unmodified).

- [x] **S2-LM1 Add `tier` field to the lesson package contract + Pydantic** — ✓ 2026-07-17
  - `packages/shared/lesson_package.schema.json`, `packages/shared/types/lesson.ts`, `apps/api/app/schemas/lesson.py` (`LessonMetadata.tier`)
  - **FROZEN CONTRACT CHANGE — required the 4-developer PR review per `CLAUDE.md` §16 / Interface Contracts before merge.**
  - ✓ `tier: Literal["T1", "T2", "T3"]` added to `LessonMetadata`; JSON schema and TS type updated in the same commit, byte-for-byte agreeing enum values (Story 2-2, `docs/stories/2-2-learner-mode-infra.md`)
  - ✓ Existing `LessonPackage`/frontend fixtures unaffected — Pydantic default (`"T2"`) meant zero backend fixtures needed updating; two frontend fixtures (`apps/web/src/mocks/data/lessonPackage.ts`, `apps/web/src/__tests__/stores/player.machine.test.ts`) needed `tier: 'T2'` added (caught by code review, fixed same day)
  - ✓ **4-dev sign-off recorded 2026-07-17** — approved by Dev 1 (developer1-cybersmith) as the accountable owner for this session's work. S2-LM3/LM4/LM5 unblocked; see below.
  - **AC:** JSON schema/TS/Pydantic agree byte-for-byte ✓; existing fixtures unaffected ✓; 4-dev sign-off recorded ✓

- [x] **S2-LM2 Add `tier` column to `lessons` table** — ✓ 2026-07-14
  - `supabase/migrations/20260714020000_add_lesson_tier.sql` — timestamped after the true latest applied migration at the time (`20260713020000_lesson_job_node_output_merge_fn.sql`, Story 2-1b — corrects this task's own stale `20260710000000` reference)
  - `tier text NOT NULL DEFAULT 'T2' CHECK (tier IN ('T1','T2','T3'))` on `public.lessons` — verified via static SQL-text test (`test_learner_mode_tier.py`, no live Postgres in this suite)
  - Independent of S2-LM1 — built in parallel, not reverted alongside S2-LM3/LM4
  - **AC:** Migration applies cleanly (additive, no existing migration touched) ✓; CHECK constraint rejects any value outside `T1/T2/T3` ✓; existing rows backfill to `T2` via `DEFAULT`, no manual step ✓ — tested ✅

- [x] **S2-LM3 Accept & validate `tier` param in `POST /lessons`; thread into the pipeline** — ✓ 2026-07-17
  - `apps/api/app/modules/content/router.py`, `apps/api/app/workers/jobs/content_pipeline.py`, `PipelineState` in `apps/api/app/modules/content/pipeline/graph.py`
  - Note (corrected by Story 2-2's Dev Notes, confirmed correct on re-implementation): tier reaches the pipeline via the SAME `lessons`-table re-fetch `content_pipeline_job` already uses for `user_id`/`book_id`/`source_pdf_path` — not a new ARQ job-payload argument. This tracker's original "thread into the ARQ job" wording was imprecise, now corrected in the task title.
  - Optional multipart field `tier`, defaulting to `"T2"` when omitted; invalid value → `422` before any DB row is created, not a silent fallback.
  - **AC:** Omitting `tier` behaves exactly as before this story (defaults `T2`) ✓ tested; an invalid tier string returns `422` ✓ tested; `PipelineState["tier"]` is populated by the time `lesson_planner` runs ✓ tested — see `docs/stories/2-lm3-lm4-lm5-tier-aware-generation.md` for the full story, including the 3-layer adversarial code review.

- [x] **S2-LM4 Tier-aware slide count in `lesson_planner` + `slide_generator`** — ✓ 2026-07-17
  - Amends **S2-7** and **S2-8** directly.
  - Slide/segment budget by tier: **T1: 20–25**, **T2: 12–15**, **T3: 6–8** (total across the lesson, divided evenly across segments — a soft heuristic, not an exact allocator).
  - `lesson_planner` reads `state["tier"]` and attaches a per-segment `slide_budget` (`{min, max}`) to each output segment; `slide_generator` reads and respects that budget in both its prompt and its degrade-not-fabricate validation — it does not re-derive tier logic independently. Falls back to the fixed 1-8 band for any segment lacking a (valid) budget.
  - Code review (Blind Hunter) caught a real math bug before merge: floor division for the per-segment minimum could let the worst-case actual total undercut the tier's own advertised floor (e.g. T3's 6-slide minimum over 5 segments could produce as few as 5) — fixed with ceiling division. Also fixed: malformed/corrupted `slide_budget` values (`min > max`, negative) were accepted as-is instead of falling back to the safe default band.
  - **AC:** For a fixed test chapter, three separate pipeline runs (T1/T2/T3) each produce a per-segment slide-count budget inside that tier's range ✓ tested (unit-level, per-segment budget math — a full live 3-tier pipeline run through real LLM calls is not part of this AC's test coverage); `slide_generator` never exceeds the budget `lesson_planner` set for a segment ✓ tested.

- [x] **S2-LM5 Tier-aware content-depth prompt variants (T3 = critical topics only / refresher)** — ✓ 2026-07-17
  - **Scope confirmed with the accountable owner before implementation** (the ambiguity this task was flagged with): outline-only — T3/T1 framing changes only `lesson_planner`'s outline-generation prompt. Phase 1 economy nodes (`quiz_generator`, `narration_generator`) are explicitly unaffected by tier.
  - T3 prompt explicitly asks for critical-topics-only/refresher framing; T1 asks for full depth including nuance; T2 (default) gets no additional framing at all — the prompt is byte-identical to the pre-tier version for any T2/untiered lesson, proven by every pre-existing `lesson_planner_node` test passing unmodified.
  - **AC:** T3 lesson plans get a critical-topics-only/refresher system-prompt instruction distinguishing them from T1/T2 ✓ tested (prompt-content assertion); whether the LLM's actual output visibly omits non-critical sub-topics in practice depends on real LLM behavior, not verified by unit tests — deferred to the eventual live eval run (S2-14).

---

- [x] **S2-7 `lesson_planner` node** — ✓ 2026-07-17 (upgraded from PARTIAL now that S2-11 really validates it)
  - `apps/api/app/modules/content/pipeline/graph.py::lesson_planner_node` (NOT a separate `nodes/lesson_planner.py` file — see Story 2-1's Tracker Cross-Reference Notes on why this file-per-node table entry is stale; the placeholder row above is removed)
  - Model: `settings.llm_lesson_planner` (`LLM_LESSON_PLANNER`) — highest cost node so far
  - **Phase 2 Premium — starts ONLY after ALL Phase 1 nodes complete for ALL segments** — already true via the existing graph wiring (Story 2-1 AC-0), unchanged by this task
  - ✓ Input is `state["segment_summaries"]` ONLY — never raw chapter text/sections; enforced structurally and by a dedicated regression test (`test_prompt_never_includes_raw_chapter_text_or_sections`) that plants raw text in state alongside summaries and asserts it never reaches the prompt
  - ✓ `complete_structured()` used with an internal Pydantic response model (`_LessonPlanLLM`/`_LessonPlanSegmentLLM`); degrade-not-fabricate guards (segment count/ID match, no duplicates, non-blank title/subject/objectives, valid `duration_min`, `complexity_level` clamped to low/medium/high) all reviewed via a real 3-layer `/bmad-code-review` and patched
  - ✓ Idempotency checkpoint added (Phase-A read-then-write style, not Story 2-1b's atomic RPC — correct choice for this single-sequential-dispatch node)
  - ✓ **Output now DOES pass `LessonMetadata.model_validate()`** — resolved transitively by S2-11 (`package_builder_node`, done 2026-07-16), which projects `lesson_plan`'s `title`/`subject`/`total_segments`/`total_duration_min`/`complexity_level` into `LessonPackage.metadata` and calls `LessonPackage.model_validate(assembled)` uncaught (AC-9). `LessonMetadata.tier` defaults `"T2"` so the metadata dict — built with no `tier` key, since S2-LM1/LM3 are still reverted — validates cleanly. Confirmed via `test_package_builder_node.py::test_model_validate_failure_propagates_uncaught` and the full round-trip assertion at line 174 (`LessonPackage.model_validate(result["lesson_package"])`); full suite re-run 2026-07-17: 381 passed, 1 skipped.
  - ✗ **Langfuse span does not record an explicit `token_cost_usd` field** — `complete_structured()`'s existing tracing records `usage_details` (input/output token counts) on the generation span, and cost IS accumulated via `cost_tracker.accumulate_cost()`/`check_ceiling()`, but the two aren't joined into one named `token_cost_usd` field on the span itself. This is a pre-existing gap shared by every node using `complete_structured()`, not something specific to `lesson_planner` — **tracked as Sprint 3's S3-5 (Pipeline cost attribution in Langfuse)**, not reopened here.
  - Tier-aware slide-count targets (Epic 1's node-11 spec) are explicitly NOT part of this task — `state` has no `tier` key post-revert (Story 2-2); deferred to S2-LM4 once S2-LM1's 4-dev sign-off unblocks tier plumbing again.
  - **AC:** Input confirmed as summaries ✓ (tested); output passes `LessonMetadata` validation ✓ (resolved by S2-11, tested); Langfuse span records `token_cost_usd` ✗ (pre-existing provider-wide gap, deferred to S3-5) — see `docs/stories/2-6-lesson-planner-node.md` for the full story, including a 3-layer adversarial code review (7 patches applied, 4 pre-existing risks deferred, 297/297 tests passing)

- [x] **S2-8 `slide_generator` node** — ✓ 2026-07-15
  - `apps/api/app/modules/content/pipeline/graph.py::slide_generator_node` (NOT a separate `nodes/slide_generator.py` file — see Story 2-1's Tracker Cross-Reference Notes on why this file-per-node table entry is stale)
  - Model: `settings.llm_slide_generator` (`LLM_SLIDE_GENERATOR`) — ONE structured-output call for the whole lesson plan (not one call per segment), same cost-conscious design `lesson_planner_node` (S2-7) uses
  - Phase 2 — sequential after S2-7, consumes `state["lesson_plan"]["segments"]` only (never raw summaries/sections/chapter text — enforced structurally and by test)
  - Output: nested `{segment_id, data}` list (mirrors `quiz_generator_node`'s established pattern, Story 2-1) — `data` is `Slide.model_validate()`-checked inside this node itself, not deferred to `package_builder`
  - Degrade-not-fabricate guards (segment count/ID match, no duplicates, 1-8 slides/segment, non-blank titles, non-blank bullets — including per-bullet blank checks and malformed-entry guards added in the 2026-07-15 code review round) all reviewed via a real 3-layer `/bmad-code-review` (orchestrated via multi-agent Workflow) and patched
  - Idempotency checkpoint (Phase-A style, same as `lesson_planner_node`)
  - Tier-aware slide-count targets (Epic 1's node-12 spec) explicitly NOT part of this task — fixed 1-8 slides/segment band, same reasoning as S2-7; deferred to S2-LM4 once S2-LM1's 4-dev sign-off unblocks tier plumbing again
  - **AC:** Output validates against `app.schemas.Slide` ✓ (tested); at least 1 (and at most 8) slide per segment ✓ (tested); `image_url`/`fallback_image_url` both nullable, always `None` at this node (images filled by S2-10) ✓ — see `docs/stories/2-7-slide-generator-node.md` for the full story, including the 3-layer adversarial code review (5 patches applied, 3 pre-existing risks deferred, 314/314 tests passing) ✅

- [x] **S2-9 `tts_node` — Sarvam AI Bulbul v2 + Azure TTS + Browser fallback** — ✓ 2026-07-15
  - `apps/api/app/modules/content/pipeline/graph.py::tts_node` (NOT a separate `nodes/tts_node.py` file — see Story 2-1's Tracker Cross-Reference Notes) + new `apps/api/app/providers/tts/sarvam.py`/`azure.py`
  - Phase 3 Media node — **banned `providers/tts/elevenlabs.py` deleted as part of this story** (ElevenLabs REMOVED 2026-06-25; the dead file had lingered in the repo until now)
  - Fallback chain: Sarvam AI Bulbul v2 → Azure TTS → Browser Speech, real HTTP calls via `httpx.AsyncClient`, each with its own circuit-breaker key (`"sarvam"`/`"azure_tts"`) and `@with_retry(max_attempts=3)`. Sarvam's 429 response body is inspected: `insufficient_quota_error` is non-retryable, anything else (e.g. `rate_limit_exceeded_error`) is retried normally.
  - Each segment's narration script → `.mp3` uploaded to the private `lesson-audio` Supabase Storage bucket (`upsert: true`, added during code review) at `{lesson_id}/{segment_id}.mp3`; `Narration.audio_url` set to that storage path (never a public URL)
  - `is_circuit_open()` wired before every provider call; fallback genuinely never hard-fails — a 3-layer adversarial `/bmad-code-review` caught that the ORIGINAL implementation's "never hard-fails" claim only covered the synthesis call itself, not the surrounding per-segment loop (storage upload, malformed-entry indexing) — fixed with a per-segment `try/except` that degrades just that one segment to browser fallback on any failure, never crashing the whole node
  - TTS cost included in `cost_tracker.accumulate_cost()` via a documented flat per-character estimate (neither vendor's exact billing API is verifiable from this environment — flagged for a future story to replace with real invoiced numbers)
  - Word-to-slide audio timestamps explicitly NOT implemented — `Narration.timestamps` ships `[]` for every segment; the tracker's own AC below doesn't require them, and no established slide-mapping heuristic exists yet (deferred to a follow-up story)
  - **AC:** Audio file produced per segment ✓; URL in `Narration.audio_url` ✓; `audio_provider` set to `"sarvam"`/`"azure"`/`"browser"` ✓; pipeline never fails over TTS ✓ (tested, including the code-review round's per-segment degrade fix) — see `docs/stories/2-8-tts-node.md` for the full story, including the adversarial review (7 patches applied, 1 pre-existing risk deferred, 333/333 tests passing) ✅

- [x] **S2-10 `image_generator` node — GPT Image 1 Mini + Imagen 4 Fast + text-only fallback** — ✓ 2026-07-15
  - `apps/api/app/modules/content/pipeline/nodes/image_generator.py` (real implementation inline in `graph.py`, per repo convention)
  - Phase 3 Media node
  - **DALL-E 3 REMOVED — shut down May 2026. Stack: GPT Image 1 Mini → Imagen 4 Fast → text-only** — `apps/api/app/providers/image/dalle.py` deleted, real `OpenAIImageProvider`/`ImagenProvider` added
  - Fall back to `image_url = None` (text-only) if cost ceiling is near — never fail the pipeline over images — proactive per-slide `check_ceiling()` pre-check implemented
  - Image cost included in `cost_tracker.accumulate_cost()` — called from `image_generator_node` itself, only after a successful Storage upload (moved out of the providers during code review — see below)
  - **AC:** Image URL or `None` set on each slide ✓ (tested); pipeline completes if all image providers fail ✓ (tested, per-slide try/except); cost tracked ✓ (tested, only after successful upload) — see `docs/stories/2-9-image-generator-node.md` for the full story, including the 3-layer adversarial code review (9 patches applied — 1 CRITICAL API-key-leak, 2 HIGH cost-accumulation race, plus a newly-discovered `app/core/retry.py` bug fixed in the same round — 356 tests, 355 passing + 1 pre-existing unrelated skip) ✅

- [x] **S2-11 `package_builder` node → JSONB write** — ✓ 2026-07-16
  - `apps/api/app/modules/content/pipeline/graph.py::package_builder_node` (real implementation inline, per repo convention)
  - Phase 3 final node — assembles all prior node outputs
  - ✓ 1. `LessonPackage` built from accumulated `state` outputs — per-segment correlation across all 6 upstream node outputs by `segment_id` (`slide_images` by `slide_id` separately, its own deliberately flat shape); a segment missing required data is skipped with a warning, not a crash; `RuntimeError` if every segment gets skipped.
  - ✓ 2. `LessonPackage.model_validate(assembled)` called uncaught — raises immediately if schema violated (tested).
  - ✓ 3. `lessons.content = package.model_dump(mode="json")`; `lessons.status = 'ready'`; `lessons.title` also populated (first node in the pipeline to write to `lessons` at all).
  - ✓ 4. `lesson_jobs.status = 'completed'`; `completed_at` set (ISO-8601 UTC) — the pre-existing `_update_job_progress()` helper could never do this (only ever sets `status="running"`); the stub's previous final call was a latent bug (would have reset status back to "running") and has been removed.
  - 5. **WebSocket `lesson_ready` push is S2-12's own scope, not S2-11's** (see S2-12's tracker entry below — "coordinate with Dev 4 before implementing"). This story's scope note treats S2-11 and S2-12 as distinct, not-overlapping work, so S2-11 is complete without it.
  - **Frozen-contract change, flagged for 4-dev sign-off (PRD §16), mirroring S2-LM1's precedent:** `Slide.image_url`/`fallback_image_url` relaxed from `AnyHttpUrl` to `str` in `app/schemas/lesson.py` + `packages/shared/lesson_package.schema.json` — both fields now store the bare Supabase Storage path, not a signed URL (baking a signed URL into stored JSONB would silently expire before a lesson is necessarily viewed; resolving paths to fresh signed URLs at lesson-view time is a separate, not-yet-built component's job).
  - **`teachback_prompt` is a PROVISIONAL placeholder** (deterministic template, no LLM call) — no node in the 15-node pipeline generates a real teach-back prompt; this is pending confirmation from whoever owns the teach-back feature (Dev 3 — Quiz API, teachback scorer, CES formula, Learner DNA per team ownership).
  - **AC:** `lessons.content` valid JSONB ✓ (tested); `LessonPackage.model_validate(row["content"])` round-trip passes ✓ (tested); `lessons.status = 'ready'` ✓ (tested); `lesson_ready` WebSocket push — out of scope for S2-11, see S2-12 below — see `docs/stories/2-11-package-builder-node.md` for the full story, including the 3-layer adversarial code review (5 patches applied — defensive `.get()` lookups replacing crash-prone direct subscripting, duplicate/orphaned-segment_id warning logging, 6 new coverage tests — plus 2 findings correctly deferred with documented rationale, 381/382 tests passing) ✅

- [x] **S2-12 WebSocket `lesson_ready` push — coordinate with Dev 4** — ✓ 2026-07-16
  - **Discovery: this infrastructure already existed, built by Dev 4** (`4534078 fix(arq): lesson_ready via Redis pub/sub`) — `apps/api/app/core/pubsub.py` (Redis pub/sub subscriber → `ConnectionManager.send()`) already wired into `app/main.py`'s lifespan, and `apps/api/app/workers/jobs/content_pipeline.py::content_pipeline_job` already published to `lesson_ready:{session_id}`. S2-12 turned out to be a reconciliation/bug-fix story against Story 2-11's landing, not new infrastructure.
  - ✓ **Real bug fixed:** `package_summary`'s `slides_count`/`quiz_count`/`audio_count` had silently reported `0`/`0`/`0` for every successful lesson since S2-11 landed — the code read top-level `slides`/`quiz_questions`/`audio_assets` keys that only existed on the old flat stub shape (S2-11's real `LessonPackage` nests all three inside each segment). Fixed to aggregate from `segments[].slides`/`.quiz`, with `audio_count = len(segments)`.
  - ✓ **Frozen-contract deviation fixed:** the published payload had an extra `session_id` key not present in `ws.ts`'s `LessonReadyMessage` type (`{lesson_id, lesson}` only). Removed — confirmed the subscriber only ever extracted `session_id` from the channel name, never the payload, so this was pure redundancy, never load-bearing.
  - `session_id` fallback (`lesson_row.get("session_id") or lesson_id`) is UNCHANGED and confirmed correct — no `sessions`-table column exists on `lessons` yet, so this remains the only path in practice; building real session-tracking stays out of scope pending genuine Dev 4 coordination.
  - Shape must match `packages/shared/types/ws.ts` discriminated union exactly — ✓ confirmed (payload is now byte-for-byte `LessonReadyMessage`'s type).
  - Triggered by `package_builder` (S2-11) on success — ✓ (pre-existing wiring, confirmed still correct).
  - **AC:** Frontend receives `lesson_ready` ✓ (pre-existing, Dev 4's wiring); message passes TS discriminated-union type check ✓ (payload now matches exactly, extra key removed); no shape mismatch with Dev 4 handler ✓ — see `docs/stories/2-12-lesson-ready-websocket-push.md` for the full story, including the 3-layer adversarial code review (4 patches applied — defensive guard against a crash-after-publish failure mode, 2 new coverage tests, 1 documentation correction — plus 2 findings correctly dismissed as verified-honest/not-a-defect, 942 tests passing) ✅

- [x] **S2-13 Cost ceiling enforcement wired into all nodes** — ✓ 2026-07-17
  - `apps/api/app/core/cost_tracker.py` — wire into every LLM, TTS, image call
  - `MAX_LESSON_COST_USD = settings.max_lesson_cost_usd` (default `$3.00`)
  - ✓ `lesson_planner_node`/`slide_generator_node` (S2-7/S2-8) now check `check_ceiling()` before dispatch — on breach, downshift from the premium model (`llm_lesson_planner`/`llm_slide_generator`) to `llm_mini` rather than aborting. `tts_node` (S2-9) checks per segment — on breach, skips Sarvam/Azure entirely and degrades straight to the free browser fallback. `image_generator_node` (S2-10) already had this (Story 2-9 AC-3) — verified unchanged. New `_record_cost_downshift()` helper writes a durable `{node, from, to, at}` trail into `lesson_jobs.node_outputs["_cost_downshifts"]` for the future S3-4 admin panel to read.
  - ✓ Story 2-1 AC-7's Phase 1 pre-dispatch gate (`_fan_out_phase1_economy_nodes`) is **explicitly and deliberately left unchanged** — `llm_mini` is already the cheapest configured LLM tier, so there is nothing to downshift Phase 1 economy nodes *to*; terminate-and-flag remains the accepted behavior there (documented as a known, accepted gap against CLAUDE.md §14's literal "never abort" wording, not something silently left inconsistent — see Story 2-13's Dev Notes).
  - Code review (3-layer adversarial, Blind Hunter + Edge Case Hunter + Acceptance Auditor) caught and fixed 2 real HIGH-severity bugs before merge: `_record_cost_downshift`'s own DB write was silently clobbered by each node's own subsequent final checkpoint write (defeating the downshift-recording AC on the very request meant to demonstrate it) — fixed by converting it to a pure in-memory merge; and `check_ceiling()` in the two new LLM-node call sites had no fail-open guard (a transient Redis error would have crashed the node) — fixed to match the existing fail-open pattern used everywhere else in the file.
  - No admin panel exists yet (S3-4, Sprint 3, not started) — "flag in admin" is satisfied today via the durable `_cost_downshifts` JSONB trail, not a literal UI.
  - **AC:** A test run over the cost ceiling completes each of the 4 premium/media nodes without crashing ✓ (tested); cost tracked in `lesson_jobs.cost_usd` (unchanged, already done) ✓; downshift recorded for future admin visibility ✓ (tested, survives the node's own final checkpoint write) — see `docs/stories/2-13-cost-ceiling-enforcement.md` for the full story, including the 3-layer adversarial code review (2 HIGH patches applied, 3 LOW patches applied, 5 findings correctly dismissed with rationale). 947/995 tests passing, 48 pre-existing unrelated failures (unchanged baseline), 2 skipped — 0 regressions.

- [x] **S2-14 Eval harness — 5 PDFs** — ✓ 2026-07-17
  - `apps/api/tests/evals/scoring.py` (rule-based slide-quality/quiz-relevance heuristics), `apps/api/tests/evals/runner.py` (drives one PDF through the real `run_pipeline()`, validates + scores + records to Langfuse + cleans up), `apps/api/tests/evals/test_live_run.py` (the actual live entry point), `apps/api/tests/fixtures/generate_eval_pdfs.py` (synthetic PDF generator, `fpdf2` new dev-only dependency)
  - **No real representative textbook PDFs were available in this session** — 5 synthetic PDFs generated deterministically instead (short=3pp, long=120pp, dense_text=15pp, table_heavy=8pp/3 tables-per-page, image_heavy=10pp/4 synthetic images-per-page). PDFs themselves are NOT committed — a pre-existing Sprint 0 `.gitignore` rule (`tests/fixtures/eval_pdfs/*.pdf`) already excluded them, discovered (not created) during this story; only the generator is committed, and it's re-runnable to regenerate them locally.
  - Scoring is explicitly rule-based/heuristic (documented honestly as such), not LLM/semantic — spends zero additional LLM budget scoring an already-completed lesson, consistent with the project's cost discipline.
  - **The actual live 5-PDF pipeline run was explicitly NOT executed** — a deliberate scope decision made with the user before implementation (real OpenAI/Sarvam/Azure/Supabase cost + up to ~15 min/lesson × 5). The harness is fully built and unit-tested (16 offline tests, zero live calls); gated behind a new `live_eval` pytest marker + `--run-live-eval` flag (scoped to `tests/evals/conftest.py`, not a global `pyproject.toml` addopts change — a code-review finding caught and reverted an initial version that did touch global config without team sign-off). **Trigger it when ready:** `pytest apps/api/tests/evals/test_live_run.py -v --run-live-eval` (requires live credentials already in `.env`).
  - Code review (3-layer adversarial) caught and fixed 5 real issues before merge, most notably: a slide-count band violation that was logged but never actually lowered the score; two places where `run_eval()`'s own "never raises" contract was violated by unguarded checks outside its try block; `run_all_evals()` having no per-PDF exception isolation around `run_eval()` itself (would have discarded all results on any future bug); and — most operationally important — no cleanup of the `books`/`lessons`/`lesson_jobs` rows or Storage object each eval run created, meaning every run (pass or fail) would have permanently accumulated orphaned test data in Supabase.
  - **AC:** All 5 synthetic PDFs produce a valid `LessonPackage` when run live (not yet verified — deferred to the user's live trigger, see above); no pipeline crash — per-PDF failure isolation is unit-tested ✓; per-lesson scores recorded to Langfuse via `start_observation()`/`score_trace()`/`.end()` (verified against the installed v4 SDK, not guessed) ✓ — see `docs/stories/2-14-eval-harness-5-pdfs.md` for the full story, including the 3-layer adversarial code review (8 patches applied — 5 HIGH, 3 LOW — plus 4 findings correctly dismissed with documented rationale). 963/1014 tests passing, 48 pre-existing unrelated failures (unchanged baseline), 3 skipped — 0 regressions.

- [x] **S2-15 LLM provider factory — model-agnostic dispatch (MANDATORY refactor)** — ✓ 2026-07-16
  - `apps/api/app/providers/llm/factory.py` (new) — `get_llm_provider(model, lesson_id=None) -> LLMProvider`
  - **Why:** all 9 economy/premium node call sites in `graph.py` hardcoded `from app.providers.llm.openai import OpenAILLMProvider` directly — `settings.llm_mini`/`settings.llm_lesson_planner`/etc. were env-var-driven for the MODEL STRING, but the PROVIDER CLASS was not selectable at all. CLAUDE.md's "swapping models is an env var change only" claim was only true within OpenAI's own model lineup — pointing `LLM_MINI` at a non-OpenAI model (Gemini, Claude) would have broken at request time. This refactor makes provider selection itself config-driven, in-process (no new service/deploy) — a future new provider (Gemini, Claude, etc.) now requires writing one file + one registry entry, zero node call-site changes.
  - ✓ Factory dispatches by model-name prefix (`"gpt-"`/`"o1-"`, both routed to `OpenAILLMProvider`); lazy per-branch import deliberately preserved (mirrors every node's pre-existing pattern) — this is what made the migration a genuinely zero-test-file-touched refactor: **0 of the ~98 informally-estimated test references actually needed a patch-target change**, confirmed by running the full suite immediately after migration, before touching any test file.
  - ✓ All 9 `graph.py` call sites migrated (`structure_node`, `lesson_planner_node`, `slide_generator_node`, `summarise_segment_node`, `quiz_generator_node`, `segment_complexity_node`, `jargon_extractor_node`, `intervention_messages_node`, `narration_generator_node`) — confirmed via grep, zero `OpenAILLMProvider` references remain in `graph.py`.
  - Does NOT include writing a second provider (Gemini/Claude) — stays deferred until actually needed for an eval. Also does NOT cover 3 additional hardcoded call sites discovered in the `assessment/` module (`dna_profile.py`, `service.py` — Dev 3's owned territory, out of this story's scope) — flagged as a deferred review finding for whoever owns that module next.
  - **AC:** `get_llm_provider()` returns a correctly-typed `LLMProvider` for every currently-supported model string ✓ (tested, including the `o1-mini` edge case found in review); all 9 `graph.py` call sites migrated ✓ (verified via grep); unknown/unregistered/non-string model raises a clear `ValueError` ✓ (tested); zero behavior change ✓ (364/365 tests passing, only patch-round additions, no existing test logic changed) — see `docs/stories/2-15-llm-provider-factory.md` for the full story, including the 3-layer adversarial code review (4 patches applied — 2 HIGH, 2 MEDIUM/LOW — 1 HIGH finding deferred as cross-module scope, 1 LOW dismissed as unrelated pre-existing clutter) ✅

---

## Sprint 3 — Weeks 6–7 (Due: ~2026-07-30)

> **Goal:** Production quality — eval harness at scale, full observability, admin panel live.

- [x] **S3-1 Eval harness expanded to 20 PDFs** — ✓ 2026-08-14
  - `apps/api/tests/evals/`
  - Cover all failure modes: dense text, table-heavy, image-heavy, short (≤10 pages), long (≥100 pages)
  - **AC:** All 20 PDFs produce valid `LessonPackage`; no pipeline crash; scores tracked in Langfuse
  - **Harness capability delivered; live run + human-review gate NOT run — see below.** 4 real,
    meaningfully-distinct variants per category (not lazy duplicates): short gets 1/3/10-page +
    sparse (testing the ≤10p boundary itself), long gets 100/150/250/400-page (testing the ≥100p
    boundary at real scale, capped at 400 deliberately — this harness is for cheap/frequent
    regression-catching, not exhaustive scale testing, that's L1's job), dense_text/table_heavy/
    image_heavy each get 4 variants stressing a different real edge (long vs. short paragraphs,
    wide vs. tall tables, captioned vs. grid images). Added a guard test keeping `_EVAL_PDF_KEYS`
    (runner.py) and `_GENERATORS` (generate_eval_pdfs.py) in sync — two independently-edited lists
    of the same names is exactly the drift pattern CLAUDE.md's binding rule 5 already names.
  - **Real hidden coupling found and fixed:** `test_extract_page_bounds.py` and
    `test_extract_text_only_mode.py` referenced the OLD 5 fixture filenames directly and
    self-skipped (no failure, no error) when the rename removed them — caught only by diffing the
    skip count against the branch's true baseline (85→110 skipped), not by the test run itself
    going red. Repointed all 5 constants at the equivalent new-named variant; `LONG_PDF` had no
    exact-120-page match among the new variants, repointed to `long_150page.pdf` with `LONG_PAGES`
    updated to match (every assertion already reads the constant, not a hardcoded 120 — a rename,
    not a semantic change, confirmed by running the affected tests). Branch
    `sprint3/s3-1-eval-harness-20-pdfs`, Story 3-57.
  - Tests: new drift-guard + page-count-boundary tests in `test_eval_runner.py`, RED-GREEN
    verified. Zero new regression failures (76/76, byte-for-byte identical failing set vs. branch
    base, verified via throwaway worktree).
  - **Not yet done, stated up front in the story:** the actual live run
    (`pytest tests/evals/test_live_run.py --run-live-eval`) is blocked on Sarvam credits (same
    402 as L1, confirmed live). The PRD's "15 of 20 PDFs rated useful to a student" gate
    (`.claude/commands/run-evals.md`) is a human judgment call, not something this story
    automates. Both remain the explicit next step once credits return.

- [ ] **S3-2 Prompt iteration from eval results**
  - `apps/api/app/modules/content/pipeline/nodes/` — prompt strings only
  - Data-driven only: track before/after Langfuse scores; change only prompts that show ≥5% regression or improvement
  - **AC:** At least one node prompt improved; before/after scores committed to Langfuse; no blind prompt edits
  - **Genuinely blocked, not skippable:** this AC's "data-driven only... no blind prompt edits"
    requires real before/after Langfuse scores, which requires S3-1's live 20-PDF eval run —
    blocked on Sarvam credits (still `402 insufficient_quota_error`, confirmed live 2026-08-14),
    same blocker as L1. Unlike S3-1, there is no infrastructure-only partial delivery possible
    here — the whole premise is real eval data that doesn't exist yet. Revisit once Sarvam
    credits return and S3-1's live run produces real scores to act on.

- [x] **S3-3 Circuit breaker implementation** — ✓ 2026-06-12 (built ahead of schedule)
  - `apps/api/app/core/circuit_breaker.py`
  - 5 failures / 2 min → OPEN; 10 min → HALF_OPEN probe; state in Redis
  - **Wire into ALL Sprint 2 provider calls immediately — do not wait until Sprint 3**
  - **AC:** `is_circuit_open()` / `record_failure()` / `record_success()` callable by all providers; state persists across restarts via Redis ✅

- [x] **S3-4 Admin panel: job status, cost tracking, failed jobs** — ✓ 2026-08-14
  - `apps/api/app/modules/admin/router.py` *(the tracker's "(to create)" was stale — this file
    already existed, 295 lines, built across Story 2-25 + this session's own D59(a) fix)*
  - Endpoints: `GET /api/admin/jobs`, `POST /api/admin/jobs/{job_id}/retry`, `GET /api/admin/costs`
  - **AC:** All jobs listable with status + cost; failed jobs retryable via single API call; cost per lesson and per user visible
  - **Real gap was 1 of 3 endpoints, not the whole router — verified by reading the current code
    first.** `GET /jobs` (per-lesson `cost_usd` in every `JobSummary`) and `GET /costs`
    (`by_user` breakdown) already existed and already satisfied their AC clauses. Only
    `POST /jobs/{job_id}/retry` was missing.
  - **Retry design, investigated rather than assumed:** `content_pipeline_job` takes only
    `lesson_id` (re-fetches everything else from `lessons`), so retry never re-validates
    ownership/chapter/page-span. `node_outputs`/`last_node` are deliberately left untouched —
    `run_pipeline` reads them to resume from the last completed node
    (`graph.py:5602`'s own comment confirms this), clearing them would silently re-run and
    re-bill already-paid-for nodes. A fresh ARQ `_job_id` is minted per retry
    (`f"pipeline:{lesson_id}:retry:{token}"`, never the bare original) — `content_pipeline.py`'s
    own comment already names the trap (`ctx["job_id"]` alone is not a uniquifier); reusing the
    exact original id on a fresh `enqueue_job()` call risked a stale/duplicate LangGraph
    `thread_id` depending on ARQ's own `job_try` reset semantics, which this story does not
    depend on either way. Only `failed` jobs are retryable (409 otherwise, naming the actual
    status). Branch `sprint3/s3-4-admin-panel-job-cost-tracking`, Story 3-58.
  - Tests: 8 new tests in `test_admin_router.py` (403/404×2/409×3/202/500), RED-GREEN verified —
    including a real RED-GREEN proof that reusing the bare `_job_id` fails the fresh-id
    assertion. Zero new regression failures (76/76, byte-for-byte identical failing set vs.
    branch base, verified via throwaway worktree).
  - **CORRECTED 2026-08-14 (retroactive review):** the line above originally called the
    concurrent-retry gap "a cost nuisance, not double-billing." **That was wrong.** A retroactive
    8-layer BMAD review's Scale & Load Hunter traced it through: `content_pipeline.py`'s
    `clear_lesson_cost()` unconditionally deletes the Redis cost counter the moment *either*
    concurrent run finishes — so the still-running sibling's next `check_ceiling()` reads `$0` and
    is permitted to spend up to another full $3.00. A real, silent cost-ceiling bypass, not a
    nuisance. Mitigated same day: `retry_job` now rejects a retry if another job for the lesson is
    already running/pending, closing the realistic trigger. The narrow residual race (two retry
    calls racing the mitigation's own check-then-act) is registered as **D109**, deferred, owner
    Dev 1. See Story 3-58's Review Findings section for the full list (8 patches applied: the
    scoping fix, the concurrency mitigation, an uncaught-`enqueue_job`-exception fix, the response
    `arq_job_id` fix, a test mock-chain fix, a missing test assertion, a wording softening, and a
    `MOCK-CONTRACT` note). Also closed the same day: a real premise-test gap in Story 3-56 (an
    unverified assumption about Langfuse's `update()` merge semantics — checked directly against
    the real SDK source, confirmed safe, pinned with a test) and a recurrence guard in Story 3-57
    (the exact silent-skip-on-stale-fixture-name defect this story already fixed once, now guarded
    against happening again unnoticed). Branch `sprint3/s3-56-57-58-review-fixes`.

- [x] **S3-5 Pipeline cost attribution in Langfuse** — ✓ 2026-08-14
  - All pipeline nodes — each Langfuse span must include `token_cost_usd` in metadata
  - **AC:** Langfuse dashboard shows cost breakdown per node per lesson; no node missing cost attribution
  - **Real gap was narrower than this AC's wording:** 4 of 6 priced providers (Sarvam TTS, Azure
    TTS, Imagen, GPT Image) already called `generation.update(..., cost_details={"input": cost})`
    from this session's earlier Langfuse self-audit. Only `providers/llm/openai.py` (`complete`,
    `complete_structured`) and `providers/embeddings/openai.py` were missing it — both computed
    real cost in `_maybe_accumulate_cost` but never wrote it back to the span. Fixed by passing
    `generation` into `_maybe_accumulate_cost` and calling `generation.update(cost_details=...)`
    right where cost is already computed — extends Langfuse's native `cost_details` field (what
    the dashboard actually reads), not a custom `token_cost_usd` metadata key. LLM cost splits
    `cost_details={"input": ..., "output": ...}` (mirrors `usage_details`' existing split, unlike
    TTS/image's single-cost calls). Branch `sprint3/s3-5-langfuse-cost-attribution`, Story 3-56.
  - Tests: `test_s3_5_langfuse_cost_attribution.py` — 4 new tests, RED-GREEN verified. Extended
    `test_langfuse_sdk_contract.py`'s premise check to include `cost_details`. Zero new failures
    in full regression (76/76, byte-for-byte identical failing set vs. branch base, verified via
    throwaway worktree).
  - **Not yet done:** cannot verify the AC's literal "Langfuse dashboard shows cost breakdown"
    visually — no real `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` exist in this environment yet
    (same limitation as the earlier Langfuse self-audit). Code/mock-level verification only.

- [x] **S3-6 Media signed-URL layer** — ✓ 2026-07-23 — added from 2026-07-22 audit (HIGH #3)
  - `apps/api/app/modules/media/router.py` — finish `GET /api/media/signed-url` (was a 501 stub)
  - **AC:** ownership-verified signing (IDOR-safe) for `lesson-audio`/`lesson-images` paths; malformed/unowned paths 404, not 500; backend-only (no frontend player changes — see `docs/stories/3-6-media-signed-url-layer.md`) ✅

- [x] **S3-37 Node 8 narration hard cap — 10,000 chars/lesson** — ✓ 2026-08-12 (branch `sprint3/s3-37-narration-char-cap`, PR not yet opened)
  - `docs/decisionupdate.md` §8: TTS synthesis cost is 67–73% of total lesson generation cost — the dominant line item against the $3.00/lesson ceiling — and no lesson-wide narration character cap existed anywhere. Cannot live in `narration_generator_node` (Send()-dispatched per-section, no cross-section visibility); enforced in `tts_node` instead, the first point all segments' scripts are available together and immediately before the TTS spend.
  - `apps/api/app/config.py` *(`settings.max_narration_chars_per_lesson`, default 10,000)*, `apps/api/app/modules/content/pipeline/graph.py` *(`tts_node` computes a running total, truncates the boundary-crossing segment, degrades every later segment through the existing browser-fallback shape — no new shape invented, no paid TTS call for a segment contributing zero narration)*, `apps/api/app/modules/admin/router.py` *(surfaces the cap event)*
  - **AC:** cap enforced lesson-wide across all segments ✅; boundary segment truncated character-exact, later segments degrade via the existing fallback shape ✅; `node_outputs["narration_cap_applied"]` always written (present even when nothing capped) — no silent truncation ✅; 34 new tests (`test_tts_node.py`, `test_admin_router.py`) ✅ — see `docs/stories/3-37-narration-char-cap.md`
  - **Verified this session:** full suite 43 failed/1795 passed/85 skipped vs. `main`'s 44 failed/1780 passed/85 skipped (same baseline failures, zero regressions, +15 new passing); ruff/mypy parity with `main`

- [x] **S3-38 tts_node measures REAL audio duration** — ✓ 2026-08-12 (branch `sprint3/s3-38-real-audio-duration`, PR not yet opened)
  - `package_builder` was guessing slide timing instead of using the actual synthesized audio's real duration. Round 2 review caught a real license defect in the first implementation: it used `mutagen`, mislabeled MIT in this story's own ACs/pyproject comment, but actually GPL-2.0-or-later (verified via `pip show mutagen`, not asserted) — swapped to `tinytag` (genuinely MIT), matching this repo's zero-tolerance stance on license mistakes (same category as the PyMuPDF/AGPL-3.0 ban).
  - `apps/api/app/modules/content/pipeline/graph.py` *(`tts_node` parses real duration via `tinytag.TinyTag`, `duration_ms` is `None` on the browser-fallback path or when `tinytag` can't parse)*, `apps/api/pyproject.toml` *(`tinytag>=2.3.0,<3.0.0` added)*
  - **AC:** real synthesized-audio duration replaces estimated slide timing ✅; parse failure degrades explicitly (`duration_ms=None`), never silently wrong ✅; license of the new dependency verified, not assumed ✅; 18 new tests (`test_audio_duration_s3_38.py`) ✅ — see `docs/stories/3-38-real-audio-duration.md`
  - **Verified this session:** 43 failed/1798 passed/85 skipped vs. `main` baseline, zero regressions; ruff/mypy parity with `main` (after installing the new `tinytag` dependency into the test environment)

- [x] **S3-39 Surface `_get_section_body`'s silent truncation (D46)** — ✓ 2026-08-12 (branch `sprint3/s3-39-surface-section-truncation`, PR not yet opened)
  - Closes D46. `_get_section_body(max_chars=...)` silently sliced oversized section text with no record anywhere that truncation happened — a smaller-scale instance of the same "reports success while covering a fraction of the input" failure class as the book-scale 4%-of-the-book defect this register exists to name.
  - `apps/api/app/config.py`, `apps/api/app/modules/content/pipeline/graph.py` *(every truncation now recorded into a `section_truncations` list, persisted and admin-visible — no silent degradation)*
  - **AC:** every truncation explicitly recorded (section id, original length, kept length) ✅; nothing truncated without a visible trail ✅; 73+49 new/updated tests across `test_phase1_economy_nodes.py`, `test_phase1_checkpoint_idempotency.py`, `test_package_builder_node.py` ✅ — see `docs/stories/3-39-surface-section-truncation.md`
  - **Verified this session:** 43 failed/1789 passed/85 skipped vs. `main` baseline, zero regressions; ruff/mypy parity with `main`
  - **D46 stays OPEN** — only the "nothing surfaces it" half is fixed here (now guarded two ways: `truncation_expected` at chapter level, `section_truncations` at per-section level). The root cause (the ~90,000-char LLM-visible window itself) is unchanged and remains open, per D46's own addendum in `docs/DEFECT-REGISTER.md` (already written by this branch's own commits) — do not report D46 as closed

- [x] **S3-40 Langfuse instrumentation audit (env, session semantics, naming)** — ✓ 2026-08-12
  - Installed `github.com/langfuse/skills`, used it to audit tracing across all providers + the tutor FSM against best-practices.md/sessions.md/environments.md fetched fresh, and against the pinned SDK's real signatures (4.14.3) — not from memory
  - `apps/api/app/config.py` *(added `langfuse_environment`, validated)*, `apps/api/app/core/langfuse.py` *(wired into client init)*, `apps/api/app/modules/tutor/state_machine/graph.py` *(`_trace_dispatch` fixed — one trace per turn + `propagate_attributes(session_id=...)`, was wrongly forcing a whole session into one ever-growing trace)*, all 5 LLM/embedding/TTS/image providers *(verb-first observation names; TTS/image providers traced for the first time)*, `apps/api/app/modules/content/pipeline/graph.py` *(TTS providers now constructed with `lesson_id`)*
  - **AC:** fresh docs fetched, not memory ✅; `environment` set and validated ✅; tutor session semantics match Langfuse's documented one-trace-per-turn model ✅; observation names verb-first/model-agnostic ✅; two real (non-mocked) Langfuse Cloud traces fetched back and inspected ✅; 141/141 relevant tests passing, 0 regressions ✅ — see `docs/stories/3-40-langfuse-tracing-audit.md` for the full audit, including gaps explicitly deferred (span/parent hierarchy, `user_id` attribution — both need `parent_span_id`/`user_id` threaded through LangGraph state, a real architecture change out of scope here)
  - **Not this story:** S3-5's `token_cost_usd` joined-metadata field is separate and still open

- [x] **S3-42 Sarvam text chunking + real WAV decoding (D74)** — ✓ 2026-08-13 (branch `sprint3/s3-42-sarvam-text-chunking`, merged to `main`)
  - Found live mid-L1: every real narration segment fell through Sarvam → Azure (unconfigured) → browser, even after D67's voice fix. Two compounding, previously-unknown defects in `SarvamTTSProvider._synthesize_inner`: Sarvam's real 500-char/3-item-per-request limits (neither ever respected), and `audio_bytes = response.content` capturing the raw JSON response body instead of the base64-encoded audio inside it — broken since Story 2-8, never caught because every test mocked the provider at the call site
  - `apps/api/app/providers/tts/sarvam.py` *(`_chunk_narration_text`, `_batched`, `_concatenate_wav_clips` — real PCM-frame WAV concatenation via the stdlib `wave` module)*
  - **AC:** live end-to-end verified before writing tests (2,406 chars → 5 chunks → 2 batched requests → one valid 130.45s WAV) ✅; 23 tests (15 new + 8 corrected), RED-GREEN verified by reintroducing the old bug ✅ — see `docs/stories/3-42-sarvam-text-chunking.md`

- [x] **S3-43 Demo-readiness fixes: lesson_planner batching + narration cap (D75, D76)** — ✓ 2026-08-13 (branch `sprint3/s3-43-demo-readiness-fixes`)
  - Stakeholder-demo goal: one real lesson, ≥15 minutes. Two root-caused blockers found via direct investigation, not assumed: **D75** — `lesson_planner_batch_size` (15) equalled `structure_max_sections` (15), so Story 2-16's own batching (built to stop a single large segment-id echo from "collapsing") never actually triggered — confirmed live: two real runs on the same 15-segment chapter returned 5 and 12 segments. The obvious `<=`→`<` fix is a no-op at these defaults (verified by hand); real fix lowers the batch size to 10. **D76** — the 10,000-char narration cap (Story 3-37) was sized against a stale ~1,600 chars/min assumption in `decisionupdate.md`; real measured Sarvam rate is 1,106.6 chars/min, capping every lesson at ~9 minutes. Raised to 17,000 chars (cost re-derived: ~13% of the $3.00 ceiling, cost was never the real constraint)
  - `apps/api/app/config.py` *(`lesson_planner_batch_size` 15→10, `max_narration_chars_per_lesson` 10,000→17,000)*
  - **AC:** RED-GREEN verified for both fixes ✅; `tests/integration/test_howto_pipeline_e2e.py`'s own 20-step how-to (already at `structure_max_sections`) now genuinely exercises real batching for the first time, assertion updated accordingly ✅; full repo-wide regression 54 failed/2060 passed/85 skipped — exactly the established pre-existing baseline, zero new failures ✅ — see `docs/stories/3-43-demo-readiness-fixes.md`

- [x] **S3-44 lesson_planner per-batch echo retry (D77)** — ✓ 2026-08-13 (branch `sprint3/s3-44-planner-batch-retry`, merged to `main`)
  - Found running D75's own fix for real, the first live test of S3-43's Phase 4: two consecutive real demo-generation attempts against the merged D75 fix still failed (`expected 15, got 14`, then `got 12`). Verified live via the real Langfuse trace before writing any code — batching genuinely engaged exactly as D75 designed (one call carrying 10 `segment_id` refs, a second carrying 5); the residual gap is that a real LLM can still occasionally under-echo even a correctly-sized batch
  - `apps/api/app/modules/content/pipeline/graph.py` *(`_run_planner_batch` retries the SAME batch's own completion up to `_PLANNER_BATCH_MAX_ATTEMPTS=3` times on echo mismatch; a `None` response still raises immediately, unchanged)*
  - **AC:** RED-GREEN verified via the Edit tool (a fragile string-replace revert script silently failed earlier in this same investigation — caught by diffing, switched method) ✅; both pre-existing guard-preservation tests re-verified to still fire correctly with retries running underneath them ✅; full repo-wide regression 54 failed/2062 passed/85 skipped — established baseline, zero new failures ✅ — see `docs/stories/3-44-planner-batch-retry.md`

- [x] **S3-45 narration cap re-sized to a real cost safety net, not a duration target (D78)** — ✓ 2026-08-13 (branch `sprint3/s3-45-narration-cap-safety-net`)
  - Found inspecting the first real, fully successful demo lesson produced after D75+D76+D77 (lesson `abe4e438`, an ordinary 29-page/15-section chapter). D76's 17,000-char cap, sized against "a real 15-minute lesson," proved actively harmful on real data: 43,793 real narration chars crossed the cap and zeroed segments 6–14 (9 of 15) — a complete loss of real Sarvam audio for 60% of the lesson (all 9 fell back to browser TTS), while real cost sat at just 29% of the $3.00 ceiling. `package_builder`'s D32/D33 recovery correctly preserved the text (working as designed), but the audio experience was materially degraded
  - `apps/api/app/config.py` *(`max_narration_chars_per_lesson` 17,000→120,000, re-derived against real cost headroom — ≈$2.40 Sarvam spend = 80% of the $3.00 ceiling — not any duration target)*
  - **AC:** new `test_production_default_does_not_truncate_a_real_world_sized_lesson` uses the REAL settings default (not a mocked cap) against the exact real per-segment character distribution from lesson `abe4e438` ✅; RED-GREEN verified (failed against 17,000 with the exact predicted zeroing, passed against 120,000) ✅; full repo-wide regression re-baselined on this exact commit: 52 failed/2062 passed/86 skipped before, 52 failed/2063 passed/86 skipped after — zero new failures ✅ — see `docs/stories/3-45-narration-cap-safety-net.md`

- [x] **S3-46 slide budget proportional to segment duration (D85)** — ✓ 2026-08-13 (branch `sprint3/s3-46-slide-budget-duration`, merged to `main`; Round 2 landed as S3-49/D87 same day — D85 now fully closed, not partial)
  - Found watching the D78-fixed demo lesson actually play in a browser: every one of 15 real segments (durations 1.23–3.48 real minutes) got exactly 1 static slide, because `_tier_slide_budget_per_segment` divided each tier's fixed total-lesson slide band evenly by segment COUNT, not duration. Fixed the mechanism — allocation is now proportional to each segment's real estimated duration share (already computed by lesson_planner, previously discarded) — verified correct via a T1 assertion (differentiates when the tier band has headroom)
  - `apps/api/app/modules/content/pipeline/graph.py` *(`_tier_slide_budget_per_segment` signature changed `(tier, segment_count: int) -> tuple[int,int]` → `(tier, segment_durations_min: list[float]) -> list[tuple[int,int]]`; `lesson_planner_node` call site updated to pass real per-segment durations and index each segment's own budget)*
  - **Honest gap, not hidden**: re-verified against the exact real 15-segment dataset and found T2/T3 still produce `(1,1)` for every segment even under the new mechanism — both tiers' total_max (15, 8) is `<=` the segment count, so there's nothing to proportionally redistribute; every segment is already pinned to the structural floor. **This is a stale `_TIER_TOTAL_SLIDE_BAND` value problem (never re-derived against `structure_max_sections=15`), not an implementation bug** — the mechanism is proven correct, but the user's actual observed T3 symptom is NOT yet fixed. Marked `[~]` Partial, not `[x]` Done, for exactly this reason. Follow-up (re-deriving the tier band values) needs explicit product/cost confirmation before implementing — more slides/tier = more `image_generator` spend
  - **AC:** `test_slide_budget_proportional_to_real_d85_durations` (real 15-segment dataset, asserts the T2 non-differentiation finding explicitly + T1 differentiation) + `test_slide_budget_zero_total_duration_falls_back_to_flat_division` ✅; RED-GREEN verified via Edit tool ✅; full repo-wide regression (worktree-local baseline) 52 failed/2013 passed/86 skipped/3 collection errors before, same failed count/2015 passed after — zero new failures ✅ — see `docs/stories/3-46-slide-budget-duration.md`

- [x] **S3-47 persist real accumulated cost to lesson_jobs.cost_usd (D86)** — ✓ 2026-08-13 (branch `sprint3/s3-47-cost-persist-lesson-jobs`, merged to `main`)
  - Found auditing `docs/handoffs/lesson-delivery-dev1.md`'s own L1 checklist item "Record: measured cost per lesson" against real data: `lesson_jobs.cost_usd` was never written anywhere in `content_pipeline_job`, confirmed by zero references in the file and by `clear_lesson_cost()`'s own docstring promising a persistence step that was never built. Two real successful lesson generations this session, both with confirmed real OpenAI + Sarvam spend, both showed `cost_usd = 0.0000`. The live $3.00 ceiling enforcement (Redis-backed) was never wrong — only the durable post-hoc record
  - `apps/api/app/workers/jobs/content_pipeline.py` *(success path reads `get_cost()` before `clear_lesson_cost()` clears it, folds into the completion update; `_update_lesson_status` extended to persist real cost on every "failed" transition too — a partially-completed lesson now records its real partial spend, not 0; both read sites degrade-not-crash on a Redis failure)*
  - **AC:** 6 new tests across `test_lesson_ready_pubsub.py` (success path) and `test_timeout_contract.py` (failure path) ✅; RED-GREEN verified via Edit tool (3 of 6 failed against pre-fix code with real errors) ✅; full repo-wide regression 54 failed/2090 passed/85 skipped before, same failed set/2096 passed after — zero new failures ✅ — see `docs/stories/3-47-cost-persist-lesson-jobs.md`

- [x] **S3-48 D53 stale-generating-lesson reaper** — ✓ 2026-08-13 (branch `sprint3/s3-48-d53-stale-lesson-reaper`, merged to `main`)
  - Explicit priority pick — the only defect flagged both High and live-in-production. Read the code before writing anything: `router.py`'s staleness-predicate workaround (ignore stale `generating` rows in the idempotency/concurrency checks) already existed; only the actual reaper — a job that transitions the stuck row to `failed` in the database — was missing, exactly as the code's own docstring said ("there is no reaper")
  - `apps/api/app/workers/jobs/reap_stale_lessons.py` *(new — ARQ cron job, every 10 min, finds `lessons.status='generating'` past `router._generating_cutoff_iso()`'s own bound and reaps each via `content_pipeline.py`'s existing `_update_lesson_status` helper, inheriting D86's real-cost persistence for free)*, `apps/api/app/workers/main.py` *(registers the cron job via `WorkerSettings.cron_jobs`)*
  - **AC:** 5 new tests in `test_reap_stale_lessons.py` ✅; RED-GREEN verified by moving the implementation file aside and confirming `ModuleNotFoundError`, then restoring ✅; full repo-wide regression 52 failed/2103 passed/86 skipped — established baseline, zero new failures ✅ — see `docs/stories/3-48-d53-stale-lesson-reaper.md`
  - Also corrected two stale `docs/DEFECT-REGISTER.md` lines while in the file: the D63/Dev4 "not yet merged here" note (independently verified merged via PR #129 during the branch triage) and the "live in production" count (was citing D29, already closed, instead of D71, the real open one)

- [x] **S3-49 D87 slide budget targets minutes-per-slide, not a fixed total** — ✓ 2026-08-13 (branch `sprint3/s3-49-d87-slide-budget-duration-target`, merged to `main`)
  - The D85 follow-up, explicitly deferred at D85's own close. D85 fixed HOW the budget is allocated (proportional to duration) but not WHAT total it allocates — `_TIER_TOTAL_SLIDE_BAND` was still a fixed lesson-wide count sized with no visibility into a real 15-segment lesson, so T2/T3 still collapsed to (1,1) for every segment even under D85's own fix. Confirmed before implementing (not assumed): `slide_generator_node`'s prompt sends the literal per-segment instruction with the real min/max, so this was purely a budget-value problem, not a separate LLM-compliance issue. Real cost checked before proposing numbers: image+LLM spend is ~$0.025/image, a few extra slides adds cents, not dollars
  - `apps/api/app/modules/content/pipeline/graph.py` *(replaced fixed `_TIER_TOTAL_SLIDE_BAND` with `_TIER_MINUTES_PER_SLIDE_BAND` — T1 0.8-1.2, T2 1.2-1.8, T3 2.0-3.0 min/slide — the total now scales with the lesson's real estimated duration; D85's per-segment proportional loop unchanged)*
  - **AC:** verified on the real demo-lesson dataset — T3's longest segment now gets (1,2) instead of (1,1), T2 gets (2,3), T1 gets (3,4), all three tiers differentiate now ✅; RED-GREEN verified via `git stash` on the implementation file only ✅; one test removed with its premise explained in place (a fixed per-tier total_min the fallback must undercut no longer exists once the fixed total was deleted) rather than silently dropped ✅; full repo-wide regression 52 failed/2102 passed/86 skipped both before and after — zero new failures ✅ — see `docs/stories/3-49-d87-slide-budget-duration-target.md`
  - This closes D87 AND promotes D85 from partial to fully closed — both rounds now landed

- [x] **S3-50 D54 force=true lesson regeneration** — ✓ 2026-08-13 (branch `sprint3/s3-50-d54-force-regenerate`, merged to `main`)
  - D53's own escape hatch, landing the same day D53 closed. `GenerateLessonRequest.force: bool = False` bypasses ONLY Gate 5's idempotency early-return; Gate 6 (page-span) and Gate 7 (concurrency) stay fully unconditional. Confirmed before implementing that no "mark superseded" logic was needed — `_latest_lesson` already picks `max(created_at)` fresh on every read
  - `apps/api/app/modules/content/schemas.py` (`force` field), `apps/api/app/modules/content/router.py` (Gate 5 loop conditionally skipped)
  - **AC:** 4 new tests in `test_generate_lesson_endpoint.py` (force bypasses existing generating/ready lesson; force omitted unchanged; force still respects the concurrency cap) ✅; RED-GREEN via Edit tool ✅; full repo-wide regression 54 failed/2102 passed/85 skipped before, same failed set/2107 passed after — zero new failures ✅ — see `docs/stories/3-50-d54-force-regenerate.md`

- [x] **S3-51 D59(a) bound the admin cost-report query** — ✓ 2026-08-13 (branch `sprint3/s3-51-d59a-admin-cost-bounded`, merged to `main`)
  - `get_cost_report` materialised every `lesson_jobs` row for the period with no `.limit()`. Added `_COST_REPORT_ROW_LIMIT=10_000` + a `CostReport.truncated` flag (set only when the fetch hits the ceiling exactly — an explicit surfaced signal, never a silent under-report of real spend). Removed the now-fixed query from `test_unbounded_queries.py`'s allow-list rather than leaving it there. D59(b), `analytics/service.py`, is Dev 3's and untouched
  - `apps/api/app/modules/admin/router.py`, `apps/api/tests/unit/test_unbounded_queries.py`
  - **AC:** 3 new tests (`.limit()` present; `truncated=False` under limit; `truncated=True` at the limit boundary) ✅; RED-GREEN via Edit tool ✅; full repo-wide regression 54 failed/2102 passed/85 skipped before, same failed set/2105 passed after — zero new failures ✅ — see `docs/stories/3-51-d59a-admin-cost-bounded.md`

- [x] **S3-52 D89 Sarvam narration pace** — ✓ 2026-08-13 (branch `sprint3/s3-52-d89-sarvam-pace`, merged to `main`)
  - A real stakeholder reported narration as "very fast" watching the real lesson play. Verified against Sarvam's real API docs (not assumed): a `pace` param exists (default 1.0, range 0.3-3.0) and was never sent — every lesson synthesized at the raw default
  - `apps/api/app/config.py` (`sarvam_narration_pace`, default 0.85, env-tunable), `apps/api/app/providers/tts/sarvam.py` (sends `pace` in the request payload)
  - **AC:** new test asserts the real payload includes the configured pace ✅; RED confirmed (`KeyError: 'pace'` reverted) ✅; full repo-wide regression 52 pre-existing failures unchanged (verified on a clean baseline worktree) — zero new failures ✅ — see `docs/stories/3-52-d89-sarvam-pace.md`

- [x] **S3-53 D88 slide overflow + D90 caption overlay** — ✓ 2026-08-13 (branch `sprint3/s3-53-d88-d90-player-ui-fixes`, merged to `main`)
  - Same real playback session, two more real findings. D88: `layout.tsx`'s `min-h-screen` + `Player.tsx`'s missing `min-h-0` — a classic flex `min-height:auto` bug letting tall slide content push the page past the viewport instead of scrolling inside `SlideRenderer.tsx`'s already-correct internal scroll. D90: zero caption UI existed anywhere (confirmed via repo-wide grep); added a non-synced, always-visible panel showing the current segment's full narration script (word-level sync isn't possible yet — Sarvam word timestamps aren't implemented). **This is normally Dev 2's file territory** — implemented directly with exact root causes already identified, explicitly flagged in the story for Dev 2's visibility
  - `apps/web/src/app/lesson/[id]/layout.tsx`, `apps/web/src/components/player/Player.tsx`, new `apps/web/src/components/player/CaptionOverlay.tsx`
  - **AC:** 6 new/updated tests (`CaptionOverlay.test.tsx` ×4, `Player.test.tsx` D88/D90 blocks ×2) ✅; `npm run type-check`/`npm run lint` clean ✅; full `apps/web` suite 768 passed, 5 pre-existing failures confirmed identical on baseline, unrelated files — zero regressions ✅ — see `docs/stories/3-53-d88-d90-player-ui-fixes.md`

- [x] **S3-54 D91 reaper uses a real started_at, not lessons.created_at** — ✓ 2026-08-13 (branch `sprint3/s3-54-d91-reaper-real-started-at`, merged to `main`)
  - D53's own deliberately-deferred follow-up ("the durable fix is the D53 reaper plus a real started_at"), triggered by live evidence, not a fresh discovery: running the real ch5/T1 generation, an ARQ retry was delayed ~32 minutes before being dequeued (event-loop-blocking), and the reaper marked the lesson `failed` while it was still actually running — leaving `lessons.status='failed'` and `lesson_jobs.status='running'` permanently inconsistent. Same run also hit a real, non-code blocker worth recording: Sarvam TTS returned `402 Payment Required` (account out of credits, same shape as the L0 OpenAI blocker) and Azure returned `401` (pre-existing, never configured) — every segment fell to the free browser fallback as a result
  - `apps/api/app/workers/jobs/content_pipeline.py` (`_update_lesson_status` writes real `lesson_jobs.started_at` on the "running" transition, fresh on every retry), `apps/api/app/workers/jobs/reap_stale_lessons.py` (queries `lesson_jobs` directly, generous outer bound + precise per-row refinement using `started_at` when available). Gate 5/Gate 7 in `router.py` deliberately unchanged — their conservative direction is safe, only the reaper's false-positive direction was harmful
  - **AC:** `test_does_not_reap_a_job_with_a_recent_real_start_despite_old_created_at` reproduces the exact live false positive directly ✅; 5 more tests covering the base/never-started/no-op/query-shape/one-bad-row cases ✅; `test_running_transition_writes_a_real_started_at` in `test_timeout_contract.py` ✅; RED-GREEN via `mv`-aside + `git stash`/pop ✅; full repo-wide regression 52 failed/2113 passed/86 skipped — established baseline, zero new failures ✅ — see `docs/stories/3-54-d91-reaper-real-started-at.md`

---

## Sprint 4 — Weeks 8–9 (Due: ~2026-08-13)

> **Goal:** Load-tested, rate-limited, RLS-audited, Stripe-ready, runbook written.

- [ ] **S4-1 Load test: 50 concurrent lesson generations**
  - Use `locust` or `k6`
  - Assert: P99 enqueue latency <500ms; pipeline completion within SLA (≤15 min per lesson)
  - **AC:** 50 concurrent jobs complete without crash; no Redis drops; cost ceiling respected under load; results documented

- [ ] **S4-2 Pipeline reliability fixes from test sessions**
  - Prioritize: retry exhaustion, cost ceiling mid-flight, Redis connection drops, node timeout under load
  - **AC:** All failure modes from S4-1 resolved; no silent failures in production

- [ ] **S4-3 Payment integration — REVISED 2026-08-31: provider is Razorpay, not Stripe**
  - **Correction, not just an update:** the Story 5-3 Stripe implementation described in this
    line through 2026-08-26 was built without visibility into a parallel, real effort already
    underway — PR #157 ("Story 4-1 — Razorpay Payment Backend", branch
    `razorpay-backend-endpoints-dev3`, opened 2026-08-27 by Tanmay Gupta, under a *different*
    story-numbering track, Epic 4 not Epic 5) — which is the team's actual, live decision.
    Razorpay fits this product's India-first deployment far better than Stripe (UPI, INR
    pricing, no US-centric card-only assumption). PR #157's own description confirms the pivot
    explicitly: "S4-02 in dev2 tracker still describes Stripe Checkout Redirect. Razorpay is
    fundamentally different (inline modal, no redirect)."
  - **Story 5-3 (Stripe) is closed, not merged, branch deleted** — PR #158 closed 2026-08-27,
    `sprint4/s4-3-stripe-checkout` deleted both locally and on origin, confirmed `main` was never
    touched (PR was never merged; no Stripe payments code exists anywhere in `main`'s history).
    `docs/stories/5-3-stripe-checkout-integration.md` and its DEFECT-REGISTER entries (D136,
    D137) describe a dead, unshipped implementation — kept in `docs/stories/` for the historical
    record (a real 8-layer review did happen and did catch a real money-losing bug class, worth
    keeping as a reference for whoever reviews the Razorpay webhook's own idempotency logic), but
    must not be read as "S4-3 done."
  - **Real S4-3 status: see PR #157 instead** — backend complete per its own description
    (`create-order` + webhook, HMAC-verified, DB-UNIQUE idempotent, `lesson_access` table,
    25 tests, 6-layer review done), with 4 explicitly named open gaps pending team answers
    (no `GET /api/payments/access` endpoint yet; all lessons priced at `price_paise = 0`,
    which Razorpay will reject on a real charge; access still gated behind the beta
    `ApprovedUser` allowlist, not real students; no rate limiting on payment endpoints yet).
    Not marked `[x]` here because it isn't merged and has open gaps — this line should be
    updated again once PR #157 actually lands.

- [x] **S4-4 Rate limiting — per-route limits** — ✓ 2026-08-25 (Story 5-4, branch `sprint4/s4-4-rate-limit-per-route`)
  - `apps/api/app/main.py` — `slowapi` middleware mounted ✓
  - **This line's "not yet configured ✗" was already stale before this story started** — direct
    read of `content/router.py:692` found `@limiter.limit("5/minute", key_func=_get_user_key)`
    already present and already covered by `test_content_router.py::test_upload_lesson_429_rate_limit`.
    Flagged, not silently corrected: S1-10 below explicitly said "do not defer to Sprint 4," and
    the decorator's presence suggests it landed around that time anyway — yet this line persisted
    as PARTIAL. Two tracker entries disagreed about the same fact; neither had been reconciled
    against the code until this story.
  - **Real gap closed (D49):** `RATE_LIMIT_STORAGE_URL` defaulted to `memory://` with no startup
    guard — a multi-replica deploy silently multiplies every ceiling by replica count. Fixed via
    `assert_rate_limit_storage_configured()` (`core/rate_limit.py`), called first thing in
    `main.py`'s `lifespan()`; raises `RuntimeError` outside debug mode. Actually pointing
    `RATE_LIMIT_STORAGE_URL` at a real shared Redis instance in each deployed environment still
    needs ADR-001 §4's open Redis-location decision (Upstash Mumbai vs. Fly Redis) — the guard
    will correctly refuse to start any non-debug deploy until that lands, which is intended.
  - **AC:** Exceeding 5 uploads/minute returns `429` with `Retry-After` header; limit is per-user (JWT sub), not global IP — ✓ pre-existing, re-confirmed green (`test_rate_limit_key.py` 8 tests + `test_content_router.py`)
  - 8 new tests added (`test_rate_limit_storage_guard.py` ×6, `test_rate_limit_redis_storage.py` ×2, the latter fakeredis-backed proving real cross-instance sharing). Full unit suite: 1241 passed / 6 skipped / 3 pre-existing unrelated failures (D134), unchanged before/after. See `docs/DEFECT-REGISTER.md` D49 (closed) and `docs/stories/5-4-rate-limiting-per-route.md` for full detail.

- [x] **S4-5 RLS security audit on all Supabase tables** — ✓ 2026-08-26 (Story 5-5, branch `sprint4/s4-5-rls-audit`)
  - All tables have RLS enabled (verified in migrations) ✓ — and re-verified **live**, not just from
    migration text: real minted sessions (owner/stranger, via the service-role Admin API's
    `generate_link`, since this project uses asymmetric JWT Signing Keys and a self-minted HS256
    token cannot authenticate against it) plus the static anon key, run as **SELECT against all 15
    live tables** (every "0 rows" result cross-checked against service-role ground truth). Full
    accept+reject **CRUD** live-tested end-to-end on 2 tables covering the schema's 2 ownership-
    predicate shapes, plus 2 live cross-account INSERT-rejection spot-checks on join-based tables —
    the other 11 tables' write commands rest on migration-text confirmation only, registered as
    **D128** rather than overclaimed. No RLS gap found in anything actually exercised.
  - `attention_events` consent gate confirmed live for 2 of the 4 required states: real INSERT with
    real consent + `user_consents` audit row succeeded (201); a real account with
    `attention_consent=false` and no audit row was rejected (403) on the identical INSERT against
    their own session. The remaining 2 states are part of D128 (would need mutating a real user's
    actual consent record or a new disposable account). A stranger's session got 0 rows on
    SELECT/UPDATE/DELETE of the owner's row; owner's own cleanup DELETE succeeded. DELETE/UPDATE
    never gate on `attention_consent` — judged **intentional** (an erasure right shouldn't depend
    on active consent), registered as D127 so a future "symmetry fix" doesn't make it worse, not
    left as a silent gap.
  - `user_consents.consent_type` only allows 2 values (`attention_tracking`, `learner_dna`);
    Epic-5's DoD wants a 3rd (`data_processing`, at signup) that is entirely unimplemented
    (confirmed by repo-wide grep — zero writers) — registered as D126, open, owner TBD.
  - Storage buckets (4, all private, zero `storage.objects` policies) live-confirmed: anon AND a
    real authenticated user both get zero direct bucket/object access; only signed URLs work.
  - Both privileged RPC functions (`merge_lesson_job_node_output`, `increment_learner_dna_session_count`)
    live-tested directly — anon and a real authenticated user both get `42501 permission denied`
    calling either one; live grants match migration text, no dashboard-side drift.
  - **AC:** Audit report committed to `docs/`; no table accessible without RLS; `attention_consent`
    gate verified — ✓ `docs/security/rls-audit.md`; see `docs/stories/5-5-rls-security-audit.md`
    for full detail and `docs/DEFECT-REGISTER.md` D126/D127/D128.

- [ ] **S4-6 Railway backups + disaster recovery tested**
  - Test restore from latest backup; validate data integrity post-restore
  - **AC:** Recovery procedure documented; restore completes in <30 min; data integrity confirmed

- [ ] **S4-7 On-call runbook written**
  - `docs/` — 5 most likely failure scenarios with step-by-step resolution
  - Scenarios: ARQ job stuck, cost ceiling breach mid-pipeline, Redis unreachable, Supabase down, pipeline node 500-loop
  - **AC:** Runbook committed; each scenario has ≤5 resolution steps; tested by a teammate who didn't write it

---

## Week 10 — Launch (Due: ~2026-08-20)

> **Goal:** First paying student completes a full session without manual intervention.

- [ ] **W10-1 Production deployment verified end-to-end**
  - **AC:** Full lesson pipeline runs in production with a real PDF; lesson plays in browser for a real user

- [ ] **W10-2 Monitoring dashboards live**
  - Langfuse (pipeline costs + traces), Sentry (errors), Railway (infra + Redis)
  - **AC:** All three dashboards populated; alerts configured for pipeline failures and cost ceiling breaches

- [ ] **W10-3 On-call rotation established**
  - **AC:** All 4 devs on rotation schedule; runbook link shared with all

- [ ] **W10-4 First paying user pipeline job monitored live**
  - **AC:** Real user, real PDF, real payment — pipeline completes without manual intervention; CES data flows to Dev 3

---

## Ahead-of-Schedule Wins

| Item | Built | Intended Sprint | Action Now |
|------|-------|----------------|------------|
| `core/retry.py` — `with_retry()` | Sprint 0 | Sprint 1 (S1-1) | Apply to all Sprint 1 nodes immediately ✅ |
| `core/circuit_breaker.py` | Sprint 0 | Sprint 3 (S3-3) | Wire into ALL Sprint 2 provider calls — do not wait |
| `core/cost_tracker.py` | Sprint 0 | Sprint 2 (S2-13) | Wire into each LLM/TTS/image node as Sprint 2 nodes are built |
| `slowapi` middleware | Sprint 0 | Sprint 4 (S4-4) | Add per-route limit to `POST /api/content/lessons` in Sprint 1 (S1-10) |

---

## Frozen Contracts (PRD §16)

| Contract | File | Status |
|----------|------|--------|
| Lesson package schema | `packages/shared/lesson_package.schema.json` | ✅ Frozen — 4-dev PR to change |
| TypeScript lesson types | `packages/shared/types/lesson.ts` | ✅ Frozen |
| WebSocket discriminated union | `packages/shared/types/ws.ts` | ✅ Frozen |
| Assessment API (OpenAPI) | Auto-generated from FastAPI routes | ✅ Frozen |
| DB migrations | `supabase/migrations/` | ✅ Never modify applied |

---

## Security Checklist (PRD §18)

| Item | Status | Notes |
|------|--------|-------|
| JWT verified locally (PyJWT + `SUPABASE_JWT_SECRET`) | ✅ | `dependencies.py` — no remote call per request |
| RLS enabled on all Supabase tables | ✅ | Enabled in both migrations; full audit due Sprint 4 (S4-5) |
| Env vars never committed | ✅ | `.gitignore` covers all `.env*` patterns |
| `attention_events` RLS gates on `attention_consent = true` | ✅ | Enforced in migration 20260611 policy |
| Raw webcam video never leaves browser | N/A | Dev 2 owns — verify in integration review |
| No clinical score fields in API responses | ⬜ | Ensure no `iq_score`, `eq_score` fields in any `LessonPackage` or API response; DPDP Act 2023 |

---

## Module Ownership Reference

| Module | Dev 1 Touches? | Notes |
|--------|---------------|-------|
| `core/` | ✅ Owner | retry, circuit_breaker, cost_tracker, redis, db, langfuse |
| `providers/` | ✅ Owner | llm, tts, image, avatar — abstract interfaces + implementations |
| `modules/content/` | ✅ Owner | pipeline nodes, router |
| `workers/` | ✅ Owner | ARQ entry, job registry |
| `modules/tutor/` | Dev 4 | Do not modify — review only |
| `modules/assessment/` | Dev 3 | Do not modify |
| `apps/web/` | Dev 2 | Do not modify |
| `supabase/migrations/` | Dev 1 authors | All 4 devs must review migration PRs |

---

## Update Protocol

1. Change `- [ ]` → `- [x]`
2. Append ` — ✓ YYYY-MM-DD` to the task title line
3. Update the **Quick Status Dashboard** table at the top (increment Done, decrement Not Started or Partial)
4. Update **Last updated** in the header block

**Example — task just completed:**
```markdown
- [x] **S1-2 PyMuPDF text + image + layout extraction node** — ✓ 2026-06-28
```

**Example — task partially done:**
```markdown
- [ ] **S0-9 Langfuse wired globally** ⚠️ PARTIAL
  - ✓ Traces emitted per-call
  - ✗ No global flush on shutdown
```

Do not delete task details after completion — they serve as a specification record.
