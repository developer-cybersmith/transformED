---
baseline_commit: d94d5b5
---
# Story 1.14: Generate a lesson from a chapter (book-scale Phase 6)

Status: review

**Branch:** `book-scale/phase-6-endpoints` (from `book-scale/integration`)
**Phase:** 6 of 9 — `docs/book-scale-phase-tracker.md` § "Phase 6 — Endpoints"
**Predecessors:** 1-9 (migration) · 1-10 (detection at upload) · 1-11 (book/chapter reads) ·
1-12 (page-scoped extraction) · 1-13 (chapter-scoped generation)

## Story

As a **student who has uploaded a textbook**,
I want **to pick one chapter and generate a lesson from it at a difficulty tier I choose**,
so that **a 1,151-page book becomes 27 lessons I can actually study, instead of one lesson
built from 4 % of it**.

### Why this story exists now

Phases 3–5 took the system apart and left it in a deliberately broken state:

- `POST /content/lessons` is ingestion-only. It returns `{book_id}` and **422s if `tier` is
  supplied** (`router.py:415-423`).
- `lessons.chapter_id` is read by `content_pipeline_job:61` and threaded all the way to the PDF
  subprocess as `page_start`/`page_end` — **and nothing writes it** (`content_pipeline.py:71-82`
  says so verbatim: "Phase 6's generate endpoint is what sets the column at lesson creation").
- Therefore **there is no way to generate a lesson at all** right now. D41.

This story is the single write that reconnects the two halves. One `lessons` INSERT carrying
`chapter_id` lights up the entire Phase 4 + Phase 5 read path, which is already built, merged
and tested.

---

## The three things most likely to go wrong

Read these before the ACs. Each one passes every mock-based test and fails against a real
database.

**1. Writing `chapters.lesson_id` is destructive, not merely wrong.**
That FK is `ON DELETE CASCADE` (`20260611000000_initial_schema.sql:132`, preserved verbatim by
`20260803000000:52-58`), and `chunks.chapter_id` cascades from the chapter (`:147`). So the
"obvious" implementation — insert the lesson, point the chapter at it, roll back the lesson when
the enqueue fails — **deletes the chapter and every chunk and embedding under it**. A whole
book's ingestion, destroyed by one failed generation. A Supabase mock has no FK engine and
cannot show you this. **Do not write, backfill, or read that column.** AC14.

**2. The wrong PostgREST FK qualifier returns HTTP 200.**
Two FKs exist between `lessons` and `chapters`, so a bare embed is `300 / PGRST201`. But
`lessons!chapters_lesson_id_fkey` — the plausible-looking wrong one — is perfectly legal, resolves
through the dead column, and returns `has_lesson: false` **forever**. Green tests, dead feature.
AC16.

**3. The $3.00 cost ceiling does not protect you from a 1,151-page chapter.**
`structure_max_sections=15` (`config.py:301`) × `_get_section_body(max_chars=6000)`
(`graph.py:1942, 1952-1960`) means **~90,000 characters is the entire LLM-visible window
regardless of page count**. A whole-book chapter therefore produces a *cheap wrong* lesson, not
an expensive one — it never trips the ceiling, and today it emits only a `logger.warning`. Any AC
phrased as "the cost ceiling protects us" would pass review and ship the original bug. AC11.

---

## Acceptance Criteria

Legend: **[PG]** needs real Postgres · **[PGRST]** needs real PostgREST · unmarked runs in
default CI. **No AC in this story spends real money** — see AC20.

### A. The endpoint

**AC1 — The route is registered, and the 422 that points at it cannot drift.**
`POST /books/{book_id}/chapters/{chapter_id}/lessons` on the content router (mounted path:
`/api/content/books/{book_id}/chapters/{chapter_id}/lessons`; `router.py:48` + `main.py:167`).
`upload_lesson`'s 422 detail already names this path in prose (`router.py:415-423`). Extract it
into a module constant consumed by **both** the route decorator and that message.
*Test:* build the real app, read `app.openapi()`, assert the route exists and that the 422 body
contains the path **read off the registered route**, not a retyped literal. This also closes the
stale-uvicorn blind spot — nothing in the Python suite currently notices a content route that
fails to register (`tests/test_openapi_spec.py:50-52` builds an assessment-only app).

**AC2 — `tier` is a body field validated from the single source of truth.**
`GenerateLessonRequest` in `app/modules/content/schemas.py`, `tier: str = DEFAULT_TIER`, validated
against `VALID_TIERS` — both imported from `app.schemas.lesson` (`:39-40`). **No second tier
literal anywhere in `router.py`** — `graph.py:61-62` imports the same two, and a third copy is
the DRY violation a previous Blind Hunter review already rejected once. `"T4"` → 422 **before any
DB call**; omitted → `DEFAULT_TIER`.
*Test:* three cases + a source scan for a duplicate tier set.

**AC3 — A new response model, not an extension of the existing ones.**
`LessonGenerationResponse{lesson_id, chapter_id, tier, status, job_id: str | None,
truncation_expected: bool}`. **202** on create, **200** when an existing lesson is returned
(AC9). `job_id` is `None` on the 200 path — the original ARQ id is not persisted anywhere and
inventing one would be a lie.
`BookResponse` must remain **byte-for-byte unchanged**; its two exact-key tests
(`test_book_endpoints.py:149-156, 235-242`) must pass untouched.

### B. Authorization — the most likely IDOR in the codebase

The Supabase client is **service-role** (`core/db.py:23-46`) and **bypasses RLS**. `chapters` has
no `user_id` column (`20260611000000:128-137`). Application-layer filtering is the only control.

**AC4 — Fixed gate order. Any size or existence answer emitted before ownership is proven turns
this endpoint into an enumeration oracle.**
1. `_validated_book_id` → `_validated_chapter_id` (new, symmetric with `router.py:283-296`) —
   both **before any DB call**
2. `_fetch_owned_book(...)` — filters on `book_id` **and** `user_id`, then re-checks `user_id` on
   the returned row
3. chapter fetch `.eq("chapter_id", …).eq("book_id", …).maybe_single()` + post-fetch
   `str(row["book_id"]) != book_id → 404`
4. `books.status != 'ready'` → **409** (nothing to generate from yet)
5. idempotency check (AC9)
6. page-span gate (AC11)

The post-fetch re-checks are not redundant — they survive a future refactor that drops a `.eq()`.
`extract_node` does re-verify book/chapter agreement (`graph.py:316-321`), but the API **must not
lean on it**: by then the `lessons` row, the `lesson_jobs` row and the ARQ job all exist, so the
caller gets a `202` and a `failed` lesson instead of a `404`, and a worker slot is burnt.

**AC5 — No existence leak.**
- Chapter in **another user's** book → `404 "Book not found"`, byte-identical to a book that does
  not exist, with **exactly one** `supabase.table()` call.
- Chapter in a **different book of the caller's** → `404 "Chapter not found"`.
- Neither 404 body contains `filename`, `title`, `page_start`, `page_end`, `chapter_index`, or a
  real `book_id`.
- Malformed UUID in **either** segment → 404, and **never reaches the database** (assert on the
  mock's call count).
- **No timing padding.** The 1-query/2-query difference is only reachable after the caller has
  proven ownership of the book — it distinguishes states they can already enumerate for free via
  `GET /books/{id}/chapters`. Say this in the docstring so nobody "fixes" it later.
*Test:* extend the patterns at `test_book_endpoints.py:265-330`.

### C. Creating the work

**AC6 — The `lessons` INSERT carries exactly `{user_id, book_id, chapter_id, tier,
status:'generating', title, source_file_path}` — every one a real column.**
`lessons` has **no `error`, no `completed_at`, no `session_id`, no `subject`** column
(`router.py:103-111` and `content_pipeline.py:75-86` both document that trap). Naming one makes
PostgREST reject the whole statement with `42703` — the D9 outage shape. `status='queued'` or
`tier='T4'` insert fine into a mock and raise `23514` in Postgres.
*Test:* payload assertion **paired with AC7's migration-parsing guard** — a payload assertion
alone asserts only on a mock it built (binding rule 2).

**AC7 — One helper owns the storage key layout.**
`books` has **no path column** — the table is created once
(`20260625000000_chunks_inline_embedding.sql:28-45`) and the only later `ALTER` is
`ENABLE ROW LEVEL SECURITY` (`:141`). Add
`_source_pdf_path(user_id, book_id, filename) -> str`, used by **both** `upload_lesson` (replacing
the inline f-string at `router.py:479`) and generate. `user_id` and `filename` come from the
**fetched books row**, never from the JWT.
Reconstruction is byte-exact because `router.py:454-456` computes `safe_filename` once and `:467`
stores that same value; the pre-Phase-3 formula was identical (`main:356`), so legacy rows
reconstruct too.
*Test:* byte-exactness across `"my book (1).pdf"`, `"../etc/passwd"`, `"ünïcode.pdf"`,
`"a/b/c.pdf"` — construct via upload, read `books.filename` back, assert the helper reproduces the
stored key. **Not** by comparing two f-strings. Plus a source scan asserting the layout appears
exactly once, in the style of `test_node_return_shape.py`.

**AC8 — `lesson_jobs` row, ARQ enqueue, and the false 409 removed.**
Insert `lesson_jobs{lesson_id, status:'pending'}`, then
`enqueue_job("content_pipeline_job", lesson_id, _job_id=f"pipeline:{lesson_id}")`.
Keep the key as-is: it is the retry-safety key the worker and CLAUDE.md's `thread_id` rule already
reference. A chapter-keyed variant would collide across tiers and block a legitimate regeneration
after failure.
`lesson_id` is minted by the INSERT immediately above, so `job is None` is unreachable by
construction and can no longer mean "already queued". Keep the check (never assume) but raise
`RuntimeError` inside the `try` → generic 500. **Delete** the old detail string "A lesson pipeline
job is already queued for this ID" — it is now a false statement to the client.

**AC9 — Idempotent under the retry a `202` invites.**
Pre-check `lessons.select("lesson_id,status,tier").eq("chapter_id", …).eq("tier", …)
.eq("user_id", …)`:
- match in `generating` or `ready` → return it, **200**, no new row, **no enqueue** (assert
  `enqueue_job.await_count == 0`)
- only `failed` matches → generate fresh, **202**
- different tier → always a new lesson; the schema permits it deliberately
  (`lessons_chapter_id_idx` is **non-unique**, `20260803000000:77`)

**State plainly in the docstring that this is best-effort and TOCTOU-racy** — two concurrent
requests can both see nothing and both insert. There is no DB uniqueness to lean on (verified:
no UNIQUE exists on `chapters.lesson_id`, `lessons.chapter_id`, or `(chapter_id, tier)` in any of
the ten migrations). The durable fix is a partial unique index
`(chapter_id, tier) WHERE status <> 'failed'`, which is a **frozen-contract migration** and
therefore out of scope — register it (AC22). Explicit regeneration (`?force=true`) is also out of
scope: register, don't build.

**AC10 — Rollback touches only what this request created. [PG]**
In order, each under `contextlib.suppress(Exception)`: `lesson_jobs` (child) → `lessons` (parent).
**Never** delete the `books` row, **never** `storage.remove(...)` the PDF, **never** touch the
`chapters` row. The pre-Phase-3 code did all three — correctly, because upload and generation were
one call.
*Test:* a **real-Postgres** integration test asserting that after a forced rollback the `books`
row, the storage object, the `chapters` row **and its `chunks`** all still exist. This AC exists
precisely because of what CASCADE would have done; a Supabase mock has no FK engine and would pass
either way.

### D. Gates that stop a book-scale generation from being catastrophic

**AC11 — Page-span gate with a warn band.**
New `max_chapter_pages: int = 200` (env `MAX_CHAPTER_PAGES`) in `config.py`. Span is
`page_end - page_start + 1`, computed from the **DB row**, not from client input.
- span > cap → **422** `{code:"chapter_too_large", page_span, max_page_span, boundary_confidence}`,
  no lesson row, no enqueue
- span > `_TRUNCATION_WARN_PAGES` (40) → **accepted**, and the 202 body carries
  `truncation_expected: true`

*Why two numbers, and why 200 rather than 80.* They gate different failures.
The **quality** cliff is at ~40 pages: 90,000 LLM-visible characters ÷ the measured
2,296–2,816 chars/page (tracker Phase 1) is 32–39 pages. Above that the lesson is genuinely built
from part of the chapter, and the client deserves to be told.
The **catastrophe** gate must sit above every real chapter, and the largest real chapter measured
across the 8-book Phase 1 corpus is **D2L Appendix A at 138 pages** (medians 10–44). A cap of 80
would refuse a legitimate chapter and break the project's one success criterion — *a 1,000-page
book runs to completion*. 200 clears 138 with headroom and still refuses an R5 whole-document
chapter (1,151 / 1,671 pages), which is the exact failure this effort exists to fix.
*Test:* parametrised over 35 / 40 / 41 / 138 / 200 / 201 / 1151.
*Rejected:* gating at ingest (destroys a browsable book over one bad chapter); gating on
`boundary_confidence == 'fallback'` (a legitimate 60-page single-chapter PDF is also rung 5).

**AC12 — Per-user concurrency cap.**
`max_concurrent_generations_per_user: int = 3`. Count `lessons` with `status='generating'` for this
`user_id`; at or above → **429** with `Retry-After`. A rate limit is *not* a cost control — this is
the one that actually bounds spend.

**AC13 — Rate limit sized for an endpoint that spends money.**
`@limiter.limit("3/minute;20/hour", key_func=_get_user_key)`. 5/min is the *upload* number; here it
would authorise roughly $900/hour of spend. The handler **must** declare a parameter literally
named `request: Request` or slowapi raises at call time (`upload_lesson:375-378` is the pattern) —
assert the signature, not just the behaviour. Docstring records that `storage_uri` defaults to
`memory://` (`core/rate_limit.py:51`), so the cap multiplies by replica count. Registered, not
fixed here.

### E. The reads learn the truth

**AC14 — `chapters.lesson_id` is dead and stays dead.**
Do not write it, do not backfill it, do not read it. Reasons, in order of severity: the CASCADE
hazard above; it is scalar and cannot express one chapter with lessons at three tiers; and its only
writer was deleted in Story 1-13. `book_ingest_job` writes `"lesson_id": None` explicitly
(`book_ingest.py:95`) and **`test_book_ingest_job.py:113` must keep passing unchanged** — a Phase 6
change that breaks it is wrong.
*Guard:* widen the source scan at `test_pipeline_writes_no_books.py:28` from `PIPELINE_DIR` to
`app/modules/content/` **for `chapters` only**. `books` stays pipeline-scoped and `lessons` writes
must remain allowed, or the endpoint cannot exist.

**AC15 — `GET /books/{id}/chapters` re-sources the link from `lessons`.**
`_CHAPTER_COLUMNS` becomes
`chapter_id,chapter_index,title,page_start,page_end,boundary_confidence,lessons!lessons_chapter_id_fkey(lesson_id,status,tier,created_at)`
— the bare `lesson_id` is **dropped**, not kept as a "harmless fallback".
`ChapterResponse` gains `lesson_count: int` and
`latest_lesson: {lesson_id, status, tier, created_at} | None`. `lesson_id` and `has_lesson` stay
(Dev 2's committed contract has them) but change meaning: newest lesson, and "at least one lesson
in any state".
`_row_to_chapter_response` **unwraps a list defensively** — `[]` → `(None, False, 0)`, mirroring
`_embedded_count` (`router.py:235-252`). Zero-lesson chapters are the normal state; a bare `[0]`
index 500s the entire chapter list for a book mid-ingestion.
Delete the now-false claims at `router.py:268-269` ("already correct the moment Phase 6 starts
writing `chapters.lesson_id`"), `router.py:685`, and `schemas.py:38-41`.
*Why `latest_lesson` carries status:* `has_lesson=true` on a chapter whose only lesson is `failed`
renders Dev 2 a "Watch" button that 404s the player.
*Test:* a chapter with two lessons at different tiers returns `lesson_count == 2` and
`latest_lesson` = the newer by `created_at` — the case a scalar column could never express.

**AC16 — The disambiguating FK names are used, and both are proven to exist. [PG][PGRST]**
Two FKs exist between these tables:
- `chapters_lesson_id_fkey` — `chapters.lesson_id → lessons` (`20260611000000:132`)
- `lessons_chapter_id_fkey` — `lessons.chapter_id → chapters` (`20260803000000:72-73`)

**Both** Phase 6 embeds name `lessons_chapter_id_fkey` — the same constraint from opposite sides,
with different cardinality and different JSON shape. That is not a typo:

| Direction | Select fragment | Shape |
|---|---|---|
| chapters → lessons | `lessons!lessons_chapter_id_fkey(...)` | to-**many**, JSON **array**, `[]` when empty |
| lessons → chapters | `chapter:chapters!lessons_chapter_id_fkey(...)` | to-**one**, JSON **object**, `null` when unset |

*Tests, three of them:*
1. The **unqualified** embed `/chapters?select=chapter_id,lessons(lesson_id)` returns **300 with
   `PGRST201`** — proving the qualifier is load-bearing and not ceremony. Mirror
   `test_a_bogus_column_really_does_raise_42703:120-125`. Note `PGRST201` is a **300**, so a naive
   `status_code >= 400` check reads it as success. **[PGRST]**
2. `pg_constraint` contains both names between these two tables — a premise assertion in
   `test_migration_chapters_book_scoped.py` (binding rule 3). **[PG]**
3. The new constants execute against real PostgREST — add them to the parametrize list and table
   map at `test_book_select_lists_against_postgrest.py:131-149`, which already imports the router's
   constants **by name** (`:92-109`) rather than regexing them. This is the guard that closed D37.
   **[PGRST]**

**AC17 — `GET /lessons` learns its chapter.**
`_LIST_COLUMNS` gains `chapter_id` and
`chapter:chapters!lessons_chapter_id_fkey(chapter_id,title,chapter_index)`.
`LessonStatusResponse` gains `chapter_id`, `chapter_title`, `chapter_index` — all nullable; legacy
lessons have `chapter_id IS NULL` and the embed returns `null` for them.

**AC18 — Embed *shape* is proven, not just embed validity. [PG][PGRST]**
The harness queries as the **anon** role with RLS on, so every data query returns `[]` — it proves
the select *parses* and never that AC16's array/object shapes hold.
(`test_the_chapters_count_embed_resolves_unambiguously:163` already guards with `if rows:` for
exactly this reason.) Mint an HS256 bearer with `{"role":"service_role"}` against the container's
`PGRST_JWT_SECRET`, seed 1 book / 1 chapter / 2 lessons, and assert: the chapters-side embed is a
**list of two**; the lessons-side is an **object**; an empty relation yields `(None, False, 0)`
without raising. Clean up the seeded rows.

### F. Not weakening what already guards us

**AC19 — Existing guards are updated deliberately, never loosened.**
- `test_content_router.py:996-1007` — the hardcoded `real_columns` set for `lessons` omits
  `chapter_id`, which **is** a real column (`20260803000000:73`). Add it. Do **not** loosen the
  membership loop.
- `test_book_endpoints.py:485-505` — **both column guards split the select list on `,`**, so adding
  an embed makes them fail on *syntax*, which will tempt someone to delete them. **Teach them to
  parse embeds** (outer names against the base table, inner names against the embedded table).
  Deleting either is a review rejection.
- `test_book_endpoints.py:346-355` — the `ChapterResponse` exact-key assertion gains the new keys.
  Still `==`, never `>=`.
- `test_content_router.py:806-824` — the tier-422 test keeps passing and additionally cross-checks
  the path constant (AC1).
- `test_pipeline_writes_no_books.py` — widened per AC14 for `chapters` only.

**AC20 — End-to-end against the real project, without paying for generation.**
Live Supabase, the real 1,151-page book:
1. Upload → poll `GET /books/{id}` to `ready`, `chapter_count` non-zero
2. `GET /books/{id}/chapters` → 27 chapters, all `has_lesson=false`, `lesson_count=0`
3. `POST .../chapters/{id}/lessons` `tier=T1` → **202**; the row has the right `chapter_id`, `tier`,
   `book_id`, and a `source_file_path` that **downloads**
4. Re-`GET` chapters → that chapter reports `has_lesson=true`, `lesson_count=1`,
   `latest_lesson.status="generating"`, and **no other chapter changed**
5. Same chapter + tier again → **200**, same `lesson_id`, no second row
6. Same chapter at `T3` → **202**, different `lesson_id`, `lesson_count=2`
7. Another user's book → 404 · a chapter of a different book → 404 · `tier="T9"` → 422 ·
   a >200-page chapter → 422
8. Start the worker; confirm `extract_node` resolves the chapter's real page range and spawns the
   subprocess with those bounds — **then stop.**

Step 8 stops deliberately. Running the eleven nodes to completion spends real money; that is Story
1-13 AC10, folded into the Phase 7 acceptance run by decision **D43**. Record observed numbers in
the tracker.

**AC21 — Repo-wide gates (binding rule 1 — never scoped to touched files).**
`pytest tests/unit tests/integration` (baseline on this branch: **968 passed, 10 skipped**),
`ruff check .` clean repo-wide, `mypy app` no worse than the 24 errors in 3 files `main` carries.

**AC22 — Every known gap gets a register ID (binding rule 5).**
Add to `docs/DEFECT-REGISTER.md`:
- **`chapters.lesson_id` is a dead column with a live CASCADE.** Trigger: drop it once legacy rows
  are purged — a frozen-contract migration.
- **The `(chapter_id, tier)` idempotency check is TOCTOU-racy.** Fix is a partial unique index;
  frozen-contract migration, out of scope here.
- **The page gate stops catastrophe, not truncation.** 90,000 chars ≈ 32–39 pages; a 138-page
  chapter passes AC11 and is still built from ~28 % of itself, with only a `logger.warning`
  (`graph.py:1953-1959`). Trigger: Phase 7's "no truncation warning" assertion firing.
- **A rung-5 whole-document book cannot be generated from at all** — its single chapter exceeds
  AC11 by design. 0 of 8 corpus books reached rung 5. Trigger: the first one that does.
- **`max_daily_spend_per_user_usd` (`config.py:150`) has zero call sites** — dead config that reads
  like a control.
- **`RATE_LIMIT_STORAGE_URL` unset ⇒ `memory://`** ⇒ the limit is per-replica.
- **300-DPI page rendering and image upload have no count cap** (`extract_subprocess.py:411,473`;
  `graph.py:423,471-479`) — outside `cost_tracker`'s view entirely.
- **Widen D34.** The wrong id at `pubsub.py:67` does not merely lose the WebSocket push; it writes
  the package cache under a lesson id that two real consumers read by **session** id —
  `_seed_learner_tier` (`websocket.py:279`) and `_segment_intervention_messages`
  (`tutor/service.py:253`). "Dead code" is true of the push only. Also note
  `test_lesson_ready_integration.py:194-211` uses **one string for both ids** and asserts against a
  MagicMock — it encodes D34 as its premise and cannot fail. Fix is **Phase 6.5, explicitly out of
  scope for this story**.

**AC23 — The frozen read contract is re-captured in the same commit.**
`docs/contracts/book-api.v1.json` → 1.1.0: add the POST entry; delete the two now-false annotations
(`lesson_id` "ALWAYS null until Phase 6", `has_lesson` "ALWAYS false until Phase 6"); add
`lesson_count`/`latest_lesson`; re-capture `real_example` from a **real** run showing one chapter
with a non-null lesson. **No `GET` response shape regresses**, so Track W's W1/W2 stay unblocked.
D41's enforcement column names this file as Dev 2's W0 contract-CI input — a stale contract there
is a green CI job over a dead product.

**AC24 — Decide, in writing, whether CI runs `-m postgres`.**
Seven ACs above are marked [PG]/[PGRST]. The containers are **hand-started from prose in a fixture
docstring** (`test_book_select_lists_against_postgrest.py:68-73`); there is no compose file and no
CI step. A harness that skips in CI guards nothing — that is `FIXED-UNGUARDED` under binding rule 7.
Either add the CI service containers, or record the decision to keep it a local pre-merge gate with
a named owner and a trigger. Do not leave it implicit. The suite must keep skipping **visibly**
(`:62-78`), and **a skip does not satisfy an AC**.

---

## Tasks / Subtasks

- [x] **T1 — Path constant, request/response models** (AC1, AC2, AC3)
- [x] **T2 — Authorization + gate order** (AC4, AC5)
- [x] **T3 — Create the work** (AC6, AC7, AC8, AC9, AC10)
  - [x] `_source_pdf_path` helper; `upload_lesson` refactored onto it
  - [x] `lessons` INSERT → `lesson_jobs` INSERT → enqueue; `job is None` → 500
  - [x] idempotent 200 path with `enqueue_job.await_count == 0`
  - [x] **[PG]** rollback test: `books`, storage object, `chapters` row and its `chunks` all survive
- [x] **T4 — Gates** (AC11, AC12, AC13)
- [x] **T5 — Reads learn the truth** (AC14, AC15, AC16, AC17, AC18)
  - [x] widen the `chapters`-write scan to `app/modules/content/`
  - [x] `_CHAPTER_COLUMNS` + `_LIST_COLUMNS` embeds; defensive list unwrap
  - [x] **[PGRST]** unqualified-embed-is-300 test · **[PG]** FK-name premise · service_role shape test
- [x] **T6 — Existing guards + contract** (AC19, AC23)
  - [x] teach both column guards to parse embeds — do not delete them
- [x] **T7 — Register entries + the CI decision** (AC22, AC24)
- [x] **T8 — End-to-end run + tracker** (AC20, AC21)

---

## Dev Notes

### The one write that reconnects everything

`content_pipeline_job:61` already selects `user_id, source_file_path, book_id, chapter_id, tier` and
passes them to `run_pipeline` (`:110-118`), which seeds `PipelineState` (`graph.py:4691-4742`).
`extract_node` (`graph.py:214-345`) **raises** if `chapter_id` or `book_id` is empty (`:282-293`) —
deliberately, with no whole-document fallback — looks the chapter up, verifies its `book_id` matches
the lesson's (`:316-321`), requires non-null `page_start`/`page_end` (`:323-331`), and passes them to
the isolated subprocess as argv 4/5 (`:373-376`, 0-based inclusive).

All of that is built, merged and tested. **This story writes one column.**

A missing `source_file_path` does not fail here — the insert succeeds and the failure surfaces
minutes later inside `extract_node` (`graph.py:270-271`) after a 202, looking like a pipeline bug.
That is why AC7 has a byte-exactness test rather than a smoke test.

### What must not regress

- The subprocess isolation boundary (CLAUDE.md §18) — this story adds no PDF parsing.
- `book_ingest_job` remains the **sole** writer of `books` and `chapters`.
- No LLM call in the router. No hardcoded model string. ARQ only.
- `lesson_waiters:{lesson_id}` **does not exist** — the comments at `content_pipeline.py:102,168`
  describe a set that was never built. Do not code against it.

### Testing standards

- Markers `unit` / `integration` / `postgres`, `--strict-markers` (`apps/api/pyproject.toml:128`).
- Binding rule 2: no test may assert only on a mock it constructed. The PostgREST harness (AC16,
  AC18) and the migration-replay suite (AC16.2, AC10) are the real-dependency tests that unit-level
  Supabase doubles point at with `# MOCK-CONTRACT:`.
- Container bring-up is in the fixture docstring at
  `test_book_select_lists_against_postgrest.py:68-73`; the migration-replay suite spins its own
  throwaway container (`transformed-migration-test`, pgvector/pgvector:pg16, :55433).
- Story 1-12's lesson: `skipif` is evaluated at **collection** time. A fixture that prepares data
  later leaves tests already marked skipped.

### Project Structure Notes

New code lands in `app/modules/content/` — router, `schemas.py`, `config.py`. No new module. Read
models stay local to the content module; `packages/shared` is a frozen four-dev contract
(CLAUDE.md §16) and needs no change here.

### References

- `docs/book-scale-phase-tracker.md` § Phase 6; § Phase 1 Observed result (the 138-page chapter, the
  2,296–2,816 chars/page measurements)
- `docs/DEFECT-REGISTER.md` — D9, D34, D37, D41, D43
- `supabase/migrations/20260611000000_initial_schema.sql`,
  `20260625000000_chunks_inline_embedding.sql`, `20260714020000_add_lesson_tier.sql`,
  `20260803000000_chapters_book_scoped.sql`
- `git show main:apps/api/app/modules/content/router.py` — the deleted lesson-creation block this
  story re-implements, chapter-scoped

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] — 2026-08-04. Five agents on disjoint files (implementation; new endpoint
tests; real-infrastructure tests; existing-guard repairs; register + contract), preceded by a
seven-investigator reconnaissance and an adversarial synthesis.

### Debug Log References

**Live gate — real 1,151-page book, real Supabase, real API.**

| Step | Result |
|---|---|
| Ingest | 1,151 pages, 21 chapters, upload 58.0 s, end-to-end 90.3 s |
| Generation half (AC20 3-7) | **12/12** |
| Page bounds reaching the subprocess (AC20 8) | **3/3** — argv `(40, 68)`, images on 52/54/55/61, 82,665 chars for 29 p vs ~3,280,945 for the whole book |
| Gating suite | **1068 passed, 1 skipped** (was 968 / 10) |
| ruff repo-wide · mypy | clean · 24 errors in 3 files, unchanged from `main` |

**Two defects found that the unit suite could not have caught.**

`D52` — `_get_user_key` decoded the bearer token with no `audience=`. Every Supabase token carries
`aud: "authenticated"`, PyJWT raises `InvalidAudienceError` in exactly that case, the bare
`except` swallowed it, and it fell through to `get_remote_address`. **Every authenticated user
shared one IP-keyed bucket** — one caller exhausting `3/minute` locked out everyone behind the
same egress IP. It predates this story: `upload_lesson`'s `5/minute` has had it since it was
written. Found because AC20 step 7d expected a 404 for another user's book and got a 429. Fixed
with `verify_aud: False`, the fallback log raised DEBUG→WARNING (reaching it is a security
posture change, not a detail), and 8 regression tests including a premise test that pins the
PyJWT behaviour. Mutation-checked: removing the flag reddens 3.

`D51` — CI's anti-vacuum guard on the gating `-m postgres` step read
`grep -qE "^[0-9]+ skipped|no tests ran"`, which only ever matches an ALL-skipped run. pytest's
mixed summary is `9 passed, 12 skipped in 3.20s`, so a PARTIAL skip passed green: the PostgREST
half of the harness had been skipping in CI, unreported, since it was written. Tightened to fail
on any skip and truth-tabled over four summary shapes. `postgresql-client` is now installed
explicitly rather than assumed from the runner image.

**A cross-endpoint contract inconsistency, found by a test agent and fixed at the source.**
`LessonGenerationResponse.status` returned `"queued"` on the 202 branch but the raw DB column on
the 200 branch — and `latest_lesson.status` did the same. `lessons.status` is
`generating|ready|failed`; every lesson-facing response in this API is
`queued|running|ready|failed` via `_map_status`. Dev 2 would have seen `"generating"` from the
chapter card and `"running"` from `GET /lessons` for the same lesson, so a status switch matching
on `"running"` would silently fall through on chapter cards only. Both paths now map.

**A story error the implementer caught.** The frozen contract left the bad-tier 422 shape
unspecified. Validation lives in `GenerateLessonRequest` as a pydantic `field_validator`, so the
body is pydantic's error list with `loc` ending in `tier`, not a plain string. Observed live.

**Three stale-process incidents**, all the same shape as the defects above — something reporting
success without being checked. A stale `uvicorn` served 3 book routes while source had 4; my own
port-free check used `LISTENING.*:8077`, which can never match Windows `netstat` column order and
so reported "free" unconditionally; and two stale ARQ workers running pre-Story-1-13 code (their
lesson `SELECT` predates `chapter_id`) failed every lesson within seconds and produced three false
gate failures. Also worth recording: `app.routes` is the wrong instrument on this FastAPI version
— module routes are `_IncludedRouter` branches with no `.path`. Use `app.openapi()`.

### Completion Notes List

- All ACs discharged, including the seven marked [PG]/[PGRST] — the harness now self-provisions
  its containers, so nothing skips except with no Docker daemon.
- `chapters.lesson_id` is neither read nor written anywhere in `app/modules/content/`, guarded by
  a widened source scan AND a real-Postgres test that demonstrates the cascade it would cause.
- No AC in this story spent money. The eleven generation nodes were never run to completion; that
  is Story 1-13 AC10, folded into Phase 7 by D43.

### File List

- `apps/api/app/modules/content/router.py`, `schemas.py`, `apps/api/app/config.py` (modified)
- `apps/api/app/core/rate_limit.py` (modified — D52)
- `.github/workflows/ci.yml` (modified — D51)
- `apps/api/tests/unit/test_generate_lesson_endpoint.py` (new — 69 tests)
- `apps/api/tests/unit/test_rate_limit_key.py` (new — 8 tests, D52)
- `apps/api/tests/integration/test_generate_rollback_postgres.py` (new)
- `apps/api/tests/integration/test_book_select_lists_against_postgrest.py`,
  `test_migration_chapters_book_scoped.py` (extended)
- `apps/api/tests/unit/test_content_router.py`, `test_book_endpoints.py`,
  `test_pipeline_writes_no_books.py` (guards updated, none weakened)
- `docs/DEFECT-REGISTER.md` (D44-D52, D34 amended), `docs/contracts/book-api.v1.json` (1.1.0),
  `docs/book-scale-phase-tracker.md`
