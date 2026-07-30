# Backend ↔ Frontend wiring audit — route by route

**Date:** 2026-07-30 · **Run by:** Dev 1 · **Scope:** every API route on `main` vs its frontend caller
**Question asked:** *can a frontend developer, today, upload a PDF and receive a valid lesson package?*

---

## ⚠️ ID namespace warning — read this first

This report uses **`W-…`** ids (W for Wiring). They are **NOT** the ids in
`docs/DEFECT-REGISTER.md`.

The audit tooling originally emitted labels `G-1`, `C-1…C-9`, `D-1…D-30`, and those `D-n`
labels **collide numerically with register ids that mean something completely different** —
audit `D-28` is a `package_builder` subscript bug, while **register D28** is the
chapter/subsection hierarchy inversion. Everything here is therefore relabelled `W-*`.

Items promoted into the register carry their new register id in the table below. Everything
else lives only here, with an owner.

**The collision was not hypothetical.** While this audit was being written, the Sprint 2
completion audit independently claimed register **D29** and **D30** on `main`. Dev 1's entries
were renumbered **D31–D37** on discovery. Two of this report's findings (W-C3, W-C6) were also
**fixed by Dev 2 mid-audit** and are struck through rather than registered — a source-read audit
goes stale the moment someone commits.

---

## Method, and its limits

Six parallel audit lanes, each required to **read both ends of its seam** (RC-2 is
*"nothing in the process reads both ends of a seam"*). Every lane's findings were then handed
to an independent adversarial verifier instructed to **refute** them and to correct inflated
severity. A synthesis pass discarded everything marked REFUTED.

13 agents, 361 tool calls. Dev 1 then personally re-verified every load-bearing claim before
this document was written.

**What this audit cannot tell you:** **no lane ran the pipeline.** Every claim is source-read.
Nobody uploaded a PDF and observed a package. The strongest supportable statement is
*"the seams line up"*, not *"it works"*. See §8.

---

## 1. Verdict

**Yes — with one configuration caveat, and the caveat is Dev 1's.**

The upload → poll → package path is genuinely wired: not mocked, not half-built. It was read
on both ends by three independent lanes and confirmed at every step.

The caveat is `NEXT_PUBLIC_API_URL`. The code's built-in fallback is correct; **`.env.example`,
`ci.yml`, and the Dev 2 handoff all specify it without the `/api` segment**, which 404s every
route. A developer who configures nothing works. A developer who follows the documentation, or
who runs a CI-built bundle, is dead on arrival — which is the worse failure, because it punishes
the person who read the instructions.

Everything else that is broken breaks **lesson completion** (quiz, teach-back, report, CES),
not lesson generation. Those trace to a single defect: `sessions` has zero writers.

---

## 2. The generate path, step by step

| # | Step | Wired? | Backend | Frontend |
|---|---|---|---|---|
| 1 | Base URL resolution | ⚠️ correct in code, wrong in every doc/CI env | `main.py:166-172` — all routers under `/api`, no unprefixed alias | `lib/api.ts:4,7`; callers relative (`upload.service.ts:47`) |
| 2 | Auth on the upload | ✅ | `HTTPBearer` `dependencies.py:34`; `sub` read `:111` | `lib/api.ts:18-27` attaches `Bearer <supabase token>` on the same axios instance the upload uses |
| 3 | Multipart POST | ✅ | `content/router.py:254` `file: UploadFile`, `:255` `tier: Form`; 50 MB cap `:283,296-305` | `upload.service.ts:37,43`; no forced `Content-Type` (`api.ts:8-15`); 50 MB pre-check `:25` → `UploadFlow.tsx:64-69` |
| 4 | Tier vocabulary | ✅ | `schemas/lesson.py:39-40` `{T1,T2,T3}`, default `T2`; 422 otherwise `router.py:277-281` | `types/learnerMode.ts:13-17` deep/balanced/refresher → T1/T2/T3, applied `UploadFlow.tsx:157` |
| 5 | 202 response | ✅ | `router.py:245` `202`, `:423` `{lesson_id, job_id, status:"queued"}` | `UploadFlow.tsx:158-161` |
| 6 | Job enqueue → DB rows | ✅ | `router.py:335-374` inserts `books` + `lessons(generating)` + `lesson_jobs(pending)`; every literal legal under `initial_schema.sql:90-91,112-113` | — |
| 7 | **Status vocabulary** | ✅ | `lessons.status` CHECK = `generating\|ready\|failed`; `_STATUS_MAP` `router.py:121-129` → `running\|ready\|failed`, unknown → `queued` | identical union `upload.service.ts:10`; consumed `UploadFlow.tsx:112-127`, `useLesson.ts:30-33`, `lessonStatusPoll.ts:15-17` |
| 8 | Terminal status written | ✅ | success `content_pipeline.py:139` + `graph.py:4119-4125` (content+status+title atomically); failure `content_pipeline.py:285-289` | `useLesson.ts:28-33` stops on terminal; `PlayerLoader.tsx:73-82` gates on `ready && lesson` |
| 9 | Package + media signing | ✅ | `content: LessonPackage \| None` `router.py:64`, populated only when ready `:472-473`; `_resolve_lesson_content:200-236` rewrites `narration.audio_url` / `slide.image_url` to **8 h signed URLs** via `core/storage.py:83-107` | `useLesson.ts:52`; `AudioTimeline.tsx:411`, `SlideRenderer.tsx:37,72-76` consume opaque absolute URLs and sign nothing |
| 10 | Package shape | ✅ key-for-key | `schemas/lesson.py:202-226` + nested | `packages/shared/types/lesson.ts:95-111`; cross-validated `tests/unit/test_lesson_schema.py:99-108` |
| 11 | Failure surfacing | ✅ | `content_pipeline.py:271-274` writes `lesson_jobs.error`; `router.py:450-462` reads it back only when failed | `UploadFlow.tsx:121-124`, `PlayerLoader.tsx:74` |
| 12 | WS `lesson_ready` push | ❌ broken — **but not load-bearing** | publish `content_pipeline.py:147`; `core/pubsub.py:67,80` passes the **lesson_id** into `manager.send()` as if it were a session_id; registry keyed by the path-param session UUID `websocket.py:72,110` | `useLessonSocket.ts:50-55` **deliberately no-ops** `lesson_ready` — *"a client that may have missed it must fetch via REST rather than rely on this push"*. Readiness comes from polling. |

**Net: steps 2–11 correct on both ends. Step 1 is a docs/CI defect. Step 12 is dead code no frontend path depends on.**

---

## 3. Blockers to GENERATION — exactly one

### W-G1 → **register D31**. `NEXT_PUBLIC_API_URL` missing `/api`. Owner: Dev 1 (infra).

| Source | Value | |
|---|---|---|
| `apps/web/src/lib/api.ts:4` fallback | `http://localhost:8000/api` | ✅ |
| `.env.example:10` | `http://localhost:8000` | ❌ |
| `.github/workflows/ci.yml:126` | `http://localhost:8000` | ❌ |
| `docs/handoffs/dev2-handoff-2026-07-29.md:154` | `http://localhost:8000` | ❌ (Dev 1 wrote it) |
| `docs/dev2-assessment-api-handoff.md:56` | *with* `/api` | ✅ |
| `docs/stories/2-3-onboarding-assessment-flow.md:107` | *with* `/api` | ✅ |

**The repo contradicts itself in six places.**

Verified empirically: axios `combineURLs` joins `http://localhost:8000` + `content/lessons`
→ `http://localhost:8000/content/lessons`, and there is no unprefixed alias.

**Three verifiers reached three different `blocks_generation` verdicts on this one fact.**
Resolution, verified by Dev 1: Next loads env from its own project root, and **there is no
`apps/web/.env*` file** (`apps/web/.gitignore:34` ignores `.env*`) — so copying the root
template does not inject the bad value, and the correct fallback applies. But the developer
*must* hand-write `apps/web/.env.local` for `NEXT_PUBLIC_SUPABASE_*`, and the only template
and the only handoff both tell them the prefix-less value; and `ci.yml:126` inlines it into
every `next build`.

**Not a blocker on the accidental path; a blocker on the documented path and on any CI build.**

### Discarded as REFUTED — do not reintroduce

- **React StrictMode double-upload / $6 cost overrun.** The effect returns at
  `UploadFlow.tsx:92` before the POST on both mount invocations; StrictMode does not replay
  dependency-driven effect runs.
- **"403 vs 401 mismatch" on a missing auth header.** FastAPI 0.135+ `HTTPBearer` returns
  **401**. Read from installed source (`uv.lock:744-745`). The mismatch does not exist.
- **"Frontend is Next 14"** — it is **Next 16.2.9 / React 19.2.4**. See W-D33.

---

## 4. Blockers to COMPLETION — none of these stop generation

| id | Item | Owner | Register |
|---|---|---|---|
| W-C1 | `sessions` has zero writers → quiz/teach-back/report all 404 | Dev 3 | **D18** (existing) |
| W-C2 | `setSessionId` has **no caller**; the store mints `crypto.randomUUID()` (`player.machine.ts:146`) and nothing ever replaces it | Dev 2 | **D35** |
| ~~W-C3~~ | ~~`/reports/${sessionId}` link guaranteed to 404~~ — **FIXED BY DEV 2 during this audit** (`4657789`, `QuickActions.tsx`). | Dev 2 | closed |
| W-C4 | Bare `catch {}` in `QuizOverlay.tsx:66`, `TeachBackModal.tsx:43` — 404/403/409/502 indistinguishable | Dev 2 | — |
| W-C5 | WS `attention_signal` has no production sender | Dev 2 | — (Sprint 3) |
| ~~W-C6~~ | ~~`POST /api/analytics/events` has zero callers~~ — **FIXED BY DEV 2 during this audit** (`4657789`): `lib/analytics.ts:31` now posts to `/analytics/events`, wired into `Player.tsx` + `JargonHover.tsx`, with tests. Not registered. | Dev 2 | closed |
| W-C7 | `pubsub.py` sends a lesson_id where a session_id is expected; `lesson_waiters` does not exist | Dev 4 | **D34** |
| W-C8 | `lesson_package:` cache written by lesson_id, read by session_id | shared | — |
| W-C9 | `user_consents` has no writer or route — **DPDP blocker before any attention data** | Dev 1 / Dev 3 | — (CLAUDE.md §Security) |

**Onboarding is the only surface that branches on status codes correctly**
(`OnboardingFlow.tsx:115-128,184-202`) and is the model W-C4 should copy.

---

## 5. Contract drift — Pydantic ↔ `lesson.ts` ↔ JSON Schema

**PR #90's question answered first: it is a no-op.** All three files *already* agree
`LessonMetadata.tier` is optional — `schemas/lesson.py:58` (`= "T2"`),
`lesson.ts:21` (`tier?`), `lesson_package.schema.json:80` (has `default`, absent from
`required` at `:66-72`), with a test at `tests/unit/test_lesson_schema.py:217-230`.
**Close #90 as already-landed.**

| Field | Drift | Severity |
|---|---|---|
| `lesson_id`/`book_id`/`chapter_id` | Pydantic `UUID` vs TS `string`; `format:"uuid"` inert in draft-07. FE fixture uses `'lesson_mock_1'` — typechecks, would `ValidationError` | low |
| `created_at` | Pydantic plain `str` vs schema `format:"date-time"` — correct only by producer discipline (`graph.py:4083`) | low |
| `metadata.total_segments` | **Semantic:** `graph.py:4087` copies the *planner's* count while `:3908-3934` skip segments → can exceed `segments.length`. Rendered at `Player.tsx:139` | low |
| `segment.segment_index` | **Non-contiguous after a skip** (`graph.py:3906,4036-4038`). Player is *accidentally* immune (keys on array position); analytics/resume would break | low, latent |
| `avatar_*_url` | Declared consistently, **never populated** (`graph.py:4079-4111` has no avatar keys) **and never signed** (`router.py:202-236` touches only narration/slide). Only media fields typed `format:"uri"` while the convention is bare paths | low |
| `slide.fallback_image_url` | Required in all three, hardcoded `None` (`graph.py:1637`). `SlideRenderer.tsx:73-76` fallback branch unreachable | low |
| `narration.audio_url` | Degrades to `""` on signing failure (`router.py:225-234`) with no type-level signal | low |
| `quiz.correct_index` | **No contract in any of the three ties `correct_index < len(options)`** — enforced only by the producer | low |

**No CI guard ties `lesson.ts` to the JSON Schema.** Generating one from the other, or
ajv-validating the fixture in Vitest, would close the class.

---

## 6. Verified working — as valuable as the defects

- **The whole generate path, steps 2–11** (§2), read on both ends by three lanes.
- **Auth:** Supabase-direct only; `Bearer` attached on **every** request including multipart;
  `sub` is the user-id claim on both ends; HS256-vs-JWKS branch with `aud="authenticated"`;
  admin gate authenticates-then-authorizes; **no `fetch()` to the API anywhere** in
  `apps/web/src`, so there is no second unauthenticated transport.
- **Status vocabulary** mapped exactly at the boundary — two tables, two vocabularies, one
  correct translation.
- **Media signing** is server-side and complete for narration + slides; the frontend signs
  nothing and needs no signing credentials.
- **Assessment request/response shapes** field-for-field, including the 20 onboarding question
  ids character-for-character against `QUESTION_SUBDIMENSION_MAP` (drift there would silently
  zero a dimension), all 9 `DnaDimension` names, `ces_breakdown` exactly 5 keys, and
  `GET /user/dna`'s 6 fields against the dict actually returned so `LearnerDNA(**body)` cannot
  `KeyError`.
- **WebSocket frame shapes** — `lesson_ready`, `state_change`, `tutor_intervene`,
  `attention_signal` envelope round-trip, the 9-event client→server vocabulary, the
  `session_start` handshake, and a compile-time exhaustiveness guard over `ServerMessage`
  (`useLessonSocket.ts:61-66`). The client's `crypto.randomUUID()` **passes** the backend's
  lowercase-hex UUID guard — so the failure is routing, not a 4003 close.
- **`GET /lessons` paging** — `limit`/`offset` accepted (`router.py:484-485`), frontend sends
  `limit: 20`, `content` correctly absent from `_LIST_COLUMNS` (Story 1-6 AC-7 holds).
- **Dashboard** uses the **real** lesson list; only Dev 3's `learningPulse` is mocked and its
  failure is explicitly isolated (`dashboard.service.ts:25-31`).

---

## 7. Dev 1's own defects found by this audit

Three, all personally re-verified. **All three were found by an audit run after Dev 1 declared
its work finalized** — which is the honest headline.

| id | Defect | Register | Severity |
|---|---|---|---|
| W-G1 | `NEXT_PUBLIC_API_URL` missing `/api` in 3 Dev-1-owned sources | **D31** | high |
| W-D28 | `graph.py:3856` `item["data"]` **raw subscript** in `_group_by_segment_id`, whose docstring claims *"Same defensive-skip philosophy as `_index_by_segment_id`"*. A `data`-less entry `KeyError`s `package_builder_node` — the last node, after 100% of the lesson's spend. **Site 2 of a closed defect** (binding rule 6). | **D32** | medium |
| W-D31 | `graph.py:3742,711` default `chapter_id`/`book_id` to `""` against `UUID` fields — unsatisfiable, so a missing chunk output yields a bare `ValidationError` at the final node instead of a diagnostic naming the cause | **D33** | low |

Plus a **coverage gap** Dev 1 owns: `_LIST_COLUMNS`' PostgREST JSON-path selectors
(`subject:content->metadata->>subject`) have **never been executed against real Postgres**.
The sibling `completed_at` reference in that exact select list already caused one
outage-class `42703`, and per binding rule 4 a Supabase mock has no catalog and cannot raise
it. → **register D37**.

### Other Dev 1 low-severity items (this report is their record)

| id | Item |
|---|---|
| W-D1 | `total_segments` = planned, not packaged — set `len(segments_out)` + a `model_validator` |
| W-D2 | `segment_index` non-contiguous after a skip |
| W-D3 | `avatar_*_url` never populated **and** never signed |
| W-D4 | `fallback_image_url` always `None` |
| W-D9 | `completed_at` structurally always null (it is a `lesson_jobs` column) |
| W-D10 | `error` dead on the list path |
| W-D11 | `tier` writable but not readable — absent from `_LIST_COLUMNS` and `LessonStatusResponse` |
| W-D13 | `generation_progress` / `ces_update` declared in `ws.ts`, never emitted |
| W-D19 | `media/signed-url` has zero callers (documented-deferred, Story 2-31 AC-5) |
| W-D24 | 501 stubs with no callers: `/auth/signup`, `/auth/signin`, `/auth/onboarding/complete`, both `/tutor` REST routes. `/auth/me` implemented but unused. `tutor/router.py:54`'s docstring describes Redis reads the handler does not perform |
| W-D29b | `package_builder` should raise an explicit diagnostic rather than a bare `ValidationError` after full spend |
| W-D32 | None of the WS/contract limitations above carried a `D-nn` id despite being documented in comments — **binding rule 5**. This report + D31–D37 closes that. |

### Dev 2 / Dev 4 / shared items

`W-D5` `correct_index` unbounded · `W-D6` UUID + date-time typing · `W-D7` no CI guard tying
`lesson.ts` to the schema · `W-D8` `subject`/`estimated_duration_mins` served but never
consumed · `W-D12` no `offset` sent, library caps at 100, tab counts wrong · `W-D14`
`attention_ack` contract says `ces`, backend sends `status` · `W-D15` `pong`/flat-error absent
from `ws.ts` (FE shim) · `W-D16` `docs/ws-message-contract.md:90,89,104-115,248` factually
wrong — and it is the reference Dev 2's shim was written against · `W-D17` 429 unhandled on
upload (slowapi emits `{"error":…}` not `{"detail":…}`; `Retry-After` present) · `W-D18` slide
images unrecoverable after signing expiry (`SlideRenderer.tsx:17-18` seeds state, no `key`, no
resync) · `W-D20` report page collapses 401/404/500 · `W-D21` onboarding never sends
`response_time_ms` · `W-D22` unanswered onboarding question submits as option A · `W-D23`
`LessonRecord` missing `tier`/`book_id`, zero call sites · `W-D25` `middleware.ts:38-44` reads
`learner_dna` from the edge runtime — cross-module direct DB access from the frontend · `W-D26`
two parallel real callers of `GET /lessons/{id}` · `W-D27` `reports.service.ts` is a 100% mock
decoy with zero consumers · `W-D33` **stack drift: `apps/web` is Next 16.2.9 / React 19.2.4
while CLAUDE.md locks "Next.js 14"** — unowned, and it may invalidate other Next-14-shaped
assumptions (→ register **D36**).

**Deliberate and documented, not defects:** `lessonService.getLesson`/`updateProgress` on mocks
(no backend route exists; `lesson.service.ts:5-6` says so); the Settings surface on mocks
(`mocks/data/users.ts:22-26` explicitly disclaims consent authority); no admin UI (no dev owns
one per §21); `media/signed-url` dormancy.

---

## 8. What this audit did NOT cover

Stated plainly, because an audit that hides its gaps is worse than no audit.

- **No lane ran the pipeline.** Every claim is source-read. Nobody uploaded a PDF and observed
  a package. *"The seams line up"* ≠ *"it works"*.
- **PostgREST JSON-path selectors never executed against real Postgres** (→ D37).
- **slowapi's 429 body was not read** (package not installed). W-D17 holds anyway — the
  frontend has no 429 branch at all.
- **PR #119 was not read.** Its absence from `main` was confirmed; its contents taken as given.
- **`POST /lessons` 409 ARQ-dedup path** — reachable only on a `lesson_id` collision; its
  frontend presentation was not traced.
- **RLS policies were not read.** Several findings (W-D25 especially) are *"correct only while
  RLS covers it"* — that premise is unverified.
- **Revision-mode / Bunny Stream video** — no code exists.
- **`media/signed-url` IDOR** was read (`media/router.py:107-117`) but never exercised.
- **Multi-tab fan-out:** `ConnectionManager` allows multiple sockets per session
  (`websocket.py:63,72`), so `attention_ack`/`tutor_intervene` broadcast to every tab with no
  dedupe. Consequences untested.
- **`lesson_ready` has no replay on reconnect** — unregistered, unaudited.
- **Nothing load-tested or cost-verified** against the $3.00 ceiling. The cost meter landed in
  `38513e3`; its output has never been examined because the live eval has never run.
- **Sprint 3 surfaces** (MediaPipe, full 7-state tutor, CES calibration) audited only for the
  existence of their seams.

---

## The one-line answer

**A frontend developer can generate a lesson package today — provided they do not follow the
setup documentation.** Fixing D31 makes that sentence unconditional.
