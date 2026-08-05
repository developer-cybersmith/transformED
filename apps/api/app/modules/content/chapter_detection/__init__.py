"""Chapter detection for book-scale ingestion (Story 1-10, Phase 3).

Pure functions over ``(page_count, toc, page_texts)`` — no PDF handle, no
database, no network — so every rung is testable against a captured fixture
rather than a mock (binding rule 2).

Evidence the design rests on: docs/reports/PHASE-1-TOC-SPIKE.md.
Design and rationale: docs/bmad/phase-3-chapter-detection-plan.md.
"""

from .ladder import detect_chapters
from .types import RUNGS, DetectedChapter, DetectionResult, Rung

__all__ = ["RUNGS", "DetectedChapter", "DetectionResult", "Rung", "detect_chapters"]
