"""Value types for the chapter-detection ladder.

Deliberately plain dataclasses over primitives: the whole module is pure
functions over ``(page_count, toc, page_texts)`` so every rung is testable
against a captured fixture with no PDF, no database and no Supabase mock
(binding rule 2 — a mock written by the consumer cannot disconfirm the
consumer's belief).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: One value per rung of the ladder. Matches the CHECK constraint added by
#: supabase/migrations/20260803000000_chapters_book_scoped.sql.
Rung = Literal["toc", "contents", "heading", "font", "fallback"]

RUNGS: tuple[Rung, ...] = ("toc", "contents", "heading", "font", "fallback")


@dataclass(frozen=True, slots=True)
class DetectedChapter:
    """A chapter boundary. `page_start`/`page_end` are 0-based PDF page indices,
    inclusive — the same convention `_build_sub_pdf` uses in Phase 4."""

    title: str
    page_start: int
    page_end: int
    chapter_index: int
    boundary_confidence: Rung

    @property
    def page_span(self) -> int:
        return self.page_end - self.page_start + 1


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """What the ladder produced, and which rung produced it.

    `raw_chapters` is pre-filter: it is what the rung detected, including front
    and back matter. `chapters` is what a student should be offered. Tests assert
    against both, because "the rung found 27 entries" and "22 of them are
    teachable" are different claims and conflating them hides filter bugs.
    """

    chapters: list[DetectedChapter]
    rung: Rung
    raw_chapters: list[DetectedChapter] = field(default_factory=list)

    @property
    def raw_count(self) -> int:
        return len(self.raw_chapters)
