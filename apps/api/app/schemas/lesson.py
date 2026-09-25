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

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------

_STRICT = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Primitive type aliases
# ---------------------------------------------------------------------------

LessonStatus = Literal["generating", "ready", "failed"]
ComplexityLevel = Literal["low", "medium", "high"]
# frozen — see lesson_package.schema.json. "sixtydb" added by Story 232 —
# FROZEN CONTRACT CHANGE, requires the 4-developer-reviewed PR per CLAUDE.md/PRD §16
# before merge, in addition to this story's own 6-agent review.
AudioProvider = Literal["sarvam", "azure", "browser", "sixtydb"]
QuizType = Literal["mcq", "concept_check"]
QuizDifficulty = Literal["easy", "medium", "hard"]
LessonTier = Literal["T1", "T2", "T3"]  # Story 2-2 — Learner Mode content-depth tier
VALID_TIERS: frozenset[str] = frozenset(("T1", "T2", "T3"))
DEFAULT_TIER = "T2"  # Story S2-LM3/LM4/LM5 (2026-07-17) — single source of truth for the
# tier default, previously duplicated independently in graph.py and router.py
# (code review finding, Blind Hunter) — both now import from here.


# ---------------------------------------------------------------------------
# Duration budget (Story S5-4, amended by Story S5-5 — issues #230 / #233)
# ---------------------------------------------------------------------------
# NOT part of the lesson_package.schema.json mirror — shared constants living
# alongside VALID_TIERS/DEFAULT_TIER by the same precedent (one source of
# truth, imported rather than retyped). No packages/shared change.
#
# The tier enum means DURATION, specifically the MINIMUM MINUTES OF SPOKEN
# NARRATION a lesson must deliver (product/CEO decision, 2026-09-25):
#
#     T1 = at least 45 min of narration
#     T2 = at least 30 min
#     T3 = at least 15 min
#
# This REPLACES S5-4's shipped reading, which took the same numbers as total
# SEAT time and gave narration a 65% share (T1 -> 29.25 min). Under that
# reading the headline number was never the number being enforced: a student
# selecting 45 minutes was promised 45 and the pipeline targeted 29. S5-4 had
# already merged (6f19918) by the time the intent was clarified, so unlike an
# amendment-before-merge this is a genuine behaviour change to shipped code —
# recorded as D189.
#
# Consequence for the other two budgets: quiz and tutor Q&A time is now
# ADDITIVE to the narration minimum rather than carved out of it, so a T1
# session runs ~45 min of narration + ~7 min of quiz + 4.5 min of Q&A. Their
# absolute values are unchanged — the quiz recalibration they came from fixed
# a real defect (a per-segment count that multiplied by segment count) and is
# independent of this semantics change.
TIER_MIN_NARRATION_MINUTES: dict[str, int] = {"T1": 45, "T2": 30, "T3": 15}

# Alias kept so callers that legitimately mean "the tier's headline minutes"
# (labels, reports) keep reading one source of truth.
TIER_SEAT_MINUTES: dict[str, int] = TIER_MIN_NARRATION_MINUTES

# Quiz and Q&A time per tier, in SECONDS. Previously expressed as shares of
# seat time; stated directly now that narration is no longer a share of
# anything.
TIER_QUIZ_SECONDS: dict[str, int] = {"T1": 405, "T2": 270, "T3": 135}
TIER_QA_SECONDS: dict[str, int] = {"T1": 270, "T2": 180, "T3": 90}


# ---------------------------------------------------------------------------
# Topic count by tier (Story 233, piece 1 of 4 — issue #233)
# ---------------------------------------------------------------------------
# Every lesson teaches exactly 1 topic (15-min, T3) or 2 topics (30/45-min,
# T1/T2) — never however many sections a chapter happens to have.
# `topic_selection_node` reads this to decide how many topics to collapse
# `state["sections"]` down to. Same duration meaning as TIER_SEAT_MINUTES
# above, not a separate tier semantics.
TIER_TOPIC_COUNT: dict[str, int] = {"T1": 2, "T2": 2, "T3": 1}


def _seat_minutes(tier: str | None) -> int:
    """Seat minutes for *tier*, falling back to the default tier.

    Soft fallback rather than a raise, matching `_tier_slide_budget_per_segment`'s
    convention: a budget hint must never be the thing that crashes a lesson the
    pipeline has already paid premium LLM spend for.
    """
    return TIER_SEAT_MINUTES.get(tier or "", TIER_SEAT_MINUTES[DEFAULT_TIER])


def narration_budget_minutes(tier: str | None) -> float:
    """MINIMUM minutes of spoken narration for *tier* (T1 45 / T2 30 / T3 15).

    A floor, not a target and not a ceiling: a lesson running longer has
    satisfied it. A lesson running shorter has satisfied it only if the
    chapter's own text could not support more — in which case the shortfall is
    reported (`duration_report.outcome == "content_limited"`), never padded.
    """
    return float(_seat_minutes(tier))


def quiz_budget_seconds(tier: str | None) -> float:
    """Seconds of the session *tier* budgets for quizzing (T1 405 / T2 270 / T3 135).

    Divided by `settings.quiz_seconds_per_question` this becomes the lesson's
    TOTAL question count, allocated across segments — replacing the pre-S5-4
    per-segment band, which multiplied by segment count and at 15 segments
    consumed 19-31 minutes of a 45-minute lesson on its own.
    """
    return float(TIER_QUIZ_SECONDS.get(tier or "", TIER_QUIZ_SECONDS[DEFAULT_TIER]))


def qa_budget_seconds(tier: str | None) -> int:
    """Tutor Q&A phase length for *tier* (T1 270 / T2 180 / T3 90 seconds).

    Returns `int` because it supplies `config.py`'s `learner_tier_*_qa_seconds`
    defaults, which are typed `int`. Under S5-4 this window is SUBTRACTED from
    the advertised duration; before S5-4 it was added on top of it (600 s of Q&A
    after a nominally 45-minute lesson).
    """
    return int(TIER_QA_SECONDS.get(tier or "", TIER_QA_SECONDS[DEFAULT_TIER]))


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
    # str, not AnyHttpUrl (Story 2-11 review): both are private-bucket storage
    # paths (e.g. "{lesson_id}/{slide_id}.png"), not URLs — a signed URL baked
    # into stored lessons.content JSONB would expire (Supabase max ~7 days)
    # long before a generated lesson is necessarily viewed. Resolving a path
    # to a fresh signed URL at lesson-view time is a separate, future
    # component's responsibility, not package_builder's. Matches
    # Narration.audio_url's existing plain-str type below.
    image_url: str | None
    fallback_image_url: str | None


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
# CaptionLine  (Story 4-29 — BR-6)
# ---------------------------------------------------------------------------


class CaptionLine(BaseModel):
    """One timed caption line within a segment's narration audio.

    Populated by ``_split_into_caption_lines()`` in ``package_builder_node``.
    Duration is distributed proportionally by character count from the
    tinytag-measured audio duration. Empty list when duration is unknown
    (browser-fallback path / tinytag failure) — see Story 4-29 AC5.
    """

    model_config = _STRICT

    text: str
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
    # Story 4-29 (BR-6): line-level caption timing. Defaults to [] so existing
    # lesson records and fixtures validate without a migration — retroactive-field
    # pattern matching tier/avatar_intro_url. Not in lesson_package.schema.json's
    # Narration.required for the same reason.
    caption_lines: list[CaptionLine] = Field(default_factory=list)


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
    # Story 1-5 — avatar cached-clip URLs (signed Supabase Storage URLs, or None
    # when unavailable/not yet populated). Defaults to None, matching `tier`'s
    # retroactive-field pattern above — package_builder_node does not populate
    # these yet (Dev 1 follow-up, tracked in
    # docs/proposals/avatar-fields-schema-change.md); every lesson validated
    # today will have all 3 fields default to None. Vendor-agnostic: the
    # HeyGen provider that would have populated these was removed as
    # dead/unwired code (D144) — these fields are unaffected and remain for
    # a future implementation.
    avatar_intro_url: str | None = None
    avatar_static_url: str | None = None
    avatar_outro_url: str | None = None


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
