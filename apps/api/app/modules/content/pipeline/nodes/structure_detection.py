"""
Rule-based document structure detection.

Consumes font_blocks (from pdftext via Story 1.2 extract_node) and raw_text
to produce heading candidates used by structure_node for LLM validation.

Heading detection uses two complementary strategies:
  1. Font-size clustering — spans significantly larger AND bold than the median
     are likely headings; relative size determines chapter/section/topic level.
  2. Regex on raw_text — numbered outlines and chapter prefixes that may not
     have distinct font metrics (e.g. copy-pasted or digitally-native PDFs).

Results from both strategies are merged and deduplicated by heading text.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

# Ordered most-specific → least-specific so a match against the more specific
# pattern is registered first and the less-specific one skips it.
_TOPIC_RE = re.compile(r"^(\d+\.\d+\.\d+)\.?\s+[A-Za-z].{2,}", re.MULTILINE)
_SECTION_RE = re.compile(r"^(\d+\.\d+)\.?\s+[A-Za-z].{2,}", re.MULTILINE)
_CHAPTER_RE = re.compile(r"^(?:Chapter\s+\d+[\.:]\s*.+|\d+\.\s+[A-Z].{3,})", re.MULTILINE)


def detect_headings(
    raw_text: str,
    font_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return heading candidates sorted by char_offset ascending.

    Each candidate: ``{"text": str, "level": "chapter"|"section"|"topic",
    "char_offset": int}``.
    Candidates are deduplicated by heading text (font wins over regex for level
    assignment when both detect the same heading).
    """
    # keyed by stripped text so font + regex detections of the same heading merge
    candidates: dict[str, dict[str, Any]] = {}

    # ── Strategy 1: font-size clustering ─────────────────────────────────────
    sizes = [b["font"]["size"] for b in font_blocks if b.get("font")]
    if sizes:
        median_size = statistics.median(sizes)
        threshold = median_size * 1.25
        for block in font_blocks:
            font = block.get("font", {})
            if font.get("size", 0) >= threshold and font.get("bold", False):
                text = block.get("text", "").strip()
                if len(text) > 3:
                    offset = raw_text.find(text)
                    if offset < 0:
                        continue
                    size = font["size"]
                    if size >= threshold * 1.15:
                        level = "chapter"
                    elif size >= threshold * 1.05:
                        level = "section"
                    else:
                        level = "topic"
                    if text not in candidates:
                        candidates[text] = {
                            "text": text,
                            "level": level,
                            "char_offset": offset,
                        }

    # ── Strategy 2: regex on raw_text ────────────────────────────────────────
    for match in _TOPIC_RE.finditer(raw_text):
        text = match.group(0).strip()
        if text not in candidates:
            candidates[text] = {
                "text": text,
                "level": "topic",
                "char_offset": match.start(),
            }

    for match in _SECTION_RE.finditer(raw_text):
        text = match.group(0).strip()
        if text not in candidates:
            candidates[text] = {
                "text": text,
                "level": "section",
                "char_offset": match.start(),
            }

    for match in _CHAPTER_RE.finditer(raw_text):
        text = match.group(0).strip()
        if text not in candidates:
            candidates[text] = {
                "text": text,
                "level": "chapter",
                "char_offset": match.start(),
            }

    return sorted(candidates.values(), key=lambda c: c["char_offset"])


def estimate_page(char_offset: int, total_chars: int, total_pages: int) -> int:
    """Return 1-indexed estimated page number for a character offset."""
    return max(1, int(char_offset / max(total_chars, 1) * total_pages) + 1)


def build_section_bodies(
    raw_text: str,
    candidates: list[dict[str, Any]],
    total_pages: int,
) -> list[dict[str, Any]]:
    """Build flat section list from heading candidates and raw text.

    Each section dict has keys: id, title, level, body, page_start, page_end.
    Guarantees at least one section — falls back to a single chapter-level
    section containing all raw_text when no candidates are found.
    """
    total_chars = len(raw_text)

    if not candidates:
        return [
            {
                "id": "s0",
                "title": "Document",
                "level": "chapter",
                "body": raw_text,
                "page_start": 1,
                "page_end": max(total_pages, 1),
            }
        ]

    sections: list[dict[str, Any]] = []
    for i, cand in enumerate(candidates):
        start_offset = cand["char_offset"] + len(cand["text"])
        end_offset = candidates[i + 1]["char_offset"] if i + 1 < len(candidates) else total_chars

        body = raw_text[start_offset:end_offset].strip()
        page_start = estimate_page(cand["char_offset"], total_chars, total_pages)
        if i + 1 < len(candidates):
            next_page = estimate_page(candidates[i + 1]["char_offset"], total_chars, total_pages)
            page_end = max(page_start, next_page - 1)
        else:
            page_end = max(total_pages, page_start)

        sections.append(
            {
                "id": f"s{i}",
                "title": cand["text"],
                "level": cand["level"],
                "body": body,
                "page_start": page_start,
                "page_end": page_end,
            }
        )

    return sections
