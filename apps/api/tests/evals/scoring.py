"""
Rule-based / heuristic scoring for the S2-14 eval harness (Story 2-14 AC-3).

Both `score_slide_quality` and `score_quiz_relevance` are DELIBERATELY
rule-based, not semantic/NLP-based. Neither calls an LLM — spending LLM
budget to score a pipeline run defeats the purpose of a cheap, frequent
regression-catching harness (the same cost-discipline CLAUDE.md applies to
pipeline nodes, applied here to post-hoc scoring instead). This means the
"relevance" score is a weak keyword-overlap proxy, not true topical
relevance — a well-written question that paraphrases its segment's
vocabulary instead of reusing it will score lower than it deserves. This
limitation is intentional and documented, not hidden. A genuine semantic
scoring pass (e.g. an LLM-as-judge step) would be a deliberate follow-up
story, not a silent upgrade here.

Both functions accept a `LessonPackage`-SHAPED DICT (not a Pydantic
instance) — the eval runner works with `run_pipeline()`'s raw dict return
value, mirroring `package_builder_node`'s own dict-first-validate-second
convention (see `docs/stories/2-11-package-builder-node.md`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_MAX_BULLET_CHARS = 200  # beyond this a bullet reads as "wall of text", not a bullet
_MIN_SLIDES_PER_SEGMENT = 1
_MAX_SLIDES_PER_SEGMENT = 8
_REQUIRED_QUIZ_OPTIONS = 4
_STOPWORDS = frozenset(
    "a an the of to in on for and or is are was were be been being this that "
    "with as by from at it its into your you their they he she we".split()
)


@dataclass
class EvalScore:
    """Result of a single scoring pass. `value` is a heuristic in [0, 1] —
    NOT a calibrated probability or a guarantee of quality; see this
    module's docstring. `issues` lists every concrete deduction reason, one
    string per finding, so a regression can be diagnosed without re-running
    the scorer under a debugger."""

    value: float
    issues: list[str] = field(default_factory=list)


def _keyword_set(text: str) -> set[str]:
    # 2026-07-17 review finding (Blind Hunter): a `len(w) > 2` filter drops
    # legitimate 2-char science terms this pipeline's textbook content will
    # routinely contain (e.g. "pH") while keeping equally-short 3-char ones
    # ("DNA", "RNA") purely by coincidence of length — an unintentional bias
    # unrelated to the documented "weak keyword-overlap proxy" limitation.
    # Loosened to >= 2 (case preserved on the original word, not the lookup,
    # since lower() already applied above).
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) >= 2}


def score_slide_quality(lesson_package: dict[str, Any]) -> EvalScore:
    """Heuristic slide-deck quality: non-blank titles, 1-8 bullets per
    slide (mirrors slide_generator_node's own AC-4 band), no blank
    bullets, no single bullet over `_MAX_BULLET_CHARS` (a "wall of text"
    proxy for a slide that isn't actually slide-shaped)."""
    segments = lesson_package.get("segments", [])
    if not isinstance(segments, list) or not segments:
        return EvalScore(value=0.0, issues=["lesson_package has no segments"])

    total_slides = 0
    passing_slides = 0
    issues: list[str] = []

    for segment in segments:
        segment_id = (
            segment.get("segment_id", "<unknown>") if isinstance(segment, dict) else "<unknown>"
        )
        slides = segment.get("slides", []) if isinstance(segment, dict) else []
        if not slides:
            issues.append(f"segment {segment_id}: zero slides")
            continue
        # 2026-07-17 review finding (Blind Hunter + Acceptance Auditor,
        # independently): this band check originally only appended an issue
        # string and never affected passing_slides/the score itself — a
        # segment with 9 otherwise-perfect slides scored a perfect 1.0
        # despite violating the very band this function's own docstring
        # says it checks. A band violation is a SEGMENT-level property, so
        # it now fails every slide in that segment (matches AC-3's intent:
        # a >8-slide segment "should score lower and report a matching
        # issue string" — value AND issue, not issue alone).
        band_violation = not (_MIN_SLIDES_PER_SEGMENT <= len(slides) <= _MAX_SLIDES_PER_SEGMENT)
        if band_violation:
            issues.append(f"segment {segment_id}: {len(slides)} slides outside the 1-8 band")

        for slide in slides:
            total_slides += 1
            slide_id = (
                slide.get("slide_id", "<unknown>") if isinstance(slide, dict) else "<unknown>"
            )
            title = (slide.get("title") or "").strip() if isinstance(slide, dict) else ""
            bullets = slide.get("bullets", []) if isinstance(slide, dict) else []

            slide_ok = not band_violation
            if not title:
                issues.append(f"slide {slide_id}: blank title")
                slide_ok = False
            if not bullets:
                issues.append(f"slide {slide_id}: zero bullets")
                slide_ok = False
            else:
                for i, bullet in enumerate(bullets):
                    bullet_text = (bullet or "").strip() if isinstance(bullet, str) else ""
                    if not bullet_text:
                        issues.append(f"slide {slide_id}: blank bullet at index {i}")
                        slide_ok = False
                    elif len(bullet_text) > _MAX_BULLET_CHARS:
                        issues.append(
                            f"slide {slide_id}: bullet {i} exceeds "
                            f"{_MAX_BULLET_CHARS} chars (wall of text)"
                        )
                        slide_ok = False
            if slide_ok:
                passing_slides += 1

    if total_slides == 0:
        return EvalScore(value=0.0, issues=issues or ["no slides found across any segment"])

    return EvalScore(value=passing_slides / total_slides, issues=issues)


def score_quiz_relevance(lesson_package: dict[str, Any]) -> EvalScore:
    """Heuristic quiz well-formedness + weak topical-relevance proxy
    (keyword overlap between each question's text and its segment's
    title/summary — NOT semantic similarity, see module docstring)."""
    segments = lesson_package.get("segments", [])
    if not isinstance(segments, list) or not segments:
        return EvalScore(value=0.0, issues=["lesson_package has no segments"])

    total_questions = 0
    passing_questions = 0
    issues: list[str] = []

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_id = segment.get("segment_id", "<unknown>")
        segment_keywords = _keyword_set(f"{segment.get('title', '')} {segment.get('summary', '')}")
        quiz = segment.get("quiz", [])

        for question in quiz:
            if not isinstance(question, dict):
                continue
            total_questions += 1
            question_id = question.get("question_id", "<unknown>")

            options = question.get("options", [])
            correct_index = question.get("correct_index")
            question_text = (question.get("question") or "").strip()
            explanation = (question.get("explanation") or "").strip()

            question_ok = True
            if len(options) != _REQUIRED_QUIZ_OPTIONS:
                issues.append(
                    f"question {question_id}: {len(options)} options, "
                    f"expected {_REQUIRED_QUIZ_OPTIONS}"
                )
                question_ok = False
            if not isinstance(correct_index, int) or not (0 <= correct_index < len(options)):
                issues.append(
                    f"question {question_id}: correct_index {correct_index!r} out of range"
                )
                question_ok = False
            if not question_text:
                issues.append(f"question {question_id}: blank question text")
                question_ok = False
            if not explanation:
                issues.append(f"question {question_id}: blank explanation")
                question_ok = False

            if segment_keywords:
                question_keywords = _keyword_set(question_text)
                overlap = segment_keywords & question_keywords
                if not overlap:
                    issues.append(
                        f"question {question_id}: no keyword overlap with segment {segment_id} "
                        "(weak relevance proxy — may be a false positive, see module docstring)"
                    )
                    question_ok = False

            if question_ok:
                passing_questions += 1

    if total_questions == 0:
        return EvalScore(value=0.0, issues=issues or ["no quiz questions found across any segment"])

    return EvalScore(value=passing_questions / total_questions, issues=issues)
