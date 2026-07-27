---
baseline_commit: 74efedc
---

# Story 2.25: Sprint 2 audit gap-fix — Dev1-owned findings (admin auth, media allowlist, stale docstring, contract drift)

Status: review

## Story

As Dev 1 (content pipeline / infra owner),
I want to fix the 4 findings from the Sprint 2 360-degree audit (`docs/reports/sprint2-360-audit-2026-07-27.md`) that fall under my own ownership per CLAUDE.md's team ownership table (content pipeline, infra, admin panel per Epic 3 Story 3.2 / Epic 5),
so that these gaps are closed before compiling the wiring requirements Dev 2 needs to sync the frontend to real endpoints.

**Source:** `docs/reports/sprint2-360-audit-2026-07-27.md`, findings: Content Pipeline #3, Media #2/#3, Shared Contract Drift #1/#3. The other 21 findings in that report belong to Dev2/Dev3/Dev4 and are explicitly out of scope here.

## Acceptance Criteria

1. **AC-1 — Admin module authorized and real.** `apps/api/app/modules/admin/router.py`'s 4 endpoints (`GET /jobs`, `GET /jobs/{job_id}`, `GET /costs`, `GET /health`) are no longer 501 stubs and are gated by a new `require_admin` dependency. Admin check: a new `admin_emails: list[str]` setting (env var `ADMIN_EMAILS`, comma-separated, default empty) checked against `current_user["email"]` — no new DB table/migration, matching the "least new surface area" principle since the JWT payload already carries `email`. A non-admin (or missing `email` claim) gets `403`, not `404`/`401` (they're authenticated, just not authorized).
   - `list_jobs` / `get_job`: real queries against `lesson_jobs` joined to `lessons` (for `user_id`) via Supabase's embedded-resource select syntax; `JobSummary.user_id` populated from the join.
   - `get_cost_report`: aggregates `lesson_jobs.cost_usd` for jobs whose `lessons.created_at` falls in the requested `period` (`today`/`this_week`/`this_month`); `by_user` computed by grouping the fetched rows by `user_id` in Python (Supabase client has no server-side GROUP BY here). `by_provider` is **dropped from `CostReport`** — cost is tracked as a single running total per lesson (`cost_tracker.py`'s Redis key), never broken out per-provider anywhere in the system, so a `by_provider` field could only ever be a fake always-empty dict. Removing an honest gap beats faking data (documented below in Dev Notes).
   - `deep_health`: real `redis.ping()` and a lightweight Supabase query (`select count(*) from lessons limit 1` equivalent); returns `"degraded"` if either fails, `"down"` if both fail. `worker_queue_depth` stays `None` with a comment — ARQ's `ArqRedis` doesn't expose a simple queue-depth call without additional instrumentation; faking a number here would be worse than an honest `None`.
2. **AC-2 — Media signed-URL allowlist fixed.** `apps/api/app/modules/media/router.py`'s `_ALLOWED_BUCKETS` drops `source-pdfs`, `avatar-clips`, and `lesson-slides` — confirmed via repo-wide grep that no frontend caller (`apps/web/src`) references any of the three, and each is structurally broken today (`source-pdfs`'s real path shape is `{user_id}/{book_id}/{filename}`, not `{lesson_id}/...`; `avatar-clips`'s static clip paths have no UUID prefix at all; `lesson-slides` bucket is never provisioned in `storage.py`'s `REQUIRED_BUCKETS` or any migration). `lesson-audio` and `lesson-images` — the two buckets actually used by `content/router.py`'s `_resolve_lesson_content` — are untouched.
3. **AC-3 — Stale pipeline docstring fixed.** `apps/api/app/modules/content/pipeline/graph.py`'s module docstring (lines 34-36) currently claims "Phase 1 economy nodes do NOT yet have an equivalent per-section checkpoint — see docs/stories/2-1b-phase1-checkpoint-idempotency.md (deferred, tracked)." This is false — `_read_phase1_checkpoint`/`_write_phase1_checkpoint`/`_increment_phase1_progress` are called in all 6 economy nodes (Story 2-1b actually landed). Remove the stale claim.
4. **AC-4 — Contract nullability + tier-default drift fixed (image_url/audio_url rename explicitly OUT of scope — see Dev Notes).**
   - `packages/shared/types/lesson.ts`'s `LessonRecord.title` and `LessonRecord.source_file_path` become `string | null` (matching `schemas/lesson.py`'s existing `str | None` and `router.py`'s actual behavior — both are `None` until the pipeline names/stores the lesson).
   - `LessonMetadata.tier` becomes optional in both `lesson.ts` (`tier?: LessonTier`) and `lesson_package.schema.json` (removed from `LessonMetadata.required`) — matching Pydantic's existing `tier: LessonTier = "T2"` default. A payload omitting `tier` should validate identically across all three layers; today it fails JSON-Schema/TS validation but silently passes in Python.

## Tasks / Subtasks

- [x] Task 1 (AC: 1): `app/config.py` — add `admin_emails: list[str] = Field(default_factory=list)` with a validator/field parser for comma-separated `ADMIN_EMAILS` env var (follow the existing `cors_origins` list-parsing pattern in the same file).
- [x] Task 2 (AC: 1): `app/dependencies.py` — add `require_admin` dependency (depends on `get_current_user` + `get_settings`; raises 403 if `current_user.get("email")` not in `settings.admin_emails`); export `AdminUser` annotated shorthand alongside `CurrentUser`.
- [x] Task 3 (AC: 1): `apps/api/app/modules/admin/router.py` — implement `list_jobs`, `get_job`, `get_cost_report`, `deep_health` for real; swap `CurrentUser` → `AdminUser` on all 4 routes; drop `by_provider` from `CostReport`.
- [x] Task 4 (AC: 1): New tests `apps/api/tests/unit/test_admin_router.py` — admin allowlist gate (403 for non-admin, 200 for admin), each endpoint's real query path (mocked Supabase/Redis), `deep_health` degraded/down branches.
- [x] Task 5 (AC: 2): `apps/api/app/modules/media/router.py` — remove `source-pdfs`, `avatar-clips`, `lesson-slides` from `_ALLOWED_BUCKETS`. Update `apps/api/tests/unit/test_media_router.py` if any test references the removed buckets (add a regression test asserting they now 400).
- [x] Task 6 (AC: 3): `apps/api/app/modules/content/pipeline/graph.py` — fix the stale docstring lines.
- [x] Task 7 (AC: 4): `packages/shared/types/lesson.ts` + `packages/shared/lesson_package.schema.json` — nullability + tier-optional fixes. No Pydantic change needed (already correct — Python was the one layer that was right all along).
- [x] Task 8 (AC: 4): Any existing test/fixture asserting `tier` is required at the JSON-Schema/TS level, or asserting `title`/`source_file_path` reject `null`, needs updating to match (grep `test_lesson_schema.py` for schema-validation assertions).
- [x] Task 9: Full unit suite green (`uv run pytest`); `ruff check .`, `ruff format --check .`, `mypy app/` all clean. Confirm zero `apps/web/**` touches (this story is backend/contract only — Dev2's wiring work is separate and comes after this).

## Dev Notes

- **Scope decision — `image_url`/`audio_url` → `image_path`/`audio_path` rename is explicitly OUT of scope for this story**, despite being audit finding "Shared Contract Drift #4". Reasoning: (a) it's the audit's own LOW-severity item, lowest priority of the four; (b) it touches `schemas/lesson.py`, `lesson.ts`, `lesson_package.schema.json`, `graph.py` (3+ write sites), `content/router.py`, and 6 test files (`test_lesson_ready_pubsub.py`, `test_content_router.py`, `test_image_generator_node.py`, `test_lesson_schema.py`, `test_package_builder_node.py`, `test_slide_generator_node.py`, `test_tts_node.py`) — a much larger blast radius than the other 3 fixes combined, for a pure naming clarity improvement with zero behavior change; (c) CLAUDE.md §16 requires 4-dev review for frozen-contract changes — a rename should be proposed to the team, not landed unilaterally in a Dev1 gap-fix commit. **Action:** flag this as a proposed follow-up when compiling requirements for Dev2/Dev3/Dev4, don't silently drop it.
- **Admin auth mechanism chosen: env-var email allowlist, not a DB `is_admin` column.** Epic 5 (`docs/bmad/epics/epic-5-platform-core.md`) describes a future `profiles.is_admin` flag, but that `profiles` table doesn't exist yet (only `public.users` does, confirmed via `supabase/migrations/20260611000000_initial_schema.sql`) and building it is Epic 5 scope, not this gap-fix. `ADMIN_EMAILS` is the minimal viable mechanism today — zero new migrations, matches the audit's own suggested option, and is trivially upgradable to a DB flag later without changing `require_admin`'s call sites (only its internals).
- **`CostReport.by_provider` is being removed, not stubbed.** `apps/api/app/core/cost_tracker.py` tracks exactly one Redis float per lesson (`cost:{lesson_id}`, 24h TTL) — there is no per-provider cost breakdown anywhere in the system to aggregate. Returning an always-empty `{}` would look like real (if currently-zero) data; removing the field is the honest choice. If per-provider cost attribution is wanted later, it's a `cost_tracker.py` instrumentation change (Sprint 3's "Pipeline cost attribution in Langfuse", Epic 3 Story 3.3), not something this endpoint can synthesize from data that doesn't exist.
- **`worker_queue_depth` stays `None`.** ARQ's `ArqRedis` (from `app.dependencies.get_arq_redis`) doesn't expose a trivial "how many jobs are queued" call without reaching into ARQ's internal Redis key structure — out of scope to reverse-engineer for this gap-fix; documented as a known gap in the field's docstring rather than a wrong number.
- **`lesson_jobs` has no `user_id` column** (confirmed via `docs/dev1-tracker.md`'s DB Tables Owned by Dev 1 section — columns are `job_id, lesson_id, status, last_node, node_outputs, error, attempt, cost_usd, started_at, completed_at, created_at`). `JobSummary.user_id` must come from a join to `lessons.user_id` via `lesson_id` — use Supabase's embedded-resource select (`.select("*, lessons(user_id, created_at)")`), the same FK Postgrest can already traverse (`lesson_jobs.lesson_id → lessons.lesson_id`, both existing, applied migrations).
- **Media allowlist removals are backend-only and additive-safe.** `avatar-clips` bucket is still written to directly by `apps/api/app/providers/avatar/heygen.py` (unrelated code path, not through `media/router.py`'s signed-url endpoint) — removing it from `_ALLOWED_BUCKETS` only closes the always-broken signed-URL-request path, it does not affect HeyGen's own storage writes.
- **`title`/`source_file_path` nullability**: `apps/api/app/modules/content/router.py:92` already returns `None` for `title` until `package_builder_node` sets it; Pydantic (`schemas/lesson.py:232,235`) already has this right. Only `lesson.ts` (frontend's mirror) needs the fix — no backend behavior change at all, purely a type-annotation correction that was always technically a lie.
- **`tier` required/optional**: `lesson_package.schema.json:54-61` lists `tier` in `LessonMetadata.required`; `lesson.ts:19` has no `?`. Pydantic (`schemas/lesson.py:58`) already defaults it. Fix both non-Python layers to match — no Python change.

### Project Structure Notes

- Touches: `apps/api/app/config.py` (UPDATE), `apps/api/app/dependencies.py` (UPDATE), `apps/api/app/modules/admin/router.py` (UPDATE), `apps/api/app/modules/media/router.py` (UPDATE), `apps/api/app/modules/content/pipeline/graph.py` (UPDATE — docstring only), `packages/shared/types/lesson.ts` (UPDATE), `packages/shared/lesson_package.schema.json` (UPDATE), `apps/api/tests/unit/test_admin_router.py` (NEW), `apps/api/tests/unit/test_media_router.py` (UPDATE if needed), `apps/api/tests/unit/test_lesson_schema.py` (UPDATE if schema-validation assertions need adjusting). Zero `apps/web/**` touches — this is a pure backend/contract gap-fix; Dev2's wiring work is a separate, subsequent effort.
- **No new migration** — the admin-auth approach was deliberately chosen to avoid one (see Dev Notes).

### References

- [Source: docs/reports/sprint2-360-audit-2026-07-27.md] — this story's origin; findings "Content Pipeline #3", "Media #2/#3", "Shared Contract Drift #1/#3"
- [Source: CLAUDE.md#Team Ownership] — admin panel + content pipeline + infra = Dev1
- [Source: docs/bmad/epics/epic-5-platform-core.md#Admin Panel] — future `is_admin`/`profiles` design (Epic 5, not this story)
- [Source: docs/bmad/epics/epic-1-content-pipeline.md, epic-2 (Story 3.2 admin panel origin)]
- [Source: apps/api/app/core/cost_tracker.py] — confirms no per-provider cost breakdown exists
- [Source: docs/dev1-tracker.md#DB Tables Owned by Dev 1] — `lesson_jobs` column list (no `user_id`)

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-27 | Story created from Sprint 2 360-degree audit findings (Dev1-owned subset only). | Dev 1 |
| 2026-07-27 | Implemented all 4 ACs: `require_admin` env-allowlist gate + real `list_jobs`/`get_job`/`get_cost_report`/`deep_health`; media allowlist trimmed to `lesson-audio`/`lesson-images`; stale `graph.py` docstring corrected; `lesson.ts`/`lesson_package.schema.json` nullability + tier-optional fixes. 617/617 unit+integration tests pass (2 pre-existing, unrelated integration failures on `main` confirmed via `git stash` before this story's changes and deselected), ruff/ruff-format/mypy clean on every touched file. Zero `apps/web/**` touches. `image_url`/`audio_url` → `image_path`/`audio_path` rename deliberately deferred (see Dev Notes) — flagged as a proposed follow-up for the Dev2 requirements handoff. | Dev 1 |

## Dev Agent Record

### Debug Log References

- `uv run pytest tests/unit/test_admin_router.py tests/unit/test_media_router.py tests/unit/test_lesson_schema.py -q` — 55 passed.
- `uv run pytest tests/unit tests/integration -q` — first run surfaced 2 failures in `test_howto_pipeline_e2e.py` (`unmocked response_format _QuizBatchLLM`); confirmed pre-existing via `git stash` (re-ran against baseline `74efedc` — same 2 failures, unrelated to this story's diff, in `quiz_generator_node`/`structure_node`, files this story never touches). Deselected for the story's own gate; full suite otherwise 617 passed, 1 skipped.
- `uv run ruff check .` / `ruff format --check .` / `uv run mypy app/` (full repo) — pre-existing findings only in files this story didn't touch (`apps/api/app/modules/assessment/service.py` mypy errors, assorted pre-existing E501/format issues in other test files); all touched files clean after fixing 2 self-introduced issues (a `dict` → `dict[str, Any]` mypy annotation in `admin/router.py`, and `E501`/`UP017` lint issues in the new `test_admin_router.py`, both fixed).

### Completion Notes List

- `require_admin` (env-var `ADMIN_EMAILS` allowlist against the JWT `email` claim) is the admin gate — deliberately not a DB `is_admin` column, since no `profiles` table exists yet (that's Epic 5 scope). Non-admin → 403; missing `email` claim → 403 (fails closed).
- `list_jobs`/`get_job` query `lesson_jobs` joined to `lessons` via Supabase's embedded-resource select (`*, lessons(user_id)`) since `lesson_jobs` itself has no `user_id` column.
- `get_cost_report` aggregates `lesson_jobs.cost_usd` by period (`today`/`this_week`/`this_month`, computed via `_period_start`), grouped by user in Python. `CostReport.by_provider` was removed (not stubbed) — `cost_tracker.py` never tracks a per-provider breakdown, so an always-empty dict would misrepresent real data as a legitimate zero.
- `deep_health` runs a real `redis.ping()` and a lightweight Supabase probe; `worker_queue_depth` stays `None` (ARQ exposes no simple queue-depth call) rather than a fabricated number.
- Media allowlist (`_ALLOWED_BUCKETS`) trimmed from 5 to 2 entries (`lesson-audio`, `lesson-images`) — the 3 removed buckets were each structurally unreachable via `_parse_lesson_id`'s `{lesson_id}/...` assumption or never provisioned, and had zero frontend callers (confirmed via repo-wide grep before removing, per Dev Notes).
- `graph.py`'s stale Phase-1-checkpoint docstring claim corrected to reflect that Story 2-1b actually landed.
- `lesson.ts`: `LessonRecord.title`/`source_file_path` now nullable, `LessonMetadata.tier` now optional — both zero-behavior-change TS-only fixes (Pydantic was already correct on both). `lesson_package.schema.json`: `tier` removed from `LessonMetadata.required`. New regression test (`test_lesson_metadata_omitting_tier_validates_against_raw_json_schema`) proves a tier-omitting metadata dict now validates against the raw schema directly (not just via Pydantic's default-filling model_dump, which always masked the drift).
- **Deliberately deferred, not implemented**: `image_url`/`audio_url` → `image_path`/`audio_path` rename (audit's own LOW-severity item) — blast radius (3 contract files + `graph.py` + `content/router.py` + 6 test files) far exceeds the other 3 fixes combined for a pure naming-clarity change, and CLAUDE.md §16 requires 4-dev sign-off for frozen-contract changes; proceeding solo in a Dev1 gap-fix commit would be the wrong call. Flagged for the Dev2/Dev3/Dev4 requirements handoff instead.

### File List

- `apps/api/app/config.py` (UPDATE) — `admin_emails` setting + `_parse_admin_emails` validator.
- `apps/api/app/dependencies.py` (UPDATE) — `require_admin` dependency + `AdminUser` annotated shorthand.
- `apps/api/app/modules/admin/router.py` (UPDATE) — all 4 endpoints implemented for real, gated by `AdminUser`; `CostReport.by_provider` removed.
- `apps/api/app/modules/media/router.py` (UPDATE) — `_ALLOWED_BUCKETS` trimmed to `lesson-audio`/`lesson-images`.
- `apps/api/app/modules/content/pipeline/graph.py` (UPDATE) — stale docstring fix only.
- `packages/shared/types/lesson.ts` (UPDATE) — `LessonRecord` nullability, `LessonMetadata.tier` optional.
- `packages/shared/lesson_package.schema.json` (UPDATE) — `tier` removed from `LessonMetadata.required`.
- `apps/api/tests/unit/test_admin_router.py` (NEW) — 12 tests covering the admin gate and all 4 endpoints.
- `apps/api/tests/unit/test_media_router.py` (UPDATE) — regression test for the 3 removed buckets.
- `apps/api/tests/unit/test_lesson_schema.py` (UPDATE) — stale docstring fix on the tier round-trip test + new regression test for tier-omitted schema validation.
- `docs/stories/2-25-sprint2-audit-gapfix-dev1-items.md` (this file).
