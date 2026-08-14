# Dev 2 backend-changes handoff — 2026-08-14

**From:** Dev 2 (Next.js, custom player, MediaPipe, quiz/teach-back UI, dashboard, WS client)
**To:** Dev 1 (infra / content pipeline / providers), Dev 3 (assessment / CES / analytics), Dev 4 (WebSocket / tutor FSM)

This is not a frontend handoff. `sprint3-master` is normally Dev 2 territory, but three
sprints of live-browser testing (the only way most of these bugs ever surfaced) forced
backend fixes on this branch that belong in your modules. This is the one PR that carries
all of it — `sprint3-master` → `main`, 96 files, 71 commits. This document is the backend
slice only: what changed outside `apps/web`, why it's yours, and one place where
`docs/DEFECT-REGISTER.md` itself is currently wrong.

---

## TL;DR

1. **A real, unmerged security fix in `rate_limit.py` (D75)** — the per-user rate-limit key
   silently falls back to IP-keying for any ES256/RS256-signed Supabase JWT, reopening the
   D52 bucket-sharing bug. Yours, Dev 1.
2. **A real, unmerged crash fix in `extract_subprocess.py` (D74)** — `book_ingest_job`
   `AttributeError`s on any real PDF with a bookmark/outline. Yours, Dev 1.
3. **`docs/DEFECT-REGISTER.md` currently claims both of the above are already on `main`.
   They are not.** Verified directly against `main`'s actual file content, not the register's
   prose. See §3.
4. **Session lifecycle: nothing ever wrote `sessions.ended_at`.** New `complete_session`
   service function + `POST /session/{id}/complete` endpoint. Yours, Dev 3 — it lives next to
   your `get_session_report`/CES code.
5. **CES was computed every window and never sent.** `tutor/service.py` now emits the
   `ces_update` WebSocket message the frontend has always been ready to receive. Yours, Dev 4.
6. **`intervention_complete` had no caller anywhere** — the tutor FSM got permanently stuck in
   `INTERVENING` after a session's first intervention, silently killing CES monitoring for the
   rest of the session. Fixed on the frontend (dismiss now sends the event); the backend
   handler already existed. Flagging because it's a cross-cutting FSM correctness bug, not a
   frontend-only fix. Yours, Dev 4.
7. **D55 — `lesson_package` cache was never populated for a returning student.** Read-through
   fallback added in `core/websocket.py`. Yours, Dev 4 (owns `core/websocket.py`) with an
   assist from Dev 1 (owns the `lessons.content` read path it falls back to).

---

## 1. `rate_limit.py` — D75, unmerged, security-relevant

### What happens

`_get_user_key` (`apps/api/app/core/rate_limit.py`) decodes the caller's JWT to build the
rate-limit bucket key. Its decode call was hardcoded to `algorithms=["HS256"]` only. Any
Supabase project migrated to asymmetric **"JWT Signing Keys"** (ES256/RS256) raises
`InvalidAlgorithmError` on every token, which the bare `except` swallows — the function then
falls through to `get_remote_address`, so **every authenticated user behind the same egress IP
shares one rate-limit bucket.** This is the exact D52 bug, reopened.

### Why it's yours

`dependencies.get_current_user` (`apps/api/app/dependencies.py:83-100`) already branches on
the token's `alg` header — HS256 against the shared secret, ES256/RS256 via JWKS. `rate_limit.py`
carries its own **second, independent** decode (can't import from a route-level dependency
without a circular import), and that second decode drifted out of sync when the JWKS branch
was added to the first one. The fix:

```python
unverified_header = pyjwt.get_unverified_header(token)
if unverified_header.get("alg") == "HS256":
    payload = pyjwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], ...)
else:
    jwks_client = _get_jwks_client(settings)  # reuses dependencies._get_jwks_client
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    payload = pyjwt.decode(token, signing_key.key, algorithms=["ES256", "RS256"], ...)
```

**This will drift a third time if `get_current_user`'s algorithm handling ever changes and
this second copy isn't updated by hand.** There's no way around the duplication without the
circular import; a comment on both sides pointing at each other is the best available guard.

### Why no test caught it

No test ever exercised an ES256-signed token through `_get_user_key` — every existing rate-limit
test used HS256 fixtures, because that's what a fresh Supabase project defaults to. Guard:
`tests/unit/test_rate_limit_key.py::test_an_es256_token_keys_the_bucket_by_user_not_ip` — a real
ES256 token signed with a generated EC key, JWKS client mocked at
`app.dependencies._get_jwks_client`.

---

## 2. `extract_subprocess.py` — D74, unmerged, crashes book ingestion

### What happens

`extract_text_only`'s TOC-parsing loop reads `item.page_index` and `item.title` as attributes
directly on the `pypdfium2.PdfBookmark` object returned by `get_toc()`. That class exposes
**neither attribute.** Every local fixture (including the eval corpus) has zero bookmarks, so
`get_toc()` always returned `[]` and this line never executed anywhere in CI. A real 2,000+-page
textbook (`d2l.pdf`) with an outline hit it on the first real-world upload:
`AttributeError: 'PdfBookmark' object has no attribute 'page_index'` — `book_ingest_job` fails,
"We couldn't read this PDF" in the UI, for a perfectly valid file.

### The fix

```python
dest = item.get_dest()
page_index = dest.get_index() if dest is not None else None
if page_index is None:
    continue  # bookmark with an unresolvable destination — normal, not an error
...
"title": (item.get_title() or "").strip(),
```

`.level` is a real attribute on `PdfBookmark` and was already correct — only the page-index and
title reads were wrong. `dest` (and its index) can legitimately be `None` for an unresolvable
destination; that's a normal bookmark shape, not an error path.

### Why no test caught it

Same root cause as §1: nothing in the local fixture set has an outline. Guard:
`tests/unit/test_extract_subprocess.py::TestExtractTextOnlyToc` — two tests using a
`_FakeBookmark`/`_FakeDest` shaped to the **real** pypdfium2 API (no `.page_index`/`.title`
attributes at all), so a regression back to attribute access fails with the same
`AttributeError` production raised, instead of silently passing the way a loose `MagicMock`
would — which is exactly how this shipped untested the first time.

---

## 3. The register says both of the above are already on `main`. They are not.

`docs/DEFECT-REGISTER.md` (current text, "Found by `sprint3-master`, merged into `main`
2026-08-13" section) reads:

> **~~D74~~ — CLOSED 2026-08-05 (fixed + guarded; renumbered to D74 on the 2026-08-13 merge
> into `main`** — was D63 on `sprint3-master`...)

I did not take that claim at face value. I ran, against `origin/main` at its current tip
(`6224751`, verified fresh — not a stale local copy):

```
git show origin/main:apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py
```

**`main`'s copy still has the original buggy code** — `item.page_index` and `item.title`,
unchanged. The same is true for the D75/rate-limit fix. Whatever merge the register is
describing either never actually landed the code change, or landed and was later reverted/lost.
Either way: **the register's own "closed, merged into main" claim is currently false**, and
until this PR merges, any real book with a bookmarked outline uploaded against `main` today
will still crash `book_ingest_job`.

I'm flagging this rather than silently "fixing" the register text, because Dev 1 owns both the
affected file and the register's Dev-1-facing entries — you may know something about how that
merge was supposed to have happened that I don't. Worth a direct look before this PR merges,
since after merge `main` and `sprint3-master` will agree on the code but the register's own
history of *how they got there* will still read as if it happened a sprint earlier than it did.

---

## 4. Session lifecycle: `sessions.ended_at` had zero writers

### What happens

Grepping the whole API for `ended_at` before this fix returns nothing but reads. Every
session, including ones a student genuinely finished start-to-end, reports
`duration_minutes: 0.0` and `completed_at: null` on `get_session_report` forever. No error,
no visible symptom besides a wrong number on the report page — exactly the "cheap wrong, not
expensive wrong" failure class CLAUDE.md calls out.

### What's new

- `complete_session()` in `apps/api/app/modules/assessment/service.py` — the only writer of
  `sessions.ended_at` in the codebase. **Idempotent by construction**: the UPDATE carries
  `.is_("ended_at", "null")`, so only the first call actually writes a row — a retry, a second
  tab, or React StrictMode double-fire affects 0 rows on every call after the first. This
  matters under CLAUDE.md's Scale & Load Q6 (concurrent check-then-act): a later, in-flight
  duplicate can never clobber a real completion timestamp with a later one.
- `POST /api/assessment/session/{session_id}/complete` in `router.py`, returning the new
  `SessionCompleted` schema. Same SEC-006 same-404-for-both-cases pattern as `create_session`
  right above it in the file.
- **The frontend must call this exactly once**, when the player reaches its terminal `ENDED`
  status. I've wired that call on the `apps/web` side already; flagging here because the
  contract itself (idempotent-by-write-filter, not by request dedup) is a backend decision you
  should know about if anything else ever calls this endpoint.

### Also riding along in `service.py` (Story 2-46 / S3-05, same file)

`get_session_report` gained two new optional response fields — `ces_timeline` and
`intervention_events` — computed from the same Redis `ces_history` read and a new bounded
`session_events` query (`.order("created_at", desc=True).limit(20)`, reversed back to
chronological order once read). Both degrade to `None`/empty on any failure rather than
failing the whole report. A `math.isfinite()` guard was added on the existing CES-history
float parse — a stray `"nan"`/`"inf"` string previously passed straight through `float()` and
would have serialized as a literal (invalid-JSON) `NaN`/`Infinity` token, breaking the
frontend's `JSON.parse` for the **entire** report, not just this field. Not something you
need to act on — just context for why `service.py`'s diff is larger than the one new function
suggests.

---

## 5. `tutor/service.py` — `ces_update` was computed and never sent

### What happens

`process_attention_signal` has always computed CES correctly every window. It only ever
emitted `attention_ack` (no score, by design — PRD §18) and `tutor_intervene` (only when an
intervention actually fires). **Nothing ever sent the frozen `ces_update` message**
(`packages/shared/types/ws.ts`), even though the frontend's `CESIndicator` /
`useLessonSocket.ts` has had complete, correct handling for it the whole time. The bug was
entirely server-side absence, not a frontend gap.

### The fix

```python
await manager.send(session_id, {
    "type": "ces_update",
    "payload": {"session_id": session_id, "ces": ces / 100.0, "window_index": window_index},
})
```

Two details worth knowing if you touch this again:
- `compute_ces` returns a 0–100 scale (PRD §11), but the frontend's `ces_update` handler
  validates `ces in [0,1]` and silently drops anything outside that range — the `/100.0` here
  is not cosmetic, it's the actual contract.
- `window_index` must be **monotonically increasing per session** (the frontend rejects an
  out-of-order frame), so it's a dedicated Redis counter (`INCR`), not history length —
  history is capped at `_CES_HISTORY_MAX` and would stop increasing once the cap is hit.
- Gated inside `state_raw == "TEACHING"` per CLAUDE.md §10 (CES monitoring only active in
  TEACHING).

---

## 6. `intervention_complete` had no caller anywhere

This one is fixed on both sides, but the backend handler pre-dates this PR (it was added for
D63 and was already correct) — the bug was that **nothing on the frontend ever called it**.
`TutorInterventionCard.tsx`'s dismiss (30s auto-dismiss and the manual ✕) only cleared local
React state; it never told the server. `route_from_intervening`'s only exit event was
undispatchable by anything, so **every session's first intervention permanently stuck the FSM
in `INTERVENING`** — and `useAttentionMonitor.ts`'s `flushWindow` gates on
`tutorStateRef.current === 'TEACHING'`, so CES monitoring silently died for the rest of the
session after the very first intervention. Flagging for Dev 4 because it's a tutor-FSM
correctness bug with a real symptom (CES freezing mid-session), not something that only
matters to the player UI.

---

## 7. D55 — `lesson_package` cache never populated for a returning student

### What happens

`pubsub.py` only writes `lesson_package:{session_id}` into Redis for sessions that were
`WAITING` on generation at publish time. A session started **after** the lesson is already
`ready` — a returning student, or literally any re-attempt of an existing lesson, the
overwhelmingly common real-world case — gets no cache entry at all. `_seed_learner_tier`
silently returned early, and `_segment_intervention_messages`
(`modules/tutor/service.py`) missed too: the Sprint 3 intervention hot path found nothing for
virtually every real session. Confirmed live (2026-08-12): a student's CES correctly dropped
into the "Low" band on sustained distraction, but no `tutor_intervene` message ever reached
the client, because this cache had simply never been populated for their session.

### The fix

`_fetch_and_cache_lesson_package` in `core/websocket.py` — a read-through fallback straight
from the durable `lessons.content` JSONB (the same column `content/router.py:get_lesson`
reads), populating the **same** Redis key with the **same** 24h TTL `pubsub.py` uses, so every
later read this session's lifetime hits Redis, not Supabase — matching CLAUDE.md's "process
once, reuse everywhere." Returns `None` (never raises) on any miss/failure; both callers
already treat that as "nothing to seed."

---

## What I need from you

Nothing blocking — everything above is already fixed, tested, and on `sprint3-master`, synced
clean against current `main` (zero conflicts, verified via a disposable worktree diff of the
full backend test run: same 63 pre-existing collection errors from missing `fpdf`/
`email-validator` packages in this environment, same failure count otherwise, +28 tests
passing from this branch's own new coverage).

**One thing worth a look before this PR merges:** §3 above. I'd rather you confirm or correct
my read of the register than have me edit Dev-1-owned register history based on my own
git-show output alone.
