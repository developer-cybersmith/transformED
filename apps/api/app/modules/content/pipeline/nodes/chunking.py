"""
Token-bounded chunking helpers for the content pipeline.

All functions here are pure (no I/O, no DB calls). chunk_node in graph.py
handles DB writes; this module only handles text splitting and token counting.

Tokenizer: cl100k_base (used by text-embedding-3-small and GPT-4o).
Algorithm: greedy paragraph-then-sentence packing with token-level overlap.
"""

from __future__ import annotations

import re
from typing import Any

_PARA_SEP = re.compile(r"\n\n+")
_SENT_SEP = re.compile(r"(?<=[.!?])\s+")


def count_tokens(text: str, encoding: Any) -> int:
    return len(encoding.encode(text))


def split_into_segments(text: str) -> list[str]:
    """Split text into paragraph/sentence segments, preserving all content.

    Returns a flat list of non-empty string segments. Paragraph breaks are
    preserved as "\\n\\n" sentinels so assembled chunks retain structure.
    """
    paragraphs = _PARA_SEP.split(text)
    segments: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        sentences = _SENT_SEP.split(para)
        for s in sentences[:-1]:
            segments.append(s + " ")
        segments.append(sentences[-1])
        segments.append("\n\n")
    return [s for s in segments if s.strip()]


def chunk_section(
    section: dict[str, Any],
    encoding: Any,
    target: int,
    overlap: int,
) -> list[dict[str, Any]]:
    """Split a single section into token-bounded chunks with overlap.

    Oversized single segments (longer than target) are emitted as-is — content
    is never truncated. Overlap is built from the exact token tail of the
    previous chunk via encoding.decode(tokens[-overlap:]).
    """
    body: str = section.get("body", "")
    section_id: str = section["id"]
    section_title: str = section.get("title", "")
    page_start: int = section.get("page_start", 1)
    page_end: int = section.get("page_end", 1)

    if not body.strip():
        return [
            {
                "id": f"{section_id}_c0",
                "section_id": section_id,
                "text": "",
                "token_count": 0,
                "section_title": section_title,
                "page_start": page_start,
                "page_end": page_end,
            }
        ]

    segments = split_into_segments(body)
    chunks: list[dict[str, Any]] = []
    buffer: list[str] = []
    buffer_tokens = 0
    overlap_prefix = ""

    for seg in segments:
        seg_tokens = count_tokens(seg, encoding)
        if buffer_tokens + seg_tokens > target and buffer:
            chunk_text = (overlap_prefix + "".join(buffer)).strip()
            chunk_tokens = count_tokens(chunk_text, encoding)
            chunks.append({
                "id": f"{section_id}_c{len(chunks)}",
                "section_id": section_id,
                "text": chunk_text,
                "token_count": chunk_tokens,
                "section_title": section_title,
                "page_start": page_start,
                "page_end": page_end,
            })
            full_tokens = encoding.encode(chunk_text)
            overlap_prefix = encoding.decode(full_tokens[-overlap:]) if len(full_tokens) >= overlap else chunk_text
            buffer = [seg]
            buffer_tokens = seg_tokens
        else:
            buffer.append(seg)
            buffer_tokens += seg_tokens

    if buffer:
        chunk_text = (overlap_prefix + "".join(buffer)).strip()
        chunk_tokens = count_tokens(chunk_text, encoding)
        chunks.append({
            "id": f"{section_id}_c{len(chunks)}",
            "section_id": section_id,
            "text": chunk_text,
            "token_count": chunk_tokens,
            "section_title": section_title,
            "page_start": page_start,
            "page_end": page_end,
        })

    return chunks


def chunk_sections(
    sections: list[dict[str, Any]],
    target: int,
    overlap: int,
    tokenizer_name: str,
) -> list[dict[str, Any]]:
    """Split all sections into token-bounded chunks.

    tiktoken.get_encoding() is called once (downloading the vocab file on first
    call then cached by tiktoken). Returns a flat list ordered by section order
    then chunk position within each section.
    """
    import tiktoken  # lazy — not installed in test env; mocked via sys.modules

    encoding = tiktoken.get_encoding(tokenizer_name)
    result: list[dict[str, Any]] = []
    for section in sections:
        result.extend(chunk_section(section, encoding, target, overlap))
    return result
