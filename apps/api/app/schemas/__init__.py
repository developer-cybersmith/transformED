from typing import Literal

from pydantic import BaseModel, Field

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


class SectionBoundary(BaseModel):
    id: str
    title: str
    level: Literal["chapter", "section", "topic"]
    body: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)


class DocumentStructure(BaseModel):
    sections: list[SectionBoundary] = Field(min_length=1)


__all__ = [
    "AudioProvider",
    "ComplexityLevel",
    "DocumentStructure",
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
    "SectionBoundary",
    "Slide",
]
