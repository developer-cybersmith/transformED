# Dev 1 — Remaining Sprint 0 Task: Pydantic Lesson Package Schemas

**Owner:** Dev 1
**Sprint:** 0 (Week 1)
**Status:** NOT STARTED — `apps/api/app/schemas/__init__.py` is empty
**Blocks:** All 11 content pipeline nodes (they cannot serialize/deserialize `LessonPackage` to/from the `lessons.content` JSONB column without these models)

---

## What Is This Task

Dev 2 has published the TypeScript contract in `packages/shared/types/lesson.ts` and `packages/shared/lesson_package.schema.json`. This task is the **Python mirror** of that contract — a set of Pydantic v2 models in `apps/api/app/schemas/lesson.py` that represent the same data structures. The JSON schema is authoritative; both the TS types and these Pydantic models must stay in sync with it.

These models serve three purposes:
1. **Pipeline output** — each of the 11 nodes returns typed output that eventually assembles into a `LessonPackage`
2. **DB serialisation** — `LessonPackage` is stored as JSONB in `lessons.content`; Pydantic handles `.model_dump()` → DB and `model_validate()` → Python
3. **API response validation** — the content and lesson routers use these models in FastAPI response schemas

---

## Frozen Contract Reference

| Source | Location |
|---|---|
| JSON Schema (authoritative) | `packages/shared/lesson_package.schema.json` |
| TypeScript types (mirror) | `packages/shared/types/lesson.ts` |
| DB column | `public.lessons.content JSONB` |
| DB row type (TS) | `LessonRecord` in `lesson.ts` |

**Do not diverge from the JSON schema.** If you find a mismatch between this doc and the schema, the schema wins.

---

## File to Create

```
apps/api/app/schemas/lesson.py
```

The existing `apps/api/app/schemas/__init__.py` is a bare empty file. Create `lesson.py` alongside it and re-export from `__init__.py`.

---

## Complete Implementation

Create `apps/api/app/schemas/lesson.py` with the following content:

```python
"""
Pydantic v2 models for the HIE lesson package.

These models are the Python mirror of:
  - packages/shared/types/lesson.ts
  - packages/shared/lesson_package.schema.json  ← authoritative source

The JSON schema uses additionalProperties: false on every object, so every
model uses model_config = ConfigDict(extra="forbid") to enforce the same
constraint at the Python layer.

Never modify these models without also updating lesson.ts and the JSON schema.
Changes require a PR reviewed by all 4 developers (frozen contract, PRD §16).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, AnyHttpUrl


# ---------------------------------------------------------------------------
# Shared config — applied to every model
# ---------------------------------------------------------------------------

_STRICT = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Primitive type aliases  (mirror lesson.ts)
# ---------------------------------------------------------------------------

LessonStatus   = Literal["generating", "ready", "failed"]
ComplexityLevel = Literal["low", "medium", "high"]
AudioProvider  = Literal["elevenlabs", "azure", "browser"]
QuizType       = Literal["mcq", "concept_check"]
QuizDifficulty = Literal["easy", "medium", "hard"]


# ---------------------------------------------------------------------------
# LessonMetadata
# ---------------------------------------------------------------------------

class LessonMetadata(BaseModel):
    model_config = _STRICT

    title:                    str
    subject:                  str
    total_segments:           Annotated[int,   Field(ge=1)]
    estimated_duration_mins:  Annotated[float, Field(ge=0)]
    complexity_level:         str  # free string per schema; use ComplexityLevel if constraining


# ---------------------------------------------------------------------------
# SegmentComplexity
# ---------------------------------------------------------------------------

class SegmentComplexity(BaseModel):
    model_config = _STRICT

    level:                   ComplexityLevel
    cognitive_load:          str
    abstraction_level:       str
    prerequisite_concepts:   list[str]
    narration_style:         str
    quiz_difficulty:         str
    intervention_sensitivity: Annotated[float, Field(ge=0.0, le=1.0)]


# ---------------------------------------------------------------------------
# Slide
# ---------------------------------------------------------------------------

class Slide(BaseModel):
    model_config = _STRICT

    slide_id:           str
    title:              str
    bullets:            list[str]
    image_url:          AnyHttpUrl | None
    fallback_image_url: AnyHttpUrl | None


# ---------------------------------------------------------------------------
# NarrationTimestamp
# ---------------------------------------------------------------------------

class NarrationTimestamp(BaseModel):
    """One entry in narration.timestamps — maps a slide to its audio window.

    Binary search on start_ms to find the active slide at any audio position.
    slide_id matches a Slide.slide_id in the same segment's slides list.
    """
    model_config = _STRICT

    slide_id: str
    start_ms: Annotated[int, Field(ge=0)]
    end_ms:   Annotated[int, Field(ge=0)]


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------

class Narration(BaseModel):
    model_config = _STRICT

    script:         str
    audio_url:      str  # Supabase Storage signed URL — not validated as URI to allow relative paths in dev
    audio_provider: AudioProvider
    timestamps:     list[NarrationTimestamp]


# ---------------------------------------------------------------------------
# QuizQuestion
# ---------------------------------------------------------------------------

class QuizQuestion(BaseModel):
    model_config = _STRICT

    question_id:   str
    type:          QuizType
    question:      str
    options:       Annotated[list[str], Field(min_length=4)]
    correct_index: Annotated[int, Field(ge=0)]
    explanation:   str
    difficulty:    QuizDifficulty


# ---------------------------------------------------------------------------
# JargonEntry  (also used as GlossaryEntry — identical shape)
# ---------------------------------------------------------------------------

class JargonEntry(BaseModel):
    model_config = _STRICT

    term:       str
    definition: str


GlossaryEntry = JargonEntry  # same schema definition; separate alias for clarity


# ---------------------------------------------------------------------------
# SegmentInterventions
# ---------------------------------------------------------------------------

class SegmentInterventions(BaseModel):
    """Pre-generated intervention messages (3 per type, never call GPT at runtime).

    Each field is a fixed-length 3-tuple matching:
      JSON schema: { minItems: 3, maxItems: 3, items: { type: string } }
      TypeScript:  [string, string, string]
    """
    model_config = _STRICT

    distraction: Annotated[list[str], Field(min_length=3, max_length=3)]
    confusion:   Annotated[list[str], Field(min_length=3, max_length=3)]
    fatigue:     Annotated[list[str], Field(min_length=3, max_length=3)]


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------

class Segment(BaseModel):
    model_config = _STRICT

    segment_id:       str
    segment_index:    Annotated[int, Field(ge=0)]
    title:            str
    summary:          str
    complexity:       SegmentComplexity
    slides:           Annotated[list[Slide], Field(min_length=1)]
    narration:        Narration
    quiz:             list[QuizQuestion]
    teachback_prompt: str
    jargon:           list[JargonEntry]
    interventions:    SegmentInterventions


# ---------------------------------------------------------------------------
# LessonPackage  (root type — stored as JSONB in lessons.content)
# ---------------------------------------------------------------------------

class LessonPackage(BaseModel):
    """Complete lesson package produced by the content pipeline.

    Serialise to DB:   lesson.model_dump(mode="json")
    Deserialise from DB: LessonPackage.model_validate(row["content"])
    """
    model_config = _STRICT

    lesson_id:  UUID
    book_id:    UUID
    chapter_id: UUID
    created_at: str  # ISO-8601 datetime string — stored as text in JSONB
    metadata:   LessonMetadata
    segments:   Annotated[list[Segment], Field(min_length=1)]
    glossary:   list[GlossaryEntry]


# ---------------------------------------------------------------------------
# LessonRecord  (DB row from public.lessons — not stored in JSONB)
# ---------------------------------------------------------------------------

class LessonRecord(BaseModel):
    """Mirrors the public.lessons table row.  content is None until pipeline completes."""
    model_config = _STRICT

    lesson_id:        UUID
    user_id:          UUID
    title:            str | None
    status:           LessonStatus
    content:          LessonPackage | None
    source_file_path: str | None
    created_at:       str
    updated_at:       str
```

---

## Update `apps/api/app/schemas/__init__.py`

After creating `lesson.py`, update the `__init__.py` so the rest of the API can import cleanly from `app.schemas`:

```python
from app.schemas.lesson import (
    AudioProvider,
    ComplexityLevel,
    GlossaryEntry,
    JargonEntry,
    LessonMetadata,
    LessonPackage,
    LessonRecord,
    LessonStatus,
    Narration,
    NarrationTimestamp,
    QuizDifficulty,
    QuizQuestion,
    QuizType,
    Segment,
    SegmentComplexity,
    SegmentInterventions,
    Slide,
)

__all__ = [
    "AudioProvider",
    "ComplexityLevel",
    "GlossaryEntry",
    "JargonEntry",
    "LessonMetadata",
    "LessonPackage",
    "LessonRecord",
    "LessonStatus",
    "Narration",
    "NarrationTimestamp",
    "QuizDifficulty",
    "QuizQuestion",
    "QuizType",
    "Segment",
    "SegmentComplexity",
    "SegmentInterventions",
    "Slide",
]
```

---

## Usage in Pipeline Nodes

Each pipeline node that produces lesson package data should import and return typed output:

```python
# Example: package_builder node
from app.schemas import LessonPackage, Segment

async def package_builder_node(state: PipelineState) -> dict:
    package = LessonPackage(
        lesson_id=state["lesson_id"],
        book_id=state["book_id"],
        chapter_id=state["chapter_id"],
        created_at=datetime.utcnow().isoformat(),
        metadata=state["lesson_metadata"],
        segments=state["segments"],
        glossary=state["glossary"],
    )

    # Serialise to JSONB-compatible dict for DB write
    content_json = package.model_dump(mode="json")

    return {"lesson_package": content_json}
```

Reading back from DB:

```python
from app.schemas import LessonPackage

row = await db.fetchone("SELECT content FROM lessons WHERE lesson_id = $1", lesson_id)
package = LessonPackage.model_validate(row["content"])
```

---

## Validation Against JSON Schema

To confirm these models stay in sync with the JSON schema, add a unit test:

```python
# tests/unit/test_lesson_schema.py
import json
from pathlib import Path
import jsonschema
from app.schemas import LessonPackage

SCHEMA_PATH = Path(__file__).parents[4] / "packages/shared/lesson_package.schema.json"

def test_lesson_package_validates_against_json_schema():
    schema = json.loads(SCHEMA_PATH.read_text())
    # Build a minimal valid LessonPackage and confirm it passes the JSON schema
    sample = LessonPackage.model_validate({
        "lesson_id": "00000000-0000-0000-0000-000000000001",
        "book_id":   "00000000-0000-0000-0000-000000000002",
        "chapter_id":"00000000-0000-0000-0000-000000000003",
        "created_at": "2026-06-25T00:00:00Z",
        "metadata": {
            "title": "Test Lesson",
            "subject": "Testing",
            "total_segments": 1,
            "estimated_duration_mins": 5.0,
            "complexity_level": "medium",
        },
        "segments": [{
            "segment_id": "seg_1",
            "segment_index": 0,
            "title": "Segment 1",
            "summary": "Summary",
            "complexity": {
                "level": "medium",
                "cognitive_load": "moderate",
                "abstraction_level": "concrete",
                "prerequisite_concepts": [],
                "narration_style": "conversational",
                "quiz_difficulty": "medium",
                "intervention_sensitivity": 0.5,
            },
            "slides": [{
                "slide_id": "sl_1",
                "title": "Slide 1",
                "bullets": ["Point 1"],
                "image_url": None,
                "fallback_image_url": None,
            }],
            "narration": {
                "script": "Hello world.",
                "audio_url": "https://example.com/audio.mp3",
                "audio_provider": "elevenlabs",
                "timestamps": [{"slide_id": "sl_1", "start_ms": 0, "end_ms": 3000}],
            },
            "quiz": [],
            "teachback_prompt": "Explain in your own words.",
            "jargon": [],
            "interventions": {
                "distraction": ["A", "B", "C"],
                "confusion": ["D", "E", "F"],
                "fatigue": ["G", "H", "I"],
            },
        }],
        "glossary": [],
    })

    jsonschema.validate(
        instance=json.loads(sample.model_dump_json()),
        schema=schema,
    )
```

---

## Cross-Reference: TS Types → Pydantic Models

| TypeScript (`lesson.ts`) | Python (`schemas/lesson.py`) | Notes |
|---|---|---|
| `LessonStatus` | `LessonStatus` | Same 3 literals |
| `ComplexityLevel` | `ComplexityLevel` | Same 3 literals |
| `AudioProvider` | `AudioProvider` | Same 3 literals |
| `QuizType` | `QuizType` | Same 2 literals |
| `QuizDifficulty` | `QuizDifficulty` | Same 3 literals |
| `LessonMetadata` | `LessonMetadata` | Exact field match |
| `SegmentComplexity` | `SegmentComplexity` | Exact field match |
| `Slide` | `Slide` | `image_url`/`fallback_image_url` → `AnyHttpUrl \| None` |
| `NarrationTimestamp` | `NarrationTimestamp` | `start_ms`, `end_ms`, `slide_id` — snake_case throughout |
| `Narration` | `Narration` | Exact field match |
| `QuizQuestion` | `QuizQuestion` | `options: min_length=4` enforced |
| `JargonEntry` | `JargonEntry` | Exact field match |
| `GlossaryEntry` | `GlossaryEntry` | Alias of `JargonEntry` — same schema definition |
| `SegmentInterventions` | `SegmentInterventions` | TS `[string,string,string]` → `list[str]` min/max 3 |
| `Segment` | `Segment` | `slides: min_length=1` enforced |
| `LessonPackage` | `LessonPackage` | `segments: min_length=1` enforced |
| `LessonRecord` | `LessonRecord` | DB row wrapper — not in JSON schema |

---

## Definition of Done

- [ ] `apps/api/app/schemas/lesson.py` created with all models above
- [ ] `apps/api/app/schemas/__init__.py` re-exports all models
- [ ] Unit test in `tests/unit/test_lesson_schema.py` passes against the JSON schema
- [ ] `mypy app` passes with no errors on the new file
- [ ] `ruff check .` passes with no errors
