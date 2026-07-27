# TransformED AI — Sprint 2 Re-Audit Report

**Date:** 2026-07-27
**Scope:** Re-audit of branch `sprint2/gapfix-dev1-audit-findings`, post Story 2-25 (Dev1-owned gap-fixes) + its 5-agent code-review hardening round. This report (a) independently re-verifies that Story 2-25's fixes are real and complete, and (b) re-checks the remaining 21 Dev2/Dev3/Dev4-owned findings from the prior 360-degree audit (`docs/reports/sprint2-360-audit-2026-07-27.md`) against current code. All findings below were independently re-verified against live code on this branch; nothing here is speculative.

---

## Executive Summary

**Dev1's fixes hold up. The rest of the system does not.**

Story 2-25 closed all 4 Dev1-owned findings from the prior audit — the admin module now has a real authorization mechanism and real queries, the media signed-URL allowlist is trimmed to only the buckets that actually work, the stale pipeline docstring is corrected, and the three-way `tier`/nullability contract drift is reconciled. The accompanying 5-agent code review caught and fixed six additional real bugs (case-sensitive admin-email matching, an env-var parsing bug that meant the comma-separated `ADMIN_EMAILS` format never worked at all, an unbounded cost-report scan with an uncaught-crash risk, unvalidated pagination bounds, a malformed-`job_id` 500 risk, and an unbounded Redis health-check hang) before merge. This part of Sprint 2 is genuinely solid.

Everything downstream of Dev1's work is unchanged and still broken. The student-facing player, dashboard, and library are still 100% mock-backed despite the real backend endpoints being ready and correct. The entire Dev4 tutor FSM/CES/WebSocket subsystem still receives zero live traffic — the socket is never opened by the live player, and even where it is, the backend still never broadcasts a real state transition. Dev3's quiz feedback contract mismatch (`is_correct`/`explanation` vs. `correct`/`message`) is still CRITICAL and unchanged — every quiz in production currently renders every answer as wrong with a blank explanation. Auth's `/signup`/`/signin`/`/onboarding/complete` are still 501 stubs bypassed by direct Supabase SDK calls from the frontend.

**Bottom line:** Dev1 is done and should not be re-flagged. Sprint 3 kickoff should still be blocked on the same wiring gate the prior audit called for — the fixes that landed did not touch any of the P0 blockers (mock-backed player, quiz feedback contract, dead WebSocket pipeline). None of this should be represented as "wiring complete" to leadership.

---

## Dev1 Fixes — Verification Results

Verified against `docs/stories/2-25-sprint2-audit-gapfix-dev1-items.md` (Status: done) and current code on `sprint2/gapfix-dev1-audit-findings`.

| # | Original finding | AC | Verdict | Notes |
|---|---|---|---|---|
| 1 | Admin module 100% stub, no authorization mechanism anywhere in the codebase (prior audit: Auth/Admin/Analytics #1, CRITICAL) | AC-1 | **FIXED** | `require_admin` dependency added (`app/dependencies.py`), gated on a new `admin_emails` env-allowlist setting checked against the JWT `email` claim; fails closed (403 on non-admin or missing claim, not 404/401). All 4 endpoints (`list_jobs`, `get_job`, `get_cost_report`, `deep_health`) implemented for real against `lesson_jobs`/`lessons`/Redis — no longer 501s. `CostReport.by_provider` was deliberately dropped rather than faked, since no per-provider cost breakdown exists anywhere to aggregate — an honest gap, not a regression. |
| 2 | `source-pdfs`/`avatar-clips` media allowlist entries structurally broken (can never succeed even for the legitimate owner); `lesson-slides` allowlisted but never provisioned (prior audit: Media #2 MEDIUM, #3 LOW) | AC-2 | **FIXED** | `_ALLOWED_BUCKETS` trimmed from 5 entries to 2 (`lesson-audio`, `lesson-images` — the only buckets `content/router.py` actually signs). Confirmed via repo-wide grep that none of the 3 removed buckets had any frontend caller before removal. Regression test added asserting the removed buckets now 400. |
| 3 | `graph.py` module docstring stale — claims Phase 1 nodes lack per-section checkpointing when they don't (prior audit: Content Pipeline #3, LOW) | AC-3 | **FIXED** | Docstring corrected to reflect that Story 2-1b's checkpoint/idempotency calls (`_read_phase1_checkpoint`/`_write_phase1_checkpoint`/`_increment_phase1_progress`) are present in all 6 economy nodes. |
| 4 | `LessonRecord.title`/`source_file_path` non-nullable in `lesson.ts` despite backend returning `None`; `LessonMetadata.tier` required in JSON Schema/TS but defaulted in Pydantic (prior audit: Shared Contract Drift #1 MEDIUM, #3 LOW) | AC-4 | **FIXED** | `lesson.ts` and `lesson_package.schema.json` corrected to match Pydantic's existing (already-correct) behavior — `title`/`source_file_path` now `string \| null`, `tier` now optional. Zero Python change needed; new regression test proves a tier-omitting payload now validates against the raw JSON Schema, not just via Pydantic's default-masking `model_dump`. |

**5-agent code-review hardening (same story, additional fixes before merge) — all confirmed applied:**
- Fixed: `ADMIN_EMAILS` as a JSON array bypassed lowercasing, locking out legitimate admins with differently-cased emails — list-input path now normalizes case too.
- Fixed: a second, related bug the above fix surfaced — pydantic-settings was JSON-decoding the `list[str]` env value before the validator ran, so the documented comma-separated `ADMIN_EMAILS` format never worked at all. Fixed via `Annotated[list[str], NoDecode]`.
- Fixed: `get_cost_report` did an unbounded full-table scan with client-side date parsing that would crash on any malformed `created_at` — refactored to a server-side filter (`lessons!inner(...)` + `.gte(...)`), crash risk eliminated.
- Fixed: `list_jobs`'s `limit`/`offset` were unvalidated (could invert the range or fetch unbounded) — now `Query(ge=1, le=200)` / `Query(ge=0)`.
- Fixed: `status_filter` had no allow-list, silently 200-ing empty on typos — now validated, 400s on unrecognized values.
- Fixed: `get_job` didn't validate `job_id` as a UUID, risking an unhandled 500 — now guarded, returns clean 404.
- Fixed: `deep_health`'s `redis.ping()` had no timeout, risking an indefinite hang on an unresponsive Redis — wrapped in a 3s `asyncio.wait_for`.
- Also noted, correctly deferred (not a defect): the `image_url`/`audio_url` → `image_path`/`audio_path` rename (the audit's own LOW-severity item) was explicitly kept out of scope given its blast radius and the CLAUDE.md §16 four-dev-review requirement for frozen-contract changes — flagged as a proposed follow-up rather than silently dropped. This is the right call, not a gap.

**Process note (transparency, not a fix-quality issue):** the code review flagged that Story 2-25's story-first commit was not story-only (it bundled the audit report alongside the story file), a violation of CLAUDE.md's BMAD gate. This was accepted and documented rather than rewritten, since the commit was already pushed to the shared remote branch. Noted for process hygiene, does not affect the fix's correctness.

**Verdict: all 4 original Dev1-owned findings are fixed and complete, with genuine additional hardening from the review round. Nothing here needs to be reopened.**

---

## Remaining Findings by Owner

### Dev2-owned

| Title | Severity | Evidence | Recommendation |
|---|---|---|---|
| Lesson player still wired to mock API, not the real content endpoint | HIGH | `useLesson.ts` → `lesson.service.ts` → `mocks/api/lesson.ts::getLessonPackageById` returns a static fixture after an artificial delay; no fetch/axios call anywhere in the chain. `[DEV1-SPRINT2-PENDING]` comments still present in all three files. Backend `GET /lessons/{lesson_id}` (`content/router.py:318-366`) is real, complete, and ready to consume — UUID-validated, ownership-checked, signed-URL-resolved. | Replace the mock-backed `lesson.service.ts` with a real HTTP call to `GET /api/content/lessons/{id}`, polling `status` until `ready`. Coordinate with Dev1 before changing the consumed shape per the existing comment instruction. |
| Dashboard and library services still exclusively wired to mocks | HIGH | `dashboard.service.ts`/`library.service.ts` import `dashboardApi`/`libraryApi` from `../mocks/api` with zero references to `fetch`/`axios`/the real content API. Backend `GET /lessons` (list, paginated, user-scoped) is real and ready. | Wire both services to `GET /api/content/lessons?limit=&offset=`, mapping `LessonStatusResponse[]` into the dashboard/library card shape. No backend change needed. |
| `/api/media/signed-url` has zero frontend callers | HIGH | Repo-wide grep for `signed-url`/`signedUrl`/`signed_url` across `apps/web/src` returns zero matches. The player doesn't even consume the real content endpoint yet, so there is no live consumer of any signed media URL today. | Either wire the player to call this endpoint for expiry refresh, or remove it. Track together with the broader real-content wiring work; don't build a parallel path without syncing with Dev1. |
| No client-side refresh/error-recovery path for expired signed URLs | LOW | `<audio>` in `AudioTimeline.tsx` has no `onError` handler; `useLesson.ts` fetches the lesson package once via SWR with no polling/refetch. Backend signs both `audio_url`/`image_url` with a flat, unparameterized 1-hour `expires_in`. | Bump `expires_in` for embedded lesson content, or add an `onError` handler that re-signs the failed segment (would also give `/signed-url` a real caller). |
| Live player never mounts `useLessonSocket` — tutor WebSocket never opens in production | **CRITICAL** | `useLessonSocket` has zero call sites outside its own file and unit test. `Player.tsx`/`PlayerLoader.tsx` never reference it, `LessonSocket`, or `/ws/`; the entire tree only reads/writes local Zustand player state. Backend `/ws/{session_id}` is fully implemented and dispatches attention/state events but has no client driving it in prod. | Mount `useLessonSocket(sessionId)` inside `Player.tsx` (or a wrapping provider) and wire `sendAttentionSignal` into the MediaPipe capture loop before Sprint 3 CES work can be validated live. |
| Session summary endpoint has no frontend consumer | MEDIUM | `analytics/service.py::get_session_summary` computes and returns raw numeric CES/attention aggregates correctly (ownership/IDOR check solid), but no fetch/hook/component in `apps/web/src` references it. The existing `SessionReport` UI consumes a different endpoint (`assessment` module's report, not this one). | Build a session-report/summary UI consuming this endpoint in Learner-DNA descriptive style, or explicitly flag as a known Sprint 3 backlog gap rather than a backend defect. |

**Cross-owner (Dev2 + Dev3) — assessment wiring:**

| Title | Severity | Evidence | Recommendation |
|---|---|---|---|
| Quiz feedback field-name mismatch — backend sends `is_correct`/`explanation`, frontend reads `correct`/`message` | **CRITICAL** | `assessment/service.py` builds feedback with keys `question_id, question, is_correct, correct_index, correct_option, selected_option, explanation` — no `correct`/`message` key exists. `QuizFeedbackItem` (frontend type) and its only consumer, `QuizOverlay.tsx`, read `f.correct`/`f.message` — both always `undefined`. Every quiz renders red/incorrect with a blank message for every question regardless of actual correctness. `QuizResult.feedback` is typed `list[dict[str, Any]]` so Pydantic never catches the drift. | Align the contract: change `QuizFeedbackItem` to `{question_id, is_correct, explanation, correct_option, selected_option}` and update `QuizOverlay.tsx` accordingly, or add backend aliases. Needs coordinated Dev3 (backend) + Dev2 (frontend) fix — cross-team wire contract. |
| `TeachbackResult.rubric_scores` type mismatch across backend and 2 frontend type files | MEDIUM | Backend intentionally sends `dict[str, str]` descriptive labels (accuracy/completeness/clarity → Exceptional/Proficient/etc., per the no-raw-scores rule, an authorized Story 3-14 breaking change). Both `types/assessment.ts` and `lib/assessment.ts` still declare it numeric, with two *different* key sets, neither matching the backend's. Currently latent — `TeachBackModal.tsx` deliberately never reads the field — but will break the first feature that consumes it. | Pick one canonical shape (`dict[str,str]` of labels, matching backend + CLAUDE.md) and make both frontend type files match exactly, including the key set. Needs 4-dev sign-off (frozen-contract rule) — this is primarily a frontend-type fix since the backend is already correct per Story 3-14. |
| SessionReport API sends raw numeric CES/teachback score on the wire despite DOM rendering going through label formatters | LOW | `SessionReport` response model carries raw `ces_score: float`, `ces_breakdown: dict[str,float]`, `teachback_score: float | None` with no server-side label conversion. `SessionReport.tsx` does render label-only output via `formatCesLabel`/`formatTeachbackLabel`, but the client-side type still exposes the raw numbers, visible via network inspection. Known, documented Story 3-19 frozen-contract tradeoff, not a new regression. | If "no clinical scores shown to students" is meant at the wire level (not just DOM), move label conversion server-side and drop raw floats from the response — needs 4-dev frozen-contract review (Dev3 backend + Dev2 frontend). Otherwise, annotate CLAUDE.md that "shown" means rendered UI only. |
| `reassessment_due` computed correctly server-side but discarded by `OnboardingFlow.tsx` before it can be surfaced | HIGH | `GET /user/dna` correctly computes `reassessment_due` from a Redis key set every 10th session (`get_learner_dna_data`, non-fatal on Redis errors). `OnboardingFlow.tsx`'s mount-time probe calls `getLearnerDna()` purely to check onboarding status, discards the resolved object entirely, and redirects to `/dashboard`. No component anywhere reads `reassessment_due` — grep confirms it appears only in types and test fixtures. | Add a banner/prompt reading `dna.reassessment_due` (dashboard or inside the onboarding success branch); fix the discard-then-redirect callback to capture the fetched DNA object. Dev2-owned frontend fix; no backend change needed. |

### Dev3-owned

No findings in this re-audit are owned exclusively by Dev3 — every remaining assessment-domain finding spans Dev2 (frontend consumer) as well and is listed above under the cross-owner section. Dev3's backend logic for these items (quiz feedback shape, `rubric_scores` labeling, session report scores, `reassessment_due` computation) is itself functionally correct in each case; the defects are either a naming mismatch with the frontend or a frontend gap in surfacing already-correct backend output. Dev3 should still be looped into the coordinated fixes above (quiz feedback field names in particular, since that's a backend-owned dict shape).

### Dev4-owned

| Title | Severity | Evidence | Recommendation |
|---|---|---|---|
| `state_change` is only ever sent on reconnect sync (`from==to`); no broadcast exists for real FSM transitions | **CRITICAL** | The only `state_change` send site is `ConnectionManager.connect()`'s reconnect branch, always a snapshot with `from_state == to_state`. `dispatch_event()` and all 7 node functions in `graph.py` persist state to Redis but never call `manager.send(...)`. `tutor/service.py` only broadcasts `tutor_intervene`, never `state_change`. `useLessonSocket.ts` has a correct, tested handler ready to consume real transitions — it's simply never fed one. | Add a `manager.send(session_id, {type:'state_change', payload:{...}})` broadcast inside `dispatch_event()` (or each node) whenever `current_state` actually changes, gated so the reconnect path isn't double-fired. |
| Frozen `AttentionAckMessage` still types a `ces: number` field the backend never sends | HIGH | `ws.ts` declares `AttentionAckMessage` payload as `{session_id: string; ces: number}`. The backend's actual frame is `{session_id, status:'ok'}` with an explicit "PRD §18: never expose raw clinical/CES scores to the student client" comment — `ces` is never sent. No runtime break today (the frontend handler is a no-op), but any code destructuring `ces` will type-check against a field that never exists on the wire. | Update the frozen `ws.ts` contract to `{session_id: string; status: 'ok'}` via the required 4-dev-reviewed contract PR. |
| CES/attention processing not restricted to `TEACHING` state — can force incorrect transitions out of `CHECKING_IN`/`QUIZZING` | HIGH | `process_attention_signal()` computes CES and dispatches `distraction_detected` with no check of current `tutor_state`. `route_from_checking_in`/`route_from_quizzing` both fall through to `return "teaching"` for any unrecognized event, silently teleporting the FSM back to TEACHING from a genuine CHECKING_IN/QUIZZING state. Only `route_from_teach_back` is explicitly guarded. Frontend (`lessonSocket.ts`) already has a code comment documenting awareness of this exact hazard for `session_start` resends. | Add an explicit state guard in `process_attention_signal` (only dispatch when `tutor_state == TEACHING`); change the two unguarded routers' fallthrough to return the current state (no-op) instead of `"teaching"`, matching the `route_from_teach_back` pattern. |
| Tutor REST endpoints `get_session_state` and `trigger_intervention` are unimplemented 501 stubs | HIGH | Both endpoints unconditionally `raise HTTPException(501)` with TODO comments ("Delegate to tutor service layer"/"Delegate to tutor state machine"), touching neither Redis nor the state machine. No frontend caller exists yet, so nothing is currently broken, but nothing can be built against them either. | Implement `get_session_state` by reading the documented Redis tutor-state keys; implement `trigger_intervention` via `dispatch_event` with admin-gated force/cooldown-bypass logic. |
| `TutorSessionState` response model exposes raw `ces_score` with no role gating | MEDIUM | The Pydantic model for `GET /session/{id}/state` declares `ces_score: float`; the endpoint's only auth dependency is `CurrentUser` (any authenticated user, no role/ownership check). Per PRD §18 this would leak a raw clinical score to any authenticated caller the day the 501 stub is filled in. Currently latent — no live leak yet. | Before implementing the body: either drop `ces_score` from the student-reachable response (admin-only endpoint for it), or add an explicit admin-role + session-ownership check. |
| Auth module `/signup`, `/signin`, `/onboarding/complete` are still 501 stubs; frontend bypasses backend via direct Supabase Auth SDK calls | HIGH | All three raise 501; only `GET /me` is functional (echoes JWT payload). `SignInForm.tsx`/`SignUpForm.tsx` call `supabase.auth.signInWithPassword`/`signUp`/`signInWithOAuth` directly, never touching the FastAPI routes. The real, working onboarding path is a *different*, fully-implemented endpoint (`assessment/router.py`'s `/onboarding/submit`, with Redis idempotency) — the auth module's `/onboarding/complete` is orphaned dead code, not just unfinished. | Decommission `/signup`, `/signin`, `/onboarding/complete` from `auth/router.py` (Supabase SDK + `/assessment/onboarding/submit` already cover these flows), removing the dead 501s and TODOs — or, if server-side profile-row creation on signup is still required (the TODO confirms it was intended but never happened), implement it and update `SignUpForm.tsx` to call it. Document the decision so the next audit doesn't re-flag intentionally-orphaned code. |

**Cross-owner (Dev2 + Dev4) — session identity:**

| Title | Severity | Evidence | Recommendation |
|---|---|---|---|
| Player's WebSocket `session_id` is client-generated and never reconciled with the backend | MEDIUM | `usePlayerStore.loadLesson()` generates `sessionId` via `crypto.randomUUID()` purely client-side with no round-trip to any backend session-creation call. The backend WS endpoint accepts any `session_id` from the URL with no validation against a server-issued/registered session record — no collision/replay protection, and no durable link to Dev3's session-report data. Compounded by the dead-socket finding above: today this ID never even reaches the backend in a real user flow. | Dev2+Dev4 should agree on a session-creation contract: either the backend mints `session_id` (returned from a REST "start session" call before the WS connects), or the client UUID is registered/validated via REST before the WS handshake. |

---

## Backend ↔ Frontend Sync — Current State

| Route / Path | Backend Status | Frontend Wired? | Notes |
|---|---|---|---|
| `GET /api/content/lessons/{id}` | Real, correct | **Mocked** | Player still calls `mocks/api/lesson.ts`, ignoring the real endpoint. Unchanged. HIGH. |
| `GET /api/content/lessons` (list) | Real, correct | **Mocked** | Dashboard/library still delegate to mock services. Unchanged. HIGH. |
| `GET /api/media/signed-url` | Real, correct, allowlist now fixed (Story 2-25) | **Not called** | Still dead code — no frontend consumer. HIGH. |
| `POST /api/assessment/quiz/submit` (feedback) | Real | Wired, but **Broken** | `is_correct`/`explanation` vs. `correct`/`message` mismatch unchanged. Every quiz renders wrong feedback. CRITICAL. |
| `GET /api/assessment/user/dna` (`reassessment_due`) | Real | Wired, but **Broken** | `OnboardingFlow.tsx` still discards the payload before checking the flag. Unchanged. HIGH. |
| `GET /api/assessment/session/{id}/report` | Real | **Real**, correctly labeled at render | Still the only genuinely-working sync path found. Wire payload still carries raw CES/teachback numbers (LOW leak). |
| `WS /ws/{session_id}` (tutor FSM/CES/attention) | Real, functional | **Not called** | `useLessonSocket` still never mounted in production. Unchanged. CRITICAL. |
| `state_change` WS message | Backend still never broadcasts on real transitions | N/A (frontend handler ready) | Still only a reconnect snapshot. Unchanged. CRITICAL. |
| `GET /api/tutor/session/{id}/state`, `POST /intervene` | 501 stubs | **Not called** | Unchanged. HIGH. |
| `GET /api/admin/jobs`, `/costs`, `/health` | **Now real**, admin-gated (Story 2-25 fix) | **No admin UI found** | Backend fixed; still no frontend admin panel consumes it — expected, out of Sprint 2 scope. |
| `GET /api/analytics/session/{id}/summary` | Real, still leaks raw CES/attention numerics | **Not called** | Latent leak, unchanged. MEDIUM. |
| `POST /api/auth/signup` / `/signin` / `/onboarding/complete` | 501 stubs (orphaned — real onboarding path is elsewhere) | **Bypassed** | Unchanged. HIGH. |

**Sync-check bottom line:** Story 2-25 moved one row (`/api/admin/*`) from "501 + no auth concept" to "real + admin-gated." Every other row is unchanged from the prior audit. Of the 12 routes/paths tracked, still only one (`GET /session/{id}/report`) is genuinely real end-to-end with correct rendering.

---

## Prioritized Asks

### Dev2 — priority order
1. **Unblock the demo path:** replace `lesson.service.ts`'s mock delegation with a real call to `GET /api/content/lessons/{id}`, polling `status` until `ready`. This is the single highest-leverage fix in the whole re-audit — nothing else matters if students see a canned lesson.
2. **Mount `useLessonSocket` in `Player.tsx`/`PlayerLoader.tsx`** and wire `sendAttentionSignal` into the MediaPipe capture loop — the entire Dev4 tutor subsystem needs a live client before it can be validated for Sprint 3.
3. **Fix the quiz feedback field mismatch** on the frontend side (`QuizFeedbackItem`/`QuizOverlay.tsx` → `is_correct`/`explanation`), coordinated with Dev3.
4. Wire `dashboard.service.ts`/`library.service.ts` to the real paginated `GET /api/content/lessons`.
5. Fix `OnboardingFlow.tsx`'s discard-then-redirect bug so `reassessment_due` can actually reach a banner.
6. Add an `onError` recovery path on `<audio>` for expired signed URLs (and give `/signed-url` a real caller in the process).
7. Reconcile `rubric_scores` type definitions with the backend's label shape (coordinate with Dev3/4-dev review).

### Dev3 — priority order
1. **Fix the quiz feedback field-name contract** (`is_correct`/`explanation`) — this is the CRITICAL item and it's backend-owned shape drift; coordinate the rename/alias with Dev2's `QuizOverlay.tsx` fix.
2. Decide, with the team, whether `SessionReport`'s wire payload should drop raw CES/teachback floats server-side (4-dev frozen-contract review) or whether CLAUDE.md's wording should be clarified to mean DOM-only.
3. Support Dev2's `reassessment_due` banner work if any backend adjustment is needed (current backend logic is already correct).
4. No independent Dev3-only action items surfaced this round beyond coordination on the above — the backend logic in this domain is otherwise sound.

### Dev4 — priority order
1. **Make `dispatch_event()` actually broadcast `state_change` on real transitions** — currently the entire FSM is invisible to any client; this is the CRITICAL blocker for validating Sprint 3's CES/attention pipeline.
2. **Gate `process_attention_signal` to `TEACHING` state only**, and fix `route_from_checking_in`/`route_from_quizzing`'s unguarded `"teaching"` fallthrough to stay-in-state instead.
3. Update the frozen `ws.ts` `AttentionAckMessage` to drop `ces` via the required 4-dev contract PR — small fix, closes a real contract lie.
4. Implement or formally remove the tutor REST stubs (`get_session_state`, `trigger_intervention`); if implementing, add the role/ownership gate on `ces_score` before shipping the body.
5. Decommission (or finish) the orphaned auth `/signup`/`/signin`/`/onboarding/complete` stubs — document the decision either way so future audits stop re-flagging it.
6. Coordinate with Dev2 on a backend-issued (or backend-validated) `session_id` to replace the unreconciled client-generated UUID.
