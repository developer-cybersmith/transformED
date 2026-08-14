# Story Demo-T15 — Validate Quiz + Teach-Back Payloads Against Real LessonPackage Schema

**Status:** done
**Sprint:** Demo Sprint (Phase L4)
**Owner:** Dev 3 + Dev 2 (Dev 3 owns backend validation; Dev 2 owns player integration)
**Branch:** `dev3-demo-t15-phaseL4`
**PR target:** `master-demo-dev3`
**Source:** `d:/HIE-Demo-Task-Tracker.xlsx` — T15 / Phase L4
**Priority:** High | **Blocking:** L3 real-lesson playback (T12/T13)

---

## Problem Statement

All existing `grade_quiz` and `grade_teachback` unit tests use simplified, non-schema-accurate
fixtures:
- `lesson_id: "lesson-001"` (not a UUID — real pipeline produces `format: uuid`)
- `segment_id: "seg-001"` (arbitrary string)
- `question_id: "q1"`, `"q2"` (arbitrary — real pipeline produces namespaced IDs)
- `_LESSON_CONTENT` only contains `{lesson_id, segments[{segment_id, quiz}]}` — missing
  all required fields: `book_id`, `chapter_id`, `created_at`, `metadata`, `glossary`,
  and within each segment: `complexity`, `slides`, `narration`, `teachback_prompt`,
  `jargon`, `interventions`

When Dev 1's first real `LessonPackage` lands (Phase L1 is Done), the assessment endpoints
**may silently fail or KeyError** if any service code accesses fields the simplified fixture
doesn't have. More critically: **the "confirm a real session row is created and both endpoints
find it" requirement has never been tested end-to-end** with schema-compliant data.

Additionally, `grade_teachback` extracts `topic = segment.get("title", "")` and
`key_concepts = [j["term"] for j in segment.get("jargon", [])]`. Current fixtures have
no `title` or `jargon` fields — so every teachback test is silently scoring with an empty
topic and zero concepts, which will produce worse GPT output than expected against real data.

---

## User Story

As Dev 3, I need the quiz and teach-back endpoints to be **validated against a complete,
schema-accurate LessonPackage fixture** — one that matches every field the real pipeline
produces — so that when the first real lesson package lands the assessment flow works on
the first attempt, not after debugging production failures.

As Dev 2, I need to be confident that `POST /api/assessment/quiz` and
`POST /api/assessment/teachback` process the payloads the frontend sends for a real lesson
without 422 or 500 errors caused by field-shape mismatches.

---

## Acceptance Criteria

**AC1 — Real-schema quiz submission succeeds:**
A `QuizSubmission` built from a schema-valid `LessonPackage` (all required fields present,
UUID IDs, `segment.quiz[].question_id` in real format) processes through `grade_quiz()`
without error. Result: `QuizResult` with correct `score`, `correct_count`, `total_count`,
and non-empty `feedback`. Test: mock DB layer; call `grade_quiz()` with real-schema fixture.

**AC2 — Real-schema teachback submission succeeds:**
A `TeachbackSubmission` against the same real-schema package processes through
`grade_teachback()` without error. The scorer receives `topic = segment.title` (non-empty)
and `key_concepts` from `segment.jargon[].term` (non-empty list). Test: mock DB + GPT scorer.

**AC3 — Session chain: create → quiz → teachback (end-to-end at service layer):**
A session created with a UUID `lesson_id` is findable by both endpoints — i.e., a mock
supabase that returns `sessions.session_id = X, user_id = Y, lesson_id = UUID` is correctly
matched when quiz/teachback submit with the same IDs. No `session not found` 404 occurs
when IDs are schema-compliant UUIDs.

**AC4 — Schema validation on the fixture itself:**
The real-package fixture used in tests validates against `packages/shared/lesson_package.schema.json`
using `jsonschema`. If the fixture diverges from the schema (missing field, wrong type), the
test fails before the endpoint is even called.

**AC5 — Segment not found uses real UUID lesson_id in error:**
When a `segment_id` not present in the package is submitted, `grade_quiz()` returns HTTP 404
with a detail that includes the real UUID `lesson_id` (not a simplified string), confirming
the error path works with real-format IDs.

**AC6 — IDOR guard works with UUID session_id:**
When a different UUID `user_id` submits against a session owned by `user_id_A`, `grade_quiz()`
returns HTTP 404 (SEC-006 — no enumeration oracle). Tested with UUID-format user IDs.

**AC7 — Wrong question_id in submission returns 422:**
When the submitted `question_id` does not match any question in the real segment's quiz array,
`grade_quiz()` returns HTTP 422. Confirms the question lookup works on real-format IDs
(not just `"q1"`, `"q2"`).

**AC8 — Empty jargon graceful fallback:**
If a real segment has an empty `jargon` array (valid per schema — `jargon` is an array with
no `minItems`), `grade_teachback()` still succeeds with `key_concepts = []`. Scorer receives
empty list without error.

**AC9 — Response_index out of range returns 422 with real options count:**
A quiz answer with `response_index >= len(options)` (real quiz has 4 options per question,
per schema `minItems: 4`) returns HTTP 422. Confirms bounds check works on real-format data.

---

## Scale & Load

**Q1 — ONE unit of work and its range:**
One quiz submission = 1 `grade_quiz()` call covering 1–N answers for one segment.
Real LessonPackage has 1–5 quiz questions per segment (T1: 3–5, T2: 2–3, T3: 1–2 per segment,
per learner-mode tier design). The test validates with 3 questions (T2 standard).
Teachback: one `grade_teachback()` call = 1 GPT scoring call. Fixed at 1 per segment.

**Q2 — Fixed budgets while input varies:**
`QuizSubmission.answers: list[QuizAnswer] = Field(min_length=1, max_length=50)` — hard-capped
at 50. The real pipeline generates at most 5 questions per segment; schema has no `maxItems`
on `segment.quiz`, so the 50-answer cap is the binding guard. No silent truncation: if
`answers > 50`, Pydantic raises 422 before service code runs.

**Q3 — Scope of every limit:**
- `max_length=50` on answers: per-request (Pydantic schema validation)
- Session ownership check: per-user, per-session
- This test suite: unit tests with mocked DB — no real resource limits exercised.

**Q4 — Unbounded reads/writes:**
No new reads or writes introduced by this story (tests only). The existing `grade_quiz`
inserts to `quiz_attempts` are bounded by the `answers` list (max 50, see Q2).

**Q5 — Inherited caps re-derived:**
The `max_length=50` on answers was sized for max 50 MCQs per submission. The real pipeline
generates at most 5 per segment. The cap is 10× over the real maximum — safe.

**Q6 — Check-then-act concurrency:**
No new check-then-act sequences introduced. The duplicate-question_id guard (Step 5b) and
session ownership check (Step 1) are pre-existing and unchanged. This story adds tests, not
logic.

---

## Tasks / Subtasks

- [x] **T1 — RED: write failing tests** — ✓ 2026-08-13
  - [x] T1.1 `test_real_schema_quiz_fixture_validates_against_schema` — jsonschema validation
  - [x] T1.2 `test_quiz_with_real_package_succeeds` — AC1
  - [x] T1.3 `test_teachback_receives_title_and_jargon_from_real_segment` — AC2
  - [x] T1.4 `test_session_chain_uuid_ids_quiz_and_teachback` — AC3
  - [x] T1.5 `test_segment_not_found_uuid_lesson_id_in_error` — AC5
  - [x] T1.6 `test_idor_guard_uuid_user_ids` — AC6
  - [x] T1.7 `test_wrong_question_id_returns_422` — AC7
  - [x] T1.8 `test_empty_jargon_teachback_graceful` — AC8
  - [x] T1.9 `test_response_index_out_of_range_422` — AC9
- [x] **T2 — GREEN: implement — build schema-accurate fixture + any service fixes** — ✓ 2026-08-13
  - [x] T2.1 `_build_real_lesson_package()` factory in test module
  - [x] T2.2 No KeyError/AttributeError — service code handled real schema correctly
  - [x] T2.3 Empty title/jargon gap confirmed via AC2 spy — title+jargon now explicitly tested
- [x] **T3 — VERIFY: run full test suite, confirm no regressions** — ✓ 2026-08-13 — 134/134 passed
- [x] **T4 — UPDATE dev3-assessment-tracker.md: mark T15 complete** — ✓ 2026-08-13

---

## Dev Notes

### Fixture structure (real schema)

The real `LessonPackage` content stored in `lessons.content` JSONB:
```python
{
    "lesson_id": "550e8400-e29b-41d4-a716-446655440000",  # UUID
    "book_id":   "6ba7b810-9dad-11d1-80b4-00c04fd430c8",  # UUID
    "chapter_id": "6ba7b812-9dad-11d1-80b4-00c04fd430c8",  # UUID
    "created_at": "2026-08-13T10:00:00Z",
    "metadata": {
        "title": "Introduction to Thermodynamics",
        "subject": "Physics",
        "total_segments": 3,
        "estimated_duration_mins": 45.0,
        "complexity_level": "medium",
        "tier": "T2"
    },
    "segments": [
        {
            "segment_id": "seg-0-intro-thermodynamics",
            "segment_index": 0,
            "title": "What is Thermodynamics?",
            "summary": "An introduction to energy, heat, and work.",
            "complexity": {
                "level": "low",
                "cognitive_load": "low",
                "abstraction_level": "concrete",
                "prerequisite_concepts": ["energy", "force"],
                "narration_style": "conversational",
                "quiz_difficulty": "easy",
                "intervention_sensitivity": 0.3
            },
            "slides": [{"slide_id": "s0", "title": "...", "bullets": [...], "image_url": null, "fallback_image_url": null}],
            "narration": {"script": "...", "audio_url": "...", "audio_provider": "sarvam", "timestamps": [...]},
            "quiz": [
                {
                    "question_id": "seg-0-q-0",
                    "type": "mcq",
                    "question": "What does thermodynamics study?",
                    "options": ["Sound", "Energy and heat", "Light", "Magnetism"],
                    "correct_index": 1,
                    "explanation": "Thermodynamics is the study of energy, heat, and work.",
                    "difficulty": "easy"
                }
            ],
            "teachback_prompt": "Explain what thermodynamics is and why it matters.",
            "jargon": [
                {"term": "entropy", "definition": "Measure of disorder in a system."},
                {"term": "enthalpy", "definition": "Total heat content of a system."}
            ],
            "interventions": {
                "distraction": ["...", "...", "..."],
                "confusion":   ["...", "...", "..."],
                "fatigue":     ["...", "...", "..."]
            }
        }
    ],
    "glossary": [{"term": "energy", "definition": "The capacity to do work."}]
}
```

### Critical finding: `grade_teachback` uses title + jargon, NOT teachback_prompt

`grade_teachback()` service.py lines 558-559:
```python
topic: str = target_segment.get("title", "")
key_concepts: list[str] = [j["term"] for j in target_segment.get("jargon", [])]
```

The `teachback_prompt` field in the schema is NOT currently consumed by the scorer. This is
pre-existing behaviour, not a bug introduced by this story. The GPT scorer receives the
segment `title` as topic and jargon `term` values as key concepts. With simplified fixtures
(no `title`, no `jargon`), the scorer was silently receiving `topic=""` and `key_concepts=[]`.

The test `test_teachback_receives_title_and_jargon_from_real_segment` (AC2) will explicitly
assert that the scorer is called with the correct non-empty values from the real fixture.

### Files touched

| File | Change |
|------|--------|
| `apps/api/tests/test_real_package_payload_validation.py` | New — schema-accurate test suite |

No service.py changes expected unless running real-schema data reveals a KeyError.
The `jsonschema` package is already in dev dependencies (`pyproject.toml`).

---

### Review Findings

**6-agent adversarial review — 2026-08-13 — 0 patch, 0 defer, 0 dismissed**

✅ Clean review — all 6 layers passed.

Layers run: Story Quality · Blind Hunter · Test Coverage (Edge Case Hunter) · AC Completeness (Acceptance Auditor) · Process Integrity · Scale & Load Hunter

Scale & Load Hunter result: `[]` (no findings — diff is test-only, no new reads/writes, no budget caps introduced)

---

## Change Log

| Date | Change |
|------|--------|
| 2026-08-13 | Story created (story-first gate) |
| 2026-08-13 | Implementation complete — 9 tests, 134/134 suite green |
| 2026-08-13 | BMAD 6-agent review: clean — 0 findings |
