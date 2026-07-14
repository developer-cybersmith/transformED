"""
Pydantic v2 models for the HIE lesson package.

Python mirror of:
  packages/shared/types/lesson.ts
  packages/shared/lesson_package.schema.json  ← authoritative source

Every model uses ConfigDict(extra="forbid") to enforce additionalProperties: false
from the JSON schema at the Python layer.

FROZEN CONTRACT — changes require a PR reviewed by all 4 developers (PRD §16).
Never modify these models without also updating lesson.ts and the JSON schema.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------

_STRICT = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Primitive type aliases
# ---------------------------------------------------------------------------

LessonStatus = Literal["generating", "ready", "failed"]
ComplexityLevel = Literal["low", "medium", "high"]
AudioProvider = Literal["sarvam", "azure", "browser"]  # frozen — see lesson_package.schema.json
QuizType = Literal["mcq", "concept_check"]
QuizDifficulty = Literal["easy", "medium", "hard"]
LessonTier = Literal["T1", "T2", "T3"]  # Story 2-2 — Learner Mode content-depth tier


# ---------------------------------------------------------------------------
# LessonMetadata
# ---------------------------------------------------------------------------


class LessonMetadata(BaseModel):
    model_config = _STRICT

    title: str
    subject: str
    total_segments: Annotated[int, Field(ge=1)]
    estimated_duration_mins: Annotated[float, Field(ge=0)]
    complexity_level: str  # free string per schema; ComplexityLevel if constraining later
    tier: LessonTier = "T2"  # Story 2-2 — defaults T2 so existing callers/fixtures are unaffected


# ---------------------------------------------------------------------------
# SegmentComplexity
# ---------------------------------------------------------------------------


class SegmentComplexity(BaseModel):
    model_config = _STRICT

    level: ComplexityLevel
    cognitive_load: str
    abstraction_level: str
    prerequisite_concepts: list[str]
    narration_style: str
    quiz_difficulty: str
    intervention_sensitivity: Annotated[float, Field(ge=0.0, le=1.0)]


# ---------------------------------------------------------------------------
# Slide
# ---------------------------------------------------------------------------


class Slide(BaseModel):
    model_config = _STRICT

    slide_id: str
    title: str
    bullets: list[str]
    image_url: AnyHttpUrl | None
    fallback_image_url: AnyHttpUrl | None


# ---------------------------------------------------------------------------
# NarrationTimestamp
# ---------------------------------------------------------------------------


class NarrationTimestamp(BaseModel):
    """Maps a slide to its audio window via binary search on start_ms."""

    model_config = _STRICT

    slide_id: str
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(ge=0)]


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------


class Narration(BaseModel):
    model_config = _STRICT

    script: str
    audio_url: str  # Supabase Storage signed URL — relative paths allowed in dev
    audio_provider: AudioProvider
    timestamps: list[NarrationTimestamp]


# ---------------------------------------------------------------------------
# QuizQuestion
# ---------------------------------------------------------------------------


class QuizQuestion(BaseModel):
    model_config = _STRICT

    question_id: str
    type: QuizType
    question: str
    options: Annotated[list[str], Field(min_length=4)]
    correct_index: Annotated[int, Field(ge=0)]
    explanation: str
    difficulty: QuizDifficulty


# ---------------------------------------------------------------------------
# JargonEntry / GlossaryEntry
# ---------------------------------------------------------------------------


class JargonEntry(BaseModel):
    model_config = _STRICT

    term: str
    definition: str


GlossaryEntry = JargonEntry  # identical schema definition; separate alias for clarity


# ---------------------------------------------------------------------------
# SegmentInterventions
# ---------------------------------------------------------------------------


class SegmentInterventions(BaseModel):
    """Pre-generated intervention messages — 3 per type, never call LLM at runtime."""

    model_config = _STRICT

    distraction: Annotated[list[str], Field(min_length=3, max_length=3)]
    confusion: Annotated[list[str], Field(min_length=3, max_length=3)]
    fatigue: Annotated[list[str], Field(min_length=3, max_length=3)]


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------


class Segment(BaseModel):
    model_config = _STRICT

    segment_id: str
    segment_index: Annotated[int, Field(ge=0)]
    title: str
    summary: str
    complexity: SegmentComplexity
    slides: Annotated[list[Slide], Field(min_length=1)]
    narration: Narration
    quiz: list[QuizQuestion]
    teachback_prompt: str
    jargon: list[JargonEntry]
    interventions: SegmentInterventions


# ---------------------------------------------------------------------------
# LessonPackage  (root — stored as JSONB in lessons.content)
# ---------------------------------------------------------------------------


class LessonPackage(BaseModel):
    """Complete lesson package produced by the content pipeline.

    Serialize to DB:   package.model_dump(mode="json")
    Deserialize from DB: LessonPackage.model_validate(row["content"])
    """

    model_config = _STRICT

    lesson_id: UUID
    book_id: UUID
    chapter_id: UUID
    created_at: str  # ISO-8601 datetime stored as text in JSONB
    metadata: LessonMetadata
    segments: Annotated[list[Segment], Field(min_length=1)]
    glossary: list[GlossaryEntry]


# ---------------------------------------------------------------------------
# LessonRecord  (DB row from public.lessons — not stored in JSONB)
# ---------------------------------------------------------------------------


class LessonRecord(BaseModel):
    """Mirrors the public.lessons table row. content is None until pipeline completes."""

    model_config = _STRICT

    lesson_id: UUID
    user_id: UUID
    title: str | None
    status: LessonStatus
    content: LessonPackage | None
    source_file_path: str | None
    created_at: str
    updated_at: str
