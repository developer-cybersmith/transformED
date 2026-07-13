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
- After a successful upload, poll `GET /api/content/lessons/{lesson_id}` every 5s.
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
