"""
Teach-back rubric prompt and structured scorer.

Sprint 0: tests score_teachback() in isolation.
Sprint 1: service.py imports and calls score_teachback() from the teachback endpoint.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.config import get_settings

if TYPE_CHECKING:
    from app.providers.llm.openai import OpenAILLMProvider  # noqa: F401


class TeachbackScoreResult(BaseModel):
    """Structured output from GPT-4o-mini teach-back evaluation."""

    score: int = Field(ge=0, le=100, description="Overall score 0-100 (weighted rubric)")
    praise: str = Field(description="Specific, encouraging feedback on what the student did well")
    correction: str = Field(
        description="Constructive feedback on gaps; empty string '' when score >= 90"
    )
    concepts_hit: list[str] = Field(
        description="Key concepts from the segment the student demonstrated understanding of"
    )
    concepts_missed: list[str] = Field(
        description="Key concepts from the segment the student omitted or got wrong"
    )


TEACHBACK_SYSTEM_PROMPT = """You are an expert learning assessment AI evaluating a student's teach-back response.

Teach-back is a study technique where students explain a concept in their own words to demonstrate understanding. Evaluate the response using three rubric criteria:

  Accuracy     (40%): Are the facts, concepts, and explanations correct?
  Completeness (35%): Does the response cover the key concepts from the segment?
  Clarity      (25%): Is the explanation clear, well-structured, and understandable?

Score formula:
  score = round(accuracy_score * 0.40 + completeness_score * 0.35 + clarity_score * 0.25)
  where each sub-score is independently assessed on a 0-100 scale.

Return a JSON object with exactly these fields:
  score          integer 0-100 (weighted rubric total)
  praise         1-2 sentences of specific, encouraging feedback on what the student did well
  correction     1-2 sentences of constructive feedback on gaps or inaccuracies;
                 use an EMPTY STRING "" (not null, not "None") when score >= 90
  concepts_hit   list of key concepts from the segment that the student demonstrated
  concepts_missed list of key concepts from the segment that the student omitted or got wrong

Guidelines:
- Be encouraging and constructive; frame gaps as learning opportunities
- Do not use clinical, diagnostic, or ability-measurement language
- Focus on the learning content, not the student as a person
- concepts_hit + concepts_missed together must cover ALL key concepts provided
"""


def build_teachback_user_prompt(
    *,
    topic: str,
    key_concepts: list[str],
    response_text: str,
) -> str:
    """Build the user-turn message for the teach-back rubric prompt."""
    if key_concepts:
        concepts_block = "\n".join(f"- {c}" for c in key_concepts)
    else:
        concepts_block = "(no key concepts specified)"
    return (
        f"Segment Topic: {topic}\n\n"
        f"Key Concepts from Segment:\n{concepts_block}\n\n"
        f"Student Teach-Back Response:\n{response_text}"
    )


async def score_teachback(
    *,
    topic: str,
    key_concepts: list[str],
    response_text: str,
    lesson_id: str,
    provider: Any,
) -> TeachbackScoreResult:
    """Score a student's typed teach-back response using GPT-4o-mini.

    Parameters
    ----------
    topic:         Segment topic the student was taught.
    key_concepts:  Key concepts from the lesson plan for this segment.
    response_text: Student's typed explanation (typed input only, no STT).
    lesson_id:     Lesson ID passed to the provider constructor for cost tracking.
    provider:      OpenAILLMProvider instance initialised with lesson_id.
    """
    settings = get_settings()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": TEACHBACK_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_teachback_user_prompt(
                topic=topic,
                key_concepts=key_concepts,
                response_text=response_text,
            ),
        },
    ]
    result: TeachbackScoreResult = await provider.complete_structured(
        messages=messages,
        model=settings.llm_mini,
        response_format=TeachbackScoreResult,
    )
    return result
