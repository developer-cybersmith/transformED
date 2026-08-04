# Dev 1 Handoff: Sprint 2 Pipeline — Full Status Audit + Bug Report

**From:** Dev 2
**To:** Dev 1 (content pipeline owner)
**Date:** 2026-07-27
**Context:** Dev 1 asked Dev 2 to check `docs/master-tracker.md` for his Sprint 2 task list and report back which tasks are genuinely working vs. broken, so everything can be fixed in one pass — including the two bugs already reported earlier this week (quiz-question duplication on retry, TTS-fallback losing the narration script).

**Important:** `docs/master-tracker.md`'s Dev 1 Sprint 2 section was stale (dated 2026-07-13, showed all 11 nodes as not-started). It has been corrected in place to match this audit — see the tracker for the per-node checklist. This doc is the detailed write-up behind that correction.

---

## TL;DR

Everything is implemented. Most of it is genuinely correct. Two real, **systemic** bugs remain open — and the scope is bigger than originally reported: the duplication bug isn't quiz-specific, it affects all 6 Phase 1 economy nodes' output fields.

---

## Status by node

| Node | Status | Notes |
|---|---|---|
| `lesson_planner_node` | ✅ Working | No bugs found. Idempotent (plain dict field, no accumulation risk). Strong validation + cost-ceiling-aware downshift. |
| `slide_generator_node` | ✅ Working | Same clean design as `lesson_planner_node`. |
| `summarise_segment_node` | ⚠️ Has the systemic bug | See below. |
| `segment_complexity_node` | ⚠️ Has the systemic bug | See below. |
| `quiz_generator_node` | ⚠️ Has the systemic bug | This is the one live-tested as "32 quiz questions from 2 unique items, repeated 16x." |
| `jargon_extractor_node` | ⚠️ Has the systemic bug | See below. |
| `intervention_messages_node` | ⚠️ Has the systemic bug | See below. |
| `narration_generator_node` | ⚠️ Has the systemic bug | This is the one behind the TTS-fallback script-loss symptom (see Bug 2). |
| `tts_node` | ✅ Working, cost caveat | Not buggy itself — but if it runs after several ARQ retries have already piled up duplicate `narration_scripts` entries (Bug 1), it'll synthesize/upload audio for the duplicates too. Wasted cost, not a correctness bug. |
| `image_generator_node` | 🔵 Not fully verified | Fallback chain (GPT Image → Imagen → text-only) and `_decode_data_uri()` hardening look solid on the portion reviewed. Not exhaustively read this pass. |
| `package_builder_node` | ❌ Has 2 real bugs | See Bug 1 and Bug 2 below. |
| Cost ceiling (`MAX_LESSON_COST_USD`) | ✅ Working | Wired via `check_ceiling()`/`accumulate_cost()` across all premium nodes + the Phase 1 fan-out router. Fails safe (downshifts), not fail-open. |
| WebSocket `lesson_ready` push | ✅ Working | Matches the frozen `ws.ts` contract. |
| Eval harness (5 PDFs) | 🔵 Harness done, not run live | Harness itself built + unit-tested (Story 2-14). The actual 5-PDF run is gated behind `@pytest.mark.live_eval` — a documented scope decision, not a gap. |

---

## Bug 1 — Systemic duplication across all 6 Phase 1 economy nodes (was reported as "quiz duplication," actually broader)

**Root cause:** every Phase 1 economy node's `PipelineState` output field is `Annotated[list, operator.add]` — a pure concatenating reducer:

```python
segment_summaries: Annotated[list[dict[str, Any]], operator.add]
quiz_questions: Annotated[list[dict[str, Any]], operator.add]
complexity_scores: Annotated[list[dict[str, Any]], operator.add]
glossary: Annotated[list[dict[str, Any]], operator.add]
intervention_prompts: Annotated[list[dict[str, Any]], operator.add]
narration_scripts: Annotated[list[dict[str, Any]], operator.add]
```

Each node's own Supabase-backed checkpoint (`_read_phase1_checkpoint`/`_write_phase1_checkpoint`) correctly stops the node from **re-spending** on the LLM call when a checkpoint already exists — but every node still does `return {"<field>": [cached_value]}` on that cache hit. Since the field is a concatenating reducer, that cached value gets **appended again** into the already-accumulated list every time `_fan_out_phase1_economy_nodes` re-dispatches — e.g. on every ARQ retry of `content_pipeline_job`.

**Live-tested symptom:** 2 unique content items → 32 quiz questions (16 unique items × 16... i.e. each repeated 16x); 3 unique items → 48 (repeated 16x) — consistent with ~16 retries.

**This affects all 6 fields identically**, not just quiz — `segment_summaries`, `glossary`, `intervention_prompts`, and `narration_scripts` all accumulate duplicates the same way. It's just that quiz duplication is the one that's visually obvious in the player (extra quiz questions); the others are silently duplicated too and would show up as bloated/repeated content wherever `package_builder_node` consumes them.

**Cheapest fix:** rather than patching the cache-hit branch in all 6 nodes individually, dedupe by `segment_id` in `package_builder_node`'s own grouping helpers (`_group_by_segment_id` / `_index_by_segment_id`) before building the final `LessonPackage`. That's a single change point that resolves the visible symptom for every field at once. (The nodes still over-accumulate internally in `PipelineState`, but the final package would no longer surface duplicates — worth deciding whether that's sufficient or whether the underlying reducer/checkpoint interaction should also be fixed properly, e.g. by checking whether the checkpointed value is already present in the current accumulated list before returning it.)

---

## Bug 2 — `_fallback_narration()` discards a recoverable script

**Root cause:** in `package_builder_node`, `_fallback_narration()` returns:

```python
{"script": "", "audio_url": "", "audio_provider": "browser", "timestamps": []}
```

unconditionally whenever a segment has zero `audio_assets` entries — even though the real narration script is sitting right there in `state["narration_scripts"]` for that `segment_id`, produced by the separate `narration_generator_node`. `tts_node` only *consumes* that script to produce audio; when `tts_node`'s output is missing/degraded for a segment, the script itself is still perfectly recoverable, but `_fallback_narration()` throws it away too.

**Live-tested symptom:** empty `audio_url` → `<audio>` element fires `'ended'` almost instantly → quiz fires at "0:00 total time," with no narration ever shown either.

**Fix:** `_fallback_narration()` should look up `state["narration_scripts"]` for the matching `segment_id` and use that script if present, only fully blanking `script` when there's genuinely nothing there either.

---

## Everything else

Confirmed working, no action needed: `lesson_planner_node`, `slide_generator_node`, cost ceiling enforcement, the WebSocket `lesson_ready` push, and the eval harness (as a harness — the live 5-PDF run itself just hasn't been executed yet, which is a deliberate scope decision already documented in Story 2-14).

`image_generator_node` wasn't exhaustively re-read this pass — nothing looked wrong in what was reviewed, but flagging as not-fully-verified rather than claiming a clean bill of health.
