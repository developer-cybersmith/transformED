# §16 Frozen-Contract Compatibility Report — Contract #1 (LessonPackage)

**PR:** #74 — `integration/sprint2-phase-b-into-main` → `main`
**Author / Certifier:** Dev1
**Date:** 2026-07-20
**Contract under change:** `packages/shared/lesson_package.schema.json` + `packages/shared/types/lesson.ts` (mirrored by Pydantic `apps/api/app/schemas/lesson.py`)
**Self-certification decision:** ✅ **SELF-CERTIFIABLE** — every breaking surface has a concrete, already-applied Dev1-only fix; no already-merged Phase 2 consumer is silently broken; typecheck and both test suites are green.

---

## 1. The Change

| # | Edit | Schema | TS | Pydantic |
|---|------|--------|----|----|
| 1 | `LessonMetadata.tier` NEW | enum `["T1","T2","T3"]`, default `"T2"`, added to `required`, under `additionalProperties:false` (L54-70) | `tier: LessonTier` — **non-optional** (L11, L19) | `tier: LessonTier = "T2"` — **default present** (L38, L58) |
| 2 | `Slide.image_url` / `Slide.fallback_image_url` relaxed | `format:"uri"` → plain `string` / `oneOf(string,null)` | already `string \| null` (unchanged on `main`) | `AnyHttpUrl \| None` → `str \| None` (L96-97) |

**Rationale.** Change 1 propagates the Learner-Mode content-depth tier (Story 2-2) into the lesson package. Change 2 permits Imagen `data:` URIs and private-bucket storage paths (e.g. `{lesson_id}/slide_sec_0_0.png`) that are not valid absolute URIs.

---

## 2. Why each change is bounded — first-principles

**Change 1 (required `tier`) can only break:**
- **(A) TS/JS object-literal constructors** of `LessonMetadata` that omit `tier` → `tsc` TS2741.
- **(C) Strict JSON-schema/ajv validators** fed a **raw** dict lacking `tier` → rejected by `required` + `additionalProperties:false`.
- It does **NOT** break pure readers (adding a field is backward-compatible), and does **NOT** break Pydantic constructors/readers — the model default fills `tier` on `model_validate` and always emits it on `model_dump` (`extra="forbid"` rejects only *unknown* keys, never a *missing-with-default* key).

**Change 2 (uri → string) is a pure widening.** `uri ⊂ string`: every previously-valid value stays valid. It can break only a consumer that assumes an absolute URL — `new URL(image_url)`, `AnyHttpUrl` attribute access, or a strict uri validator.

---

## 3. Consumer surfaces audited

### 3.1 Frontend (`apps/web/src`)
| Consumer | Kind | Constructs metadata literal? | Verdict |
|----------|------|:---:|---------|
| `mocks/data/lessonPackage.ts` | mock | ✅ | `tier:'T2'` added (L14) — compiles |
| `__tests__/stores/player.machine.test.ts` | fixture | ✅ | `tier:'T2'` added (L19) — compiles, 47 tests pass |
| `components/player/Player.tsx` | reader | ❌ | reads title/total_segments/estimated_duration_mins only — unaffected |
| `components/player/SlideRenderer.tsx` | reader | ❌ | passes `image_url` raw to `<img src>`, no URL parse — unaffected by widening |
| `__tests__/components/player/SlideRenderer.test.tsx` | test | ❌ | https strings + null — pass under widened type |
| `stores/player.machine.ts`, `hooks/useLesson.ts`, `services/lesson.service.ts`, `mocks/api/lesson.ts` | readers/passthrough | ❌ | no literal, no runtime schema validator (no ajv/zod) — unaffected |
| `mocks/data/lessons.ts` | local type | ❌ | own `MockLesson`/`Slide` shape, not the shared contract — unaffected |

**Exhaustive result:** exactly **two** metadata literals exist in the web tree; both remediated in-branch. `git diff main...HEAD -- apps/web/src` = **2 files, 2 insertions**, both `tier:'T2'`. No frontend runtime JSON-schema validator exists, so `required`/`additionalProperties:false` never execute client-side.

### 3.2 Backend cross-module consumers (`apps/api/app/**`, outside `content`)
| Consumer | Handling | Verdict |
|----------|----------|---------|
| `core/pubsub.py` | `json.dumps(lesson)` opaque → Redis | no field access — unaffected |
| `workers/jobs/content_pipeline.py` | republishes package verbatim; reads `tier` from the **lessons.tier column**, not JSONB | unaffected |
| `modules/tutor/service.py` | `json.loads(raw)` → indexes `segments[idx].interventions`; try/except degrade | never reads metadata/tier — unaffected |
| `modules/assessment/service.py` | `content` as dict → `segments`; never builds LessonPackage | old rows w/o metadata.tier accepted — unaffected |
| `modules/content/router.py` GET | returns lessons ROW fields, never the content JSONB | unaffected |
| `modules/tutor/state_machine/graph.py` | doc-comments only | unaffected |

`assessment`, `media`, `analytics`, `admin` have **zero** references to the lesson contract. All out-of-module consumers treat the package as an opaque dict.

### 3.3 Producer + strict validators
- `modules/content/pipeline/graph.py::package_builder_node` — sets `"tier"` explicitly (guarded to `_VALID_TIERS`/`_DEFAULT_TIER`) then `LessonPackage.model_validate(...)`. Runs at **generation/write time** with tier always present. This is the only strict full-package validation in non-test app code.
- The **only** `jsonschema.validate` call sites (`tests/unit/test_lesson_schema.py` L103, L195) validate `package.model_dump_json()` — routed through Pydantic first, so `tier='T2'` is present before the strict check. `MINIMAL_PACKAGE_DICT` omits tier but is never validated as a raw dict.

---

## 4. Checks run and results

| Check | Result | Detail |
|-------|--------|--------|
| `npx tsc --noEmit` (apps/web) | ✅ PASS | Exit 0, zero type errors — both metadata literals satisfy required `tier`; image_url relaxation causes no mismatch |
| `npx vitest run` (apps/web) | ✅ PASS | 41 files / 327 tests pass (incl. player.machine tier fixture + SlideRenderer image_url/fallback tests) |
| `pytest tests/unit` (apps/api) | ✅ PASS | 423 passed, 1 skipped (unrelated `test_extract_subprocess`); incl. 29 lesson-schema tests + tier default/accept/reject/round-trip |
| `git diff main...HEAD -- apps/web/src` | ✅ | 2 files, 2 insertions — both `tier:'T2'`; proves break points remediated in-branch |
| grep `ajv\|zod\|jsonschema\|lesson_package.schema` over apps/web/src | ✅ | 0 runtime validators — schema `required` cannot reject data client-side |
| grep `new URL(image_url)` / `AnyHttpUrl` attr use repo-wide | ✅ | 0 matches against image_url — widening has no live break vector |
| grep `LessonMetadata` literals repo-wide | ✅ | exactly 2 (web) + 1 py fixture (`test_lesson_ready_pubsub.py`, already has tier) — all carry tier |

---

## 5. Breakages and fixes

| Breakage class | Present on branch? | Fix | Status |
|----------------|:---:|-----|--------|
| A — TS literal omits tier | No (2 sites remediated) | `+ tier: 'T2'` in each of the 2 literals | ✅ Applied in-branch |
| C — raw dict strict-validated w/o tier | No consumer exists | Route through `model_validate` (Pydantic fills default) | ✅ Structural (default) |
| D — old JSONB rows lack metadata.tier | Harmless | tier read only from lessons.tier COLUMN | ✅ No backfill needed |
| F/G — image_url URL-parse assumption | No consumer exists | n/a — pure widening | ✅ Non-breaking |

**No outstanding required fixes.** The compatibility edits (§5 class A) are already committed on the branch.

---

## 6. Old-data handling (persisted `lessons.content` JSONB)

Rows generated before this change carry metadata **without** a `tier` key. This is a **non-issue, no backfill required**:
- `tier` flows **column-only** end to end: `upload_lesson` writes `lessons.tier` (validated, 422 on bad value) → `content_pipeline_job` re-selects the column → `package_builder` bakes it into **new** content JSONB. Nothing ever reads `tier` back out of stored JSONB.
- Migration `20260714020000_add_lesson_tier.sql` backfills the **column** (DEFAULT `'T2'`) for every row; it does not rewrite metadata inside JSONB, which is correct and sufficient.
- Every read-side consumer (assessment quiz/teachback, tutor interventions, content router GET, frontend player) treats content as a loosely-indexed dict and never strict-validates the full package. Reading old rows via `LessonPackage.model_validate` would also succeed (Pydantic injects `tier='T2'`).
- An optional cosmetic JSONB backfill would matter only if a future consumer starts reading `metadata.tier` from stored content — none does today.

---

## 7. Other three frozen contracts — untouched (confirmed)

`git diff main...HEAD` on each returned **empty (exit 0)**:
- ✅ `packages/shared/types/ws.ts` — WebSocket discriminated union: **no change**
- ✅ `supabase/migrations/20260611000000_initial_schema.sql` — applied migration: **no change**
- ✅ `supabase/migrations/20260625000000_chunks_inline_embedding.sql` — applied migration: **no change**
- ✅ Assessment OpenAPI: content router request/response models (`LessonUploadResponse`/`LessonStatusResponse`) unchanged in shape; only an **additive optional** `tier` FORM field on `POST /lessons` (default `T2`, non-breaking for existing clients). Assessment module's own endpoints read content as a dict and are unaffected.

---

## 8. Residual risk

- **Un-merged branches (out of scope).** A still-open Phase-2 branch could contain a `LessonMetadata` literal omitting `tier`; it would fail `tsc` at merge time — a self-evident, self-fixable compile error, not a silent break.
- **Future strict read-side validation.** If a new endpoint ever runs raw jsonschema/ajv against stored JSONB, legacy tier-less rows would be rejected. No such code exists today; guard by routing through Pydantic or backfilling `metadata.tier` if/when introduced.

No already-merged code is silently broken in any way undetectable by `tsc`/`pytest`.

---

## 9. Conclusion

Both edits to frozen contract #1 are **compatible with all already-merged Phase 2 code**. Change 1's only real break surface (TS metadata-literal constructors) is fully remediated in-branch; the Pydantic default neutralizes every dict/old-row path; Change 2 is a pure widening with no live break vector. The other three frozen contracts are byte-for-byte untouched. Typecheck and both test suites are green.

**Recommendation: attach this report as §16 evidence, self-certify, and merge.** No Dev2/Dev3/Dev4 sign-off is required.