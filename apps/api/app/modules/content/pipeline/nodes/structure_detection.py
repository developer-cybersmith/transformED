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


# Coarsest → finest, so a merged section adopts the coarsest level among members.
_LEVEL_RANK = {"chapter": 0, "section": 1, "topic": 2}


def _merge_two(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge section ``b`` into ``a`` (a precedes b). Text-preserving: b's title
    and body are folded into a's body so no source text is ever dropped. The
    merged section keeps a's title, the coarsest level of the two, and spans
    both page ranges."""
    b_title = (b.get("title") or "").strip()
    b_body = (b.get("body") or "").strip()
    folded = "\n".join(part for part in (b_title, b_body) if part)
    merged_body = a.get("body", "")
    if folded:
        merged_body = f"{merged_body}\n\n{folded}" if merged_body else folded
    a_level = a.get("level", "topic")
    b_level = b.get("level", "topic")
    coarser = a_level if _LEVEL_RANK.get(a_level, 2) <= _LEVEL_RANK.get(b_level, 2) else b_level
    return {
        **a,
        "level": coarser,
        "body": merged_body,
        "page_start": min(a.get("page_start", 1), b.get("page_start", 1)),
        "page_end": max(a.get("page_end", 1), b.get("page_end", 1)),
    }


def coalesce_sections(
    sections: list[dict[str, Any]],
    *,
    min_chars: int,
    max_sections: int,
) -> list[dict[str, Any]]:
    """Bound an over-segmented section list without losing any source text.

    Two text-preserving passes (Story 2-16, RC-1):
      1. **Min-body floor** — any section whose ``body`` is shorter than
         ``min_chars`` is folded into the previously-kept section (or, if it is
         the first section, the next one is folded into it). This collapses
         numbered how-to steps that were mis-detected as headings.
      2. **Max-count cap** — while more than ``max_sections`` remain, repeatedly
         merge the adjacent pair with the smallest combined body length until the
         count reaches the cap.

    Bodies concatenate (with the absorbed section's title folded in), so the
    union of the returned bodies contains every original body — nothing is
    dropped. ``id``s are re-sequenced ``s0..sN``. A list already within bounds is
    returned unchanged (aside from id re-sequencing being a no-op)."""
    if not sections:
        return sections

    # ── Pass 1: min-body floor merge ─────────────────────────────────────────
    kept: list[dict[str, Any]] = []
    for sec in sections:
        body = (sec.get("body") or "").strip()
        if len(body) < min_chars and kept:
            kept[-1] = _merge_two(kept[-1], sec)
        else:
            kept.append(dict(sec))
    # A sub-floor first section couldn't merge backwards above; fold it forward.
    if len(kept) >= 2 and len((kept[0].get("body") or "").strip()) < min_chars:
        merged_first = _merge_two(kept[0], kept[1])
        kept = [merged_first, *kept[2:]]

    # ── Pass 2: max-count cap via O(n) contiguous bucketing ───────────────────
    # Distribute the kept sections into `max_sections` contiguous, near-equal
    # buckets and merge each bucket in place. Contiguous (order-preserving) and
    # O(n) — deliberately NOT an O(n^2) smallest-adjacent-pair search, which an
    # adversarial upload (tens of thousands of above-floor numbered lines) could
    # grind on in the ARQ worker before the downstream fan-out cap ever applies.
    if max_sections >= 1 and len(kept) > max_sections:
        n = len(kept)
        base, extra = divmod(n, max_sections)  # n > max_sections >= 1 => base >= 1
        bucketed: list[dict[str, Any]] = []
        idx = 0
        for b in range(max_sections):
            size = base + (1 if b < extra else 0)
            group = kept[idx : idx + size]
            idx += size
            merged = group[0]
            for nxt in group[1:]:
                merged = _merge_two(merged, nxt)
            bucketed.append(merged)
        kept = bucketed

    # ── Re-sequence ids ──────────────────────────────────────────────────────
    for i, sec in enumerate(kept):
        sec["id"] = f"s{i}"
    return kept
