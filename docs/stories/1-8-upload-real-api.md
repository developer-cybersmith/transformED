# Story 1-8 — Upload Flow: Real API Integration

**Status:** done — 2026-07-13
**Sprint:** 1 (remainder item, resumed in Sprint 2 timeframe)
**Owner:** Dev 2
**Branch:** `sprint1/s1-8-upload-real-api`
**Supersedes:** the original S1-08 sketch in `docs/dev2-sprint-tracker.md` (written before Dev 1's backend existed and guessed an API shape that turned out wrong)

## Context

The original sketch assumed `POST /api/pipeline/submit` returning `{lesson_id, session_id}`, with pipeline progress streamed over `/ws/{session_id}` as 14 named stage events, auto-redirecting on a `lesson_ready` WS message.

Dev 1's Sprint 1 work (merged to `main` at `d38f357`) actually shipped:
- `POST /api/content/lessons` (multipart) → 202 `{lesson_id, job_id, status: "queued"}` (`apps/api/app/modules/content/router.py`)
- `GET /api/content/lessons/{lesson_id}` → `{lesson_id, status: queued|running|ready|failed, title, error, created_at, completed_at}` — flat status only, no per-stage/percentage data
- `GET /api/content/lessons` — paginated list (used by S1-09, not this story)

There is no `generation_progress` WS message anywhere in the backend (checked `apps/api` — zero matches) — the frozen `packages/shared/types/ws.ts` contract defines the type, but no pipeline node ever publishes it, and no Sprint 2 node work (`S2-1`..`S2-14`) has started yet to produce one.

A working `lesson_ready` WS push **does** exist (`apps/api/app/core/pubsub.py` + `content_pipeline_job` in `apps/api/app/workers/jobs/content_pipeline.py`): on pipeline completion the worker publishes to Redis channel `lesson_ready:{session_id}` (session_id falls back to lesson_id when no session row exists), and `core/websocket.py`'s `/ws/{session_id}` endpoint forwards it to connected clients. This is **not used by this story**: Redis pub/sub has no replay, so a client that connects after the message was published (a real risk — connecting right after the 202 response, before the socket handshake completes, while a fast pipeline run finishes) would wait forever with no fallback. Polling is the only mechanism with no failure mode, so it is the sole source of truth here. Revisit combining the two once `S2-12` (WebSocket `lesson_ready` push, coordinated with Dev 4) formally lands as part of the real pipeline.

## Acceptance Criteria

### AC-1 Real upload call
- `upload.service.ts` posts multipart `FormData` to `POST /api/content/lessons` via the shared `api` axios client (`src/lib/api.ts` — already attaches the Supabase Bearer token).
- Returns `{lesson_id, job_id, status}` on success (202).
- Client-side file size validation (max 50MB) before the request fires, matching the backend's `MAX_PDF_SIZE_BYTES` limit — reject with an inline error, no network call made.

### AC-2 Status polling replaces the mock WebSocket
- `UploadFlow.tsx` no longer imports `uploadGenerationService` / `MockWebSocketClient`.
- After a successful upload, poll `GET /api/content/lessons/{lesson_id}` immediately, then every ~5s thereafter (self-rescheduled after each poll settles, not a fixed-interval timer) — the immediate first check means a fast pipeline run is detected without waiting a full cycle.
- Map `status` to the existing UI states: `queued` / `running` → `processing`, `ready` → `completed`, `failed` → `error` (with the `error` field as the message).
- No percentage or per-stage text is shown — a static "Processing..." message only (matches `S1-09`'s "not percentage — just Processing..." pattern for the same reason: the backend has none to report).
- Polling stops on unmount and on reaching a terminal state (`ready`/`failed`).

### AC-3 Completion + error handling
- On `ready`: `router.push(`/lesson/${lessonId}`)` fires automatically, same as today.
- On `failed`: error card shows the backend's `error` field; "Try Again" resets to idle.
- On a network/5xx failure while polling: retry (does not immediately surface as a terminal error) — only a `failed` status or repeated poll failures beyond a small threshold should surface an error state.

### AC-4 Tests
- `upload.service.ts`: unit test asserting the multipart POST body/headers and the mapped response shape.
- `UploadFlow.tsx`: test covering queued→running→ready polling transition, queued→failed transition, and the file-size-rejection path — no reliance on the old mock socket.

### Review Findings

5-agent BMAD code review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) run 2026-07-13 against `sprint1/s1-8-upload-real-api` vs `main`.

- [x] [Review][Dismiss] POLL_INTERVAL_MS test-injectability — decided: leave the ~10-15s real-wait test as-is; not worth adding a config module purely for test speed.
- [x] [Review][Patch] AC-2 wording — update to reflect the immediate-first-poll behavior (already implemented and tested) instead of the literal "wait 5s first" reading.
- [x] [Review][Defer] AbortController-based request cancellation on unmount — deferred to a separate cross-service hardening story; reason: no other service in the codebase cancels in-flight requests either, and the harm today is one wasted network call (client-side effects are already suppressed via the `cancelled` flag), not a leak or correctness bug.
- [x] [Review][Patch] Multipart Content-Type header manually set to `'multipart/form-data'` with no boundary — breaks real request parsing (axios/browser must auto-generate the boundary; forcing the header suppresses that) [apps/web/src/services/upload.service.ts]
- [x] [Review][Patch] Polling race condition — `setInterval` fires the next tick even if the previous `getLessonStatus` call hasn't resolved yet; an out-of-order/stale response can overwrite an already-reached terminal state [apps/web/src/components/dashboard/upload/UploadFlow.tsx] — fixed by replacing `setInterval` with a self-rescheduling `setTimeout` that only schedules the next poll after the current one settles
- [x] [Review][Patch] No cap on total poll attempts/duration — if the backend returns `queued`/`running` forever (e.g. a dead worker), the UI polls indefinitely with no escape [apps/web/src/components/dashboard/upload/UploadFlow.tsx] — added `MAX_POLL_ATTEMPTS = 240` (~20 min at 5s/poll); not unit-tested (would require 240 mocked round-trips or reopening the test-injectability question already dismissed above)
- [x] [Review][Patch] Unexpected/unknown `status` values are silently treated as "still processing" with no logging or surfacing [apps/web/src/components/dashboard/upload/UploadFlow.tsx] — now `console.warn`s and still counts toward `MAX_POLL_ATTEMPTS`, so it can't hang forever
- [x] [Review][Patch] Non-string (array-shaped) `detail` from FastAPI's automatic 422 validation errors is not normalized before being used as `errorMessage` [apps/web/src/services/upload.service.ts] — added `extractErrorMessage()`, unit tested
- [x] [Review][Patch] 4xx poll failures (e.g. a malformed/missing `lesson_id` → 404) are retried identically to transient network errors, producing a misleading "lost connection" message after ~15s instead of failing fast [apps/web/src/components/dashboard/upload/UploadFlow.tsx] — now fails immediately on any 4xx poll response
- [x] [Review][Patch] Tautological test `MAX_UPLOAD_SIZE_BYTES is 50MB` only checks the constant against its own literal — provides no real coverage [apps/web/src/__tests__/services/upload.service.test.ts] — removed, replaced with `extractErrorMessage` unit tests
- [x] [Review][Patch] AC-4 gap — no test exercises the non-terminal `queued`/`running` → `processing` branch; all polling tests resolve a terminal status on the first call [apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx] — added, plus a fail-fast-on-4xx test
- [x] [Review][Dismiss] Deleting `lib/websocket/*` risks breaking unrelated consumers — verified safe: two independent review layers with project read access grepped the full `apps/web/src` tree and found zero remaining references; the real WS client (S1-07) lives separately at `lib/ws/lessonSocket.ts`
- [x] [Review][Dismiss] 50MB boundary uses strict `>` not `>=` — verified consistent with the backend's `MAX_PDF_SIZE_BYTES` check, which also uses strict `>`
- [x] [Review][Dismiss] `consecutiveFailures` reset before the `cancelled` check — cosmetic ordering issue, explicitly harmless (effect teardown makes it moot)
- [x] [Review][Dismiss] "12 new/updated tests, tsc clean" claim in the tracker lacks attached CI evidence — already verified true earlier in this session (323/323 tests passing, `tsc --noEmit` clean)
- [x] [Review][Dismiss] Two-phase status message ("Uploading..." then "Processing...") deviates from AC-2's literal "static message" wording — acceptable: improves UX, doesn't reintroduce fabricated percentage/stage data (the actual spec intent)

### Post-review finding (live end-to-end testing, 2026-07-13)

- [x] [Bug] `POST /api/content/lessons` 422'd against the real running backend — the shared axios instance (`apps/web/src/lib/api.ts`) set a hardcoded default `Content-Type: application/json` header on every request. Axios only auto-generates a multipart boundary when no `Content-Type` is already present, so this default silently overrode it: the browser sent `Content-Type: application/json` with a raw `FormData` body (no boundary), and FastAPI couldn't parse the `file` field at all. Fixed by removing the default — axios still auto-sets `application/json` for plain-object JSON bodies with no header present, so no other call site is affected. 327/327 web tests still pass.
