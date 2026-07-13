"""
Content pipeline LangGraph graph.

Node order (14 nodes)
---------------------
 1. extract               PDF → raw text + images
 2. structure             Raw text → sections/chapters
 3. chunk                 Sections → token-sized chunks
 4. embed                 Chunks → vector embeddings (stored in Supabase pgvector)
 5. lesson_planner        Chunks → lesson plan (learning objectives, structure)
 6. slide_generator       Lesson plan → slide deck JSON
 7. summarise_segment     Each segment → short summary for narration intro
 8. quiz_generator        Each segment → multiple-choice questions
 9. segment_complexity    Each segment → complexity / readability score
10. jargon_extractor      Each segment → glossary of technical terms
11. intervention_messages Complexity + jargon → proactive intervention prompts
12. narration_generator   Slides + summaries → narration scripts
13. tts_node              Narration scripts → audio + word timestamps
14. image_generator       Slide content → AI-generated illustration URLs
15. package_builder       All outputs → final lesson JSON package

Architecture constraints
------------------------
- MemorySaver for in-process checkpointing (PostgresSaver is BANNED per PRD §24)
- All AI calls go through provider abstractions (never direct API calls here)
- After each node: update lesson_jobs.progress and write checkpoint to DB
- Cost ceiling checked by providers — RuntimeError raised if exceeded
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Send
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Story 2-1 AC-0: the six Phase 1 "economy" nodes. Each is fanned out once per
# `state["sections"]` entry via Send() and must ALL complete before Phase 2
# (lesson_planner) starts — violating this silently 5xs pipeline cost by
# feeding lesson_planner raw chapter text instead of cheap summaries.
_ECONOMY_NODES: list[str] = [
    "summarise_segment",
    "quiz_generator",
    "segment_complexity",
    "jargon_extractor",
    "intervention_messages",
    "narration_generator",
]


# ── Pipeline State ────────────────────────────────────────────────────────────


class PipelineState(TypedDict, total=False):
    """Accumulated state flowing through the content pipeline."""

    # Input
    lesson_id: str
    user_id: str
    book_id: str
    source_pdf_path: str
    chapter_content: str  # Raw text passed directly (for testing without PDF)

    # Node 1: extract
    raw_text: str
    extracted_images: list[dict[str, Any]]  # [{page: int, path: str, caption: str}]
    font_blocks: list[dict[str, Any]]       # pdftext span-level blocks; consumed by Node 2

    # Node 2: structure
    sections: list[dict[str, Any]]  # [{title, body, page_start, page_end}]

    # Node 3: chunk
    chunks: list[dict[str, Any]]  # [{id, section_id, text, token_count}]

    # Node 4: embed
    embeddings_stored: bool

    # Node 5: lesson_planner
    lesson_plan: dict[str, Any]  # {title, objectives: [], segments: [], total_duration_min}

    # Node 6: slide_generator
    slides: list[dict[str, Any]]  # [{id, title, body, speaker_notes, layout}]

    # Node 7: summarise_segment
    # Annotated with operator.add: each Send() dispatch (one per section) returns
    # a single-item list; LangGraph concatenates them across the parallel fan-out
    # rather than the default "last write wins" (which would silently drop all
    # but one section's output — see Story 2-1 AC-0).
    segment_summaries: Annotated[list[dict[str, Any]], operator.add]  # [{segment_id, summary}]

    # Node 8: quiz_generator
    quiz_questions: Annotated[list[dict[str, Any]], operator.add]  # [{id, question, options, correct, explanation}]

    # Node 9: segment_complexity
    complexity_scores: Annotated[list[dict[str, Any]], operator.add]  # [{segment_id, flesch_kincaid, grade_level}]

    # Node 10: jargon_extractor
    glossary: Annotated[list[dict[str, Any]], operator.add]  # [{term, definition, segment_id}]

    # Node 11: intervention_messages
    intervention_prompts: Annotated[list[dict[str, Any]], operator.add]  # [{trigger, message, type}]

    # Node 12: narration_generator
    narration_scripts: Annotated[list[dict[str, Any]], operator.add]  # [{slide_id, script}]

    # Set by the Send() fan-out router for each dispatched Phase 1 node call —
    # NOT part of the accumulated/reduced state, just the single-section payload
    # for that one dispatched invocation.
    _section: dict[str, Any]
    _section_index: int

    # Node 13: tts_node
    audio_assets: list[dict[str, Any]]  # [{slide_id, audio_url, timestamps}]

    # Node 14: image_generator
    slide_images: list[dict[str, Any]]  # [{slide_id, image_url}]

    # Node 15: package_builder
    lesson_package: dict[str, Any]  # Final assembled lesson JSON

    # Metadata
    error: str | None
    progress_pct: float


# ── Node implementations ──────────────────────────────────────────────────────

# AC-5 (Story 2-0b): max simultaneous Supabase image uploads per extract run.
# Uploads are blocking HTTP calls run via asyncio.to_thread — the semaphore
# bounds thread/connection pressure while keeping big-image pages parallel.
# Tuned 4 (from 8) after the 1120-page live run: a 545-image sustained storm
# at 8-way rate-limited Supabase Storage into persistent failures.
_IMAGE_UPLOAD_CONCURRENCY = 4
# Upload retry: 5 attempts, exponential backoff 1→8 s (+ jitter) rides out
# rate-limit windows that a 545-image book provokes; a 3×1.5 s retry did not.
_IMAGE_UPLOAD_ATTEMPTS = 5
_IMAGE_UPLOAD_BACKOFF_BASE_S = 1.0


def _compute_extract_timeout(pdf_size_bytes: int, settings: Any) -> float:
    """AC-5: page-aware timeout for the PDF-extraction subprocess.

    ``page_estimate`` is a byte heuristic (~30 kB/page) that overestimates the
    page count for text-heavy PDFs — overestimating is safe (longer timeout).
    The result never exceeds the hard cap nor ``arq_job_timeout_s - 300`` so
    the subprocess timeout ALWAYS fires before ARQ cancels the whole job.
    Clamped to >= 1s: Settings validates the invariant, but this function also
    receives ad-hoc settings objects — a 0/negative wait_for must be impossible.
    """
    page_estimate = max(1, pdf_size_bytes // 30_000)
    return max(
        1.0,
        min(
            settings.extract_timeout_base_s + settings.extract_timeout_per_page_s * page_estimate,
            float(settings.extract_timeout_cap_s),
            float(settings.arq_job_timeout_s - 300),
        ),
    )


async def extract_node(state: PipelineState) -> PipelineState:
    """Node 1: Extract raw text, font blocks, and images from the source PDF.

    Runs pypdfium2 + pdftext + pdfplumber (table detection only) + docling +
    tesseract in an isolated subprocess per CLAUDE.md §18 (untrusted PDF parsing
    must not run in the ARQ worker process).
    PyMuPDF (fitz) is BANNED — AGPL-3.0 incompatible with closed-source SaaS.
    """
    import asyncio
    import json
    import os
    import random
    import signal
    import sys
    import tempfile
    import time

    from app.config import get_settings
    from app.core.db import get_supabase

    lesson_id: str = state["lesson_id"]
    book_id: str = state.get("book_id", "")
    source_pdf_path: str = state.get("source_pdf_path", "")

    logger.info("[%s] extract_node: starting", lesson_id)

    supabase = get_supabase()
    settings = get_settings()

    # ── Idempotency: return cached output if this node already ran ────────────
    jobs_resp = (
        supabase.table("lesson_jobs")
        .select("node_outputs")
        .eq("lesson_id", lesson_id)
        .single()
        .execute()
    )
    node_outputs: dict[str, Any] = (jobs_resp.data or {}).get("node_outputs") or {}

    if "extract" in node_outputs:
        cached = node_outputs["extract"]
        logger.info("[%s] extract_node: cache hit — skipping re-extraction", lesson_id)
        return {
            **state,
            "raw_text": cached["raw_text"],
            "extracted_images": cached.get("extracted_images", []),
            "font_blocks": cached.get("font_blocks", []),
            "progress_pct": 7.0,
        }

    # ── Download PDF from Supabase Storage ────────────────────────────────────
    if not source_pdf_path:
        raise RuntimeError(
            f"extract_node: source_pdf_path missing for lesson_id={lesson_id}"
        )

    pdf_bytes: bytes = supabase.storage.from_("source-pdfs").download(source_pdf_path)

    # ── Run extraction in isolated subprocess ─────────────────────────────────
    with tempfile.TemporaryDirectory(prefix=f"hie_{lesson_id}_") as tmpdir:
        local_pdf = os.path.join(tmpdir, "input.pdf")
        img_dir = os.path.join(tmpdir, "images")
        os.makedirs(img_dir, exist_ok=True)

        with open(local_pdf, "wb") as fh:
            fh.write(pdf_bytes)

        # AC-5: settings-driven, page-aware timeout (replaces the fixed 600 s).
        extract_timeout = _compute_extract_timeout(len(pdf_bytes), settings)

        # start_new_session=True puts the child in its own process group so a
        # single killpg reaps it AND any grandchildren (tesseract, docling).
        spawn_kwargs: dict[str, Any] = (
            {"start_new_session": True} if sys.platform != "win32" else {}
        )
        proc = await asyncio.create_subprocess_exec(  # noqa: S603
            sys.executable,
            "-m", "app.modules.content.pipeline.nodes.extract_subprocess",
            local_pdf,
            img_dir,
            str(settings.ocr_text_yield_threshold),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **spawn_kwargs,
        )
        # AC-5: cleanup lives in try/finally — an except-TimeoutError block
        # never runs when ARQ cancels the job (CancelledError), which is how
        # 4 GB tesseract orphans survived. finally reaps the child on EVERY
        # exit path: success, timeout, and cancellation.
        try:
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=extract_timeout
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"PDF extraction timed out after {extract_timeout:.0f}s "
                    f"for lesson_id={lesson_id}"
                ) from None
        finally:
            if proc.returncode is None:
                try:
                    if sys.platform != "win32":
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except ProcessLookupError:
                    pass  # child already dead — nothing to reap
                # shield: the kill above is sync and already happened; a second
                # cancellation arriving here must not interrupt the reap, or
                # the zombie holds pipe FDs until the worker exits.
                await asyncio.shield(proc.wait())  # reap child so event loop releases pipe FDs

        if proc.returncode != 0:
            raise RuntimeError(
                f"PDF extraction subprocess failed (exit={proc.returncode}): "
                f"{stderr.decode(errors='replace')[:1000]}"
            )

        result: dict[str, Any] = json.loads(stdout.decode())
        raw_text: str = result["raw_text"]
        page_count: int = result["page_count"]
        image_files: list[dict[str, Any]] = result.get("image_files", [])
        font_blocks: list[dict[str, Any]] = result.get("font_blocks", [])

        # ── Upload extracted images to Supabase Storage (AC-5: concurrent) ────
        # Blocking Supabase calls run in threads via asyncio.to_thread, bounded
        # by a Semaphore so a figure-heavy chapter can't spawn unbounded
        # threads/connections. No return_exceptions on gather: one failed
        # upload propagates and fails the node exactly as the serial loop did.
        upload_sem = asyncio.Semaphore(_IMAGE_UPLOAD_CONCURRENCY)

        def _upload_image(local_path: str, storage_path: str) -> None:
            # File read + HTTP call both blocking — keep them inside the thread.
            # Bounded retry: under 8-way concurrent bursts the Storage API can
            # return a transient empty/non-JSON response that storage3 surfaces
            # as JSONDecodeError (observed live 2026-07-10 — 20-image excerpt
            # upload failed on one blip). Retries smooth transient errors; a
            # persistent failure still raises and fails the node.
            with open(local_path, "rb") as imgf:
                payload = imgf.read()
            last_exc: Exception | None = None
            for attempt in range(_IMAGE_UPLOAD_ATTEMPTS):
                try:
                    supabase.storage.from_("lesson-images").upload(
                        path=storage_path,
                        file=payload,
                        file_options={"content-type": "image/png", "upsert": "true"},
                    )
                    return
                except Exception as exc:  # noqa: BLE001 — storage3 raises mixed types
                    last_exc = exc
                    logger.warning(
                        "[%s] extract_node: image upload attempt %d/%d failed for %s: %s",
                        lesson_id, attempt + 1, _IMAGE_UPLOAD_ATTEMPTS, storage_path, exc,
                    )
                    if attempt < _IMAGE_UPLOAD_ATTEMPTS - 1:
                        # 1s, 2s, 4s, 8s + jitter — inside the thread
                        time.sleep(
                            _IMAGE_UPLOAD_BACKOFF_BASE_S * (2 ** attempt)
                            + random.random()
                        )
            raise RuntimeError(
                f"extract_node: image upload failed after "
                f"{_IMAGE_UPLOAD_ATTEMPTS} attempts for {storage_path}"
            ) from last_exc

        async def _bounded_upload(local_path: str, storage_path: str) -> None:
            async with upload_sem:
                await asyncio.to_thread(_upload_image, local_path, storage_path)

        # Entries are appended in input (idx) order and gather preserves the
        # order of its input list, so storage_images stays deterministic.
        upload_coros: list[Any] = []
        storage_images: list[dict[str, Any]] = []
        for idx, img_info in enumerate(image_files):
            local_path: str = img_info["local_path"]
            page_num: int = img_info["page"]
            storage_path = f"{lesson_id}/p{page_num}_{idx}.png"
            if os.path.exists(local_path):
                upload_coros.append(_bounded_upload(local_path, storage_path))
                storage_images.append({"page": page_num, "path": storage_path, "caption": ""})
        if upload_coros:
            await asyncio.gather(*upload_coros)

    # ── Write books.page_count ────────────────────────────────────────────────
    if book_id:  # P6: don't skip when page_count=0 — that's valid information
        try:
            supabase.table("books").update({"page_count": page_count}).eq(
                "book_id", book_id
            ).execute()
        except Exception:  # noqa: BLE001
            logger.warning("[%s] extract_node: failed to update books.page_count", lesson_id)

    # ── Write checkpoint to lesson_jobs ───────────────────────────────────────
    extract_cache: dict[str, Any] = {
        "raw_text": raw_text,
        "extracted_images": storage_images,
        "page_count": page_count,
        "font_blocks": font_blocks,
    }
    # Story 2-0b additive observability keys — defensive .get: the subprocess
    # change lands in a parallel lane, so BOTH old JSON (keys absent) and new
    # JSON (keys present) must checkpoint cleanly.
    for _extra_key in ("tables_detected", "docling_pages"):
        if _extra_key in result:
            extract_cache[_extra_key] = result[_extra_key]
    try:
        supabase.table("lesson_jobs").update({
            "last_node": "extract",
            "node_outputs": {**node_outputs, "extract": extract_cache},
        }).eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning("[%s] extract_node: failed to write checkpoint", lesson_id)

    await _update_job_progress(lesson_id, 7.0, "extract")

    return {
        **state,
        "raw_text": raw_text,
        "extracted_images": storage_images,
        "font_blocks": font_blocks,
        "progress_pct": 7.0,
    }


_STRUCTURE_SYSTEM_PROMPT = """You are a document structure analyser for educational textbooks.
Given raw text from a PDF chapter and candidate headings detected by regex/font analysis,
produce a corrected DocumentStructure with accurate chapter/section/topic hierarchy.

Rules:
- Use ONLY 3 levels: chapter > section > topic
- Every document needs at least 1 section (even if no headings found)
- Preserve ALL body text across sections — no text should be lost
- If no clear heading structure exists, return 1 section at chapter level with full text
- body text should not include the heading title itself
- Keep body text verbatim — do not summarise or paraphrase"""


def _build_structure_prompt(raw_text: str, candidates: list[dict[str, Any]]) -> str:
    text_preview = raw_text[:6000] + ("..." if len(raw_text) > 6000 else "")
    candidates_str = "\n".join(
        f"- [{c['level']}] {c['text']!r} (char_offset={c['char_offset']})"
        for c in candidates[:30]
    )
    return (
        f"Raw text (first 6000 chars of {len(raw_text)}):\n{text_preview}\n\n"
        f"Rule-based heading candidates:\n{candidates_str or '(none detected)'}\n\n"
        "Return a DocumentStructure with accurate section boundaries and full body text."
    )


async def structure_node(state: PipelineState) -> PipelineState:
    """Node 2: Detect chapter/section/topic boundaries using font metadata + LLM validation."""
    from app.config import get_settings
    from app.core.db import get_supabase
    from app.modules.content.pipeline.nodes.structure_detection import (
        build_section_bodies,
        detect_headings,
    )
    from app.providers.llm.openai import OpenAILLMProvider
    from app.schemas import DocumentStructure

    lesson_id: str = state["lesson_id"]
    logger.info("[%s] structure_node: detecting document structure", lesson_id)

    supabase = get_supabase()
    settings = get_settings()

    # ── Idempotency: return cached output if this node already ran ────────────
    jobs_resp = (
        supabase.table("lesson_jobs")
        .select("node_outputs")
        .eq("lesson_id", lesson_id)
        .single()
        .execute()
    )
    node_outputs: dict[str, Any] = (jobs_resp.data or {}).get("node_outputs") or {}

    if "structure" in node_outputs:
        cached = node_outputs["structure"]
        logger.info("[%s] structure_node: cache hit", lesson_id)
        return {**state, "sections": cached["sections"], "progress_pct": 14.0}

    # ── Get page count from extract checkpoint ────────────────────────────────
    total_pages: int = (node_outputs.get("extract") or {}).get("page_count", 1) or 1
    raw_text: str = state.get("raw_text", "")
    font_blocks: list[dict[str, Any]] = state.get("font_blocks", [])

    # ── Rule-based detection ──────────────────────────────────────────────────
    candidates = detect_headings(raw_text, font_blocks)
    rule_sections = build_section_bodies(raw_text, candidates, total_pages)

    # ── LLM validation ────────────────────────────────────────────────────────
    sections_list = rule_sections
    # AC-4 hardening: with empty/whitespace raw_text the < 90% length proxy
    # below is vacuously false (llm_total < 0 never holds), so hallucinated
    # LLM sections would be adopted. Skip the LLM entirely — rule-based wins.
    if not raw_text.strip():
        logger.warning(
            "[%s] structure_node: raw_text is empty — skipping LLM validation, "
            "keeping rule-based sections",
            lesson_id,
        )
    else:
        try:
            provider = OpenAILLMProvider(lesson_id=lesson_id)
            messages = [
                {"role": "system", "content": _STRUCTURE_SYSTEM_PROMPT},
                {"role": "user", "content": _build_structure_prompt(raw_text, candidates)},
            ]
            result: DocumentStructure = await provider.complete_structured(
                messages=messages,
                model=settings.llm_mini,
                response_format=DocumentStructure,
            )
            # AC-4 data-loss guard: the prompt only shows the LLM the first 6000
            # chars of raw_text, so its sections can silently drop everything past
            # that window. Only adopt the LLM output when its bodies cover ≥ 90%
            # of the full raw text; otherwise keep the rule-based sections.
            # Known limitation (Tier-3 #18): a pure length proxy — duplicated or
            # padded bodies totalling ≥ 90% of len(raw_text) still pass.
            llm_total = sum(len(s.body or "") for s in result.sections)
            if llm_total < 0.9 * len(raw_text):
                logger.warning(
                    "[%s] structure_node: LLM sections cover %d/%d chars (< 90%%) — "
                    "rejecting LLM output, keeping rule-based sections",
                    lesson_id, llm_total, len(raw_text),
                )
            else:
                sections_list = [s.model_dump() for s in result.sections]
                logger.info("[%s] structure_node: LLM produced %d sections", lesson_id, len(sections_list))
        except Exception:  # noqa: BLE001
            logger.warning(
                "[%s] structure_node: LLM validation failed — using rule-based fallback",
                lesson_id,
            )

    # ── Write checkpoint to lesson_jobs ───────────────────────────────────────
    structure_cache: dict[str, Any] = {"sections": sections_list}
    try:
        supabase.table("lesson_jobs").update({
            "last_node": "structure",
            "node_outputs": {**node_outputs, "structure": structure_cache},
        }).eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning("[%s] structure_node: failed to write checkpoint", lesson_id)

    await _update_job_progress(lesson_id, 14.0, "structure")
    return {**state, "sections": sections_list, "progress_pct": 14.0}


async def chunk_node(state: PipelineState) -> PipelineState:
    """Node 3: Split sections into token-bounded chunks and write to Supabase.

    Uses tiktoken cl100k_base (text-embedding-3-small tokenizer) with a
    configurable target size and overlap. Creates one `chapters` row then
    bulk-upserts all chunk rows (without embeddings — Story 1.5 sets those).

    Idempotent: if node_outputs["chunk"] already exists, cached data is
    restored and no DB writes are issued.
    """
    from app.config import get_settings
    from app.core.db import get_supabase
    from app.modules.content.pipeline.nodes.chunking import chunk_sections

    lesson_id: str = state["lesson_id"]
    book_id: str = state.get("book_id") or ""  # coerce None → "" so NOT NULL constraint gives clear error
    sections: list[dict[str, Any]] = state.get("sections", [])

    logger.info("[%s] chunk_node: chunking %d sections", lesson_id, len(sections))

    supabase = get_supabase()
    settings = get_settings()

    # ── Idempotency: return cached output if this node already ran ────────────
    jobs_resp = (
        supabase.table("lesson_jobs")
        .select("node_outputs")
        .eq("lesson_id", lesson_id)
        .single()
        .execute()
    )
    node_outputs: dict[str, Any] = (jobs_resp.data or {}).get("node_outputs") or {}

    if "chunk" in node_outputs:
        cached = node_outputs["chunk"]
        logger.info("[%s] chunk_node: cache hit — skipping re-chunking", lesson_id)
        return {**state, "chunks": cached["chunks"], "progress_pct": 20.0}

    # ── Token-bounded chunking ────────────────────────────────────────────────
    chunks = chunk_sections(
        sections,
        target=settings.chunk_target_tokens,
        overlap=settings.chunk_overlap_tokens,
        tokenizer_name=settings.embedding_tokenizer,
    )
    logger.info("[%s] chunk_node: produced %d chunks from %d sections", lesson_id, len(chunks), len(sections))

    # ── Create one chapter row (one chapter per lesson ingestion in MVP) ──────
    chapter_title = sections[0].get("title", "Chapter") if sections else "Chapter"
    chapter_page_start = sections[0].get("page_start", 1) if sections else 1
    chapter_page_end = sections[-1].get("page_end", 1) if sections else 1

    try:
        chapter_resp = supabase.table("chapters").insert({
            "lesson_id": lesson_id,
            "book_id": book_id,
            "title": chapter_title,
            "page_start": chapter_page_start,
            "page_end": chapter_page_end,
            "chapter_index": 1,
        }).execute()
    except Exception as exc:
        raise RuntimeError(
            f"chunk_node: failed to create chapter row for lesson_id={lesson_id}"
        ) from exc

    if not chapter_resp.data:
        raise RuntimeError(
            f"chunk_node: chapters insert returned no data for lesson_id={lesson_id}"
        )
    chapter_id: str = chapter_resp.data[0]["chapter_id"]

    # ── Bulk-upsert chunk rows (embedding column left NULL — Story 1.5 fills it) ─
    # Zero-token chunks (empty section bodies) are excluded from DB to prevent
    # embed_node from calling OpenAI embeddings API with an empty string (→ 400).
    # They remain in the in-memory chunks list for state consistency.
    db_rows = [
        {
            "chapter_id": chapter_id,
            "book_id": book_id,
            "section": chunk["section_title"],
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"],
            "content": chunk["text"],
            "chunk_index": global_i,
            "token_count": chunk["token_count"],
        }
        for global_i, chunk in enumerate(chunks)
        if chunk["token_count"] > 0
    ]
    if db_rows:
        try:
            supabase.table("chunks").upsert(db_rows).execute()
        except Exception as exc:
            raise RuntimeError(
                f"chunk_node: failed to upsert {len(db_rows)} chunks for lesson_id={lesson_id}"
            ) from exc

    # ── Write checkpoint to lesson_jobs ───────────────────────────────────────
    chunk_cache: dict[str, Any] = {"chunks": chunks, "chapter_id": chapter_id}
    try:
        supabase.table("lesson_jobs").update({
            "last_node": "chunk",
            "node_outputs": {**node_outputs, "chunk": chunk_cache},
        }).eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning("[%s] chunk_node: failed to write checkpoint", lesson_id)

    await _update_job_progress(lesson_id, 20.0, "chunk")
    return {**state, "chunks": chunks, "progress_pct": 20.0}


# OpenAI embeddings API hard limits (text-embedding-3-small):
#   - max 2048 inputs per request (array limit) — a larger array 400s outright
#   - ~8191 tokens per single input — one oversized input 400s the WHOLE batch
_MAX_EMBED_BATCH_ITEMS = 2048
_MAX_EMBED_INPUT_TOKENS = 8000  # safety margin under the ~8191-token model cap


async def embed_node(state: PipelineState) -> PipelineState:
    """Node 4: Generate vector embeddings for all chunks and store in pgvector.

    Reads chapter_id from the chunk_node checkpoint, queries chunks with
    embedding IS NULL (paginated past PostgREST's 1000-row cap), filters
    empty-content chunks ONCE (so embeddings can never misalign with rows),
    batches by token budget (settings.embed_batch_token_budget — OpenAI's
    request cap is 300k tokens), bulk-upserts the 1536-dim vectors back to
    chunks.embedding, verifies nothing embeddable is left NULL, marks
    books.status='ready', and writes its own checkpoint.

    Embeddings are generated ONCE at ingestion — never regenerated for stored
    content (CLAUDE.md rule). The `embedding IS NULL` filter makes retries safe.
    """
    import asyncio
    from datetime import datetime, timezone

    from app.config import get_settings
    from app.core.db import get_supabase
    from app.providers.embeddings.openai import OpenAIEmbeddingsProvider

    lesson_id: str = state["lesson_id"]
    book_id: str = state.get("book_id") or ""
    logger.info("[%s] embed_node: starting", lesson_id)

    supabase = get_supabase()
    settings = get_settings()

    # ── Idempotency: return cached output if this node already completed ──────
    jobs_resp = (
        supabase.table("lesson_jobs")
        .select("node_outputs")
        .eq("lesson_id", lesson_id)
        .single()
        .execute()
    )
    node_outputs: dict[str, Any] = (jobs_resp.data or {}).get("node_outputs") or {}

    if "embed" in node_outputs:
        cached = node_outputs["embed"]
        logger.info(
            "[%s] embed_node: cache hit — %d chunks already embedded",
            lesson_id, cached.get("chunk_count", 0),
        )
        return {**state, "embeddings_stored": True}

    # ── Get chapter_id from chunk_node checkpoint ─────────────────────────────
    chapter_id: str = (node_outputs.get("chunk") or {}).get("chapter_id", "")
    if not chapter_id:
        raise RuntimeError(
            f"embed_node: no chapter_id in chunk checkpoint for lesson_id={lesson_id}. "
            "Ensure chunk_node ran successfully before embed_node."
        )

    # ── Query chunks that still need embeddings ───────────────────────────────
    # AC-6(b): paginate with .range() — PostgREST silently caps a select at
    # 1000 rows, so books > 1000 chunks would otherwise be half-embedded then
    # checkpointed as complete.
    _PAGE_SIZE = 1000

    def _fetch_unembedded_chunks() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page_resp = (
                supabase.table("chunks")
                .select("chunk_id, content, token_count, chunk_index")
                .eq("chapter_id", chapter_id)
                .is_("embedding", "null")
                .order("chunk_index")
                .range(offset, offset + _PAGE_SIZE - 1)
                .execute()
            )
            page: list[dict[str, Any]] = page_resp.data or []
            rows.extend(page)
            if len(page) < _PAGE_SIZE:
                return rows
            offset += _PAGE_SIZE

    # Sync PostgREST round-trips must not block the ARQ event loop.
    chunks: list[dict[str, Any]] = await asyncio.to_thread(_fetch_unembedded_chunks)

    # AC-6(a): filter empty-content chunks ONCE — the SAME list feeds both
    # embed_texts and the writeback pairing, so misalignment is impossible.
    embeddable = [c for c in chunks if (c.get("content") or "").strip()]
    if len(embeddable) < len(chunks):
        logger.info(
            "[%s] embed_node: skipping %d empty-content chunks (embedding stays NULL)",
            lesson_id, len(chunks) - len(embeddable),
        )

    if embeddable:
        provider = OpenAIEmbeddingsProvider(lesson_id=lesson_id)
        total_tokens = 0
        batch_count = 0
        ingested_at = datetime.now(tz=timezone.utc).isoformat()
        metadata: dict[str, Any] = {
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
            "ingested_at": ingested_at,
        }

        # AC-6(c): pack consecutive chunks by token budget AND item count — a
        # fixed 2048-chunk batch can exceed OpenAI's 300k-token request cap,
        # and any request over _MAX_EMBED_BATCH_ITEMS inputs is rejected (400).
        # Each batch entry is (chunk_row, api_text): a single chunk estimated
        # over _MAX_EMBED_INPUT_TOKENS has ONLY its API input truncated —
        # chunks.content in the DB is never modified.
        budget: int = settings.embed_batch_token_budget
        batches: list[list[tuple[dict[str, Any], str]]] = []
        current: list[tuple[dict[str, Any], str]] = []
        current_tokens = 0
        for c in embeddable:
            text: str = c["content"]
            est = c.get("token_count") or max(1, len(text) // 4)
            if est > _MAX_EMBED_INPUT_TOKENS:
                logger.warning(
                    "[%s] embed_node: chunk %s est %d tokens exceeds the "
                    "%d-token per-input cap — truncating the API input "
                    "(DB content unchanged)",
                    lesson_id, c.get("chunk_id"), est, _MAX_EMBED_INPUT_TOKENS,
                )
                text = text[: _MAX_EMBED_INPUT_TOKENS * 4]  # ~4 chars/token
                est = _MAX_EMBED_INPUT_TOKENS
            if current and (
                current_tokens + est > budget
                or len(current) >= _MAX_EMBED_BATCH_ITEMS
            ):
                batches.append(current)
                current = []
                current_tokens = 0
            current.append((c, text))  # at least 1 chunk per batch, even if est > budget
            current_tokens += est
        if current:
            batches.append(current)

        for batch_idx, batch in enumerate(batches):
            texts = [text for _, text in batch]
            embeddings, batch_tokens = await provider.embed_texts(texts)
            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f"embed_node: OpenAI returned {len(embeddings)} embeddings for "
                    f"{len(texts)} texts in lesson_id={lesson_id} — batch index {batch_idx}"
                )
            total_tokens += batch_tokens
            batch_count += 1

            # AC-6(d): ONE bulk upsert per batch instead of per-chunk round-trips.
            # The upsert MUST echo chapter_id/content/chunk_index: Postgres
            # validates NOT NULL on the candidate tuple BEFORE ON CONFLICT
            # arbitration, so omitting them fails with 23502 even though every
            # chunk_id already exists and only the UPDATE arm would run.
            rows = [
                {
                    "chunk_id": c["chunk_id"],
                    "chapter_id": chapter_id,
                    "content": c["content"],  # FULL content, even when API input was truncated
                    "chunk_index": c["chunk_index"],
                    "embedding": embedding,
                    "embedding_metadata": metadata,
                }
                for (c, _), embedding in zip(batch, embeddings)
            ]
            try:
                await asyncio.to_thread(
                    lambda rows=rows: supabase.table("chunks")
                    .upsert(rows, on_conflict="chunk_id")
                    .execute()
                )
            except Exception as exc:
                raise RuntimeError(
                    f"embed_node: failed to bulk-write {len(rows)} embeddings "
                    f"(batch index {batch_idx}) for lesson_id={lesson_id}"
                ) from exc

        logger.info(
            "[%s] embed_node: embedded %d chunks in %d batches (%d tokens total)",
            lesson_id, len(embeddable), batch_count, total_tokens,
        )
    else:
        logger.info(
            "[%s] embed_node: no unembedded chunks found for chapter_id=%s (all already done)",
            lesson_id, chapter_id,
        )

    # ── Completion check (AC-6b): never checkpoint a half-embedded book ───────
    remaining = [
        c
        for c in await asyncio.to_thread(_fetch_unembedded_chunks)
        if (c.get("content") or "").strip()
    ]
    if remaining:
        raise RuntimeError(
            f"embed_node: {len(remaining)} chunks still unembedded after writeback "
            f"for lesson_id={lesson_id} chapter_id={chapter_id} — refusing to checkpoint"
        )

    # ── Mark book as ready ────────────────────────────────────────────────────
    if book_id:
        try:
            supabase.table("books").update({"status": "ready"}).eq("book_id", book_id).execute()
            logger.info("[%s] embed_node: books.status=ready for book_id=%s", lesson_id, book_id)
        except Exception as exc:
            logger.warning(
                "[%s] embed_node: failed to mark book_id=%s ready: %s",
                lesson_id, book_id, exc,
            )

    # ── Checkpoint ────────────────────────────────────────────────────────────
    embed_cache: dict[str, Any] = {"chunk_count": len(embeddable), "chapter_id": chapter_id}
    supabase.table("lesson_jobs").update({
        "last_node": "embed",
        "node_outputs": {**node_outputs, "embed": embed_cache},
    }).eq("lesson_id", lesson_id).execute()

    await _update_job_progress(lesson_id, 28.0, "embed")
    return {**state, "embeddings_stored": True}


async def lesson_planner_node(state: PipelineState) -> PipelineState:
    """Node 5 (Phase 2 Premium): generate a structured lesson plan.

    Uses llm_lesson_planner model (gpt-4o by default, PRD §6.4).

    AC-0 SCOPE NOTE (Story 2-1): this node's real GPT-4o generation logic is
    S2-7, a separate story — not implemented here. What Story 2-1 requires is
    that the graph wiring actually DELIVERS `state["segment_summaries"]` to
    this node (proving Phase 1 completed and its output is consumable) rather
    than the node running with zero Phase 1 data available at all, which was
    the bug this story's AC-0 fixes. `total_segments` reflects the real input
    count as a wiring-proof signal; `title`/`objectives`/`segments` remain
    placeholders until S2-7 lands.
    """
    from app.config import get_settings
    settings = get_settings()
    _model = settings.llm_lesson_planner  # noqa: F841 (used by S2-7, not yet implemented)

    lesson_id = state["lesson_id"]
    segment_summaries = state.get("segment_summaries", [])
    logger.info(
        "[%s] lesson_planner_node: generating lesson plan from %d segment summaries",
        lesson_id,
        len(segment_summaries),
    )
    await _update_job_progress(lesson_id, 30.0, "lesson_planner")

    # TODO (S2-7): OpenAILLMProvider(lesson_id).complete_structured(messages, model, LessonPlan)
    lesson_plan: dict[str, Any] = {
        "title": "TODO: LLM-generated title",
        "objectives": [],
        "segments": [],
        "total_segments": len(segment_summaries),
        "total_duration_min": 0,
    }
    return {**state, "lesson_plan": lesson_plan, "progress_pct": 38.0}


async def slide_generator_node(state: PipelineState) -> PipelineState:
    """Node 6: Generate slide deck JSON from the lesson plan.

    Uses llm_slide_generator model (gpt-4o by default).
    """
    lesson_id = state["lesson_id"]
    logger.info("[%s] slide_generator_node: generating slides", lesson_id)
    await _update_job_progress(lesson_id, 40.0, "slide_generator")

    # TODO: OpenAILLMProvider(lesson_id).complete_structured(messages, model, SlideDeck)
    slides: list[dict[str, Any]] = []
    return {**state, "slides": slides, "progress_pct": 48.0}


class _SegmentSummaryLLM(BaseModel):
    """Internal structured-output shape for summarise_segment_node — not part
    of the frozen lesson contract, just the LLM response parsing target."""

    summary: str


def _cap_words(text: str, max_words: int) -> str:
    """Truncate *text* to at most *max_words* words, logging if it had to."""
    words = text.split()
    if len(words) <= max_words:
        return text
    logger.warning("summary exceeded %d words (got %d) — truncating", max_words, len(words))
    return " ".join(words[:max_words])


async def summarise_segment_node(state: PipelineState) -> PipelineState:
    """Node 7 (Story 2-1 AC-1): generate a 2-3 sentence, <=100 word summary
    for one section. Send()-dispatched once per section (see AC-0) — this is
    what `lesson_planner` (S2-7) consumes INSTEAD of raw chapter text (the
    single most cost-critical constraint in the whole pipeline).
    """
    from app.config import get_settings
    from app.providers.llm.openai import OpenAILLMProvider

    lesson_id = state["lesson_id"]
    section = state["_section"]
    section_id = section.get("title") or f"section_{state.get('_section_index', 0)}"
    logger.info("[%s] summarise_segment_node: %s", lesson_id, section_id)

    settings = get_settings()
    provider = OpenAILLMProvider(lesson_id)
    messages = [
        {
            "role": "system",
            "content": "Summarise the following section in 2-3 sentences, no more than 100 words.",
        },
        {"role": "user", "content": section.get("body", "")[:6000]},
    ]
    response = await provider.complete_structured(messages, settings.llm_mini, _SegmentSummaryLLM)
    summary_text = _cap_words(response.summary, 100)

    return {"segment_summaries": [{"segment_id": section_id, "summary": summary_text}]}


async def quiz_generator_node(state: PipelineState) -> PipelineState:
    """Node 8: Generate MCQs for one section (Send()-dispatched, see AC-0).

    Still a stub (S2-3, not yet implemented) — return shape is fan-out-safe:
    only this node's own reduced key, no **state spread / progress_pct (a
    concurrent write to a non-reducer key across parallel dispatches raises
    LangGraph's InvalidUpdateError).
    """
    lesson_id = state["lesson_id"]
    logger.info("[%s] quiz_generator_node: %s", lesson_id, state.get("_section", {}).get("title"))

    # TODO (S2-3): OpenAILLMProvider(lesson_id).complete_structured(messages, llm_mini, QuizSet)
    return {"quiz_questions": []}


def _clamp(value: float, lo: float, hi: float, *, label: str) -> float:
    """Clamp *value* into [lo, hi], logging when the LLM produced an
    out-of-range value rather than silently trusting it (Story 2-1 AC-2)."""
    if not (lo <= value <= hi):
        logger.warning("%s=%.4f out of range [%.1f, %.1f] — clamping", label, value, lo, hi)
        return max(lo, min(hi, value))
    return value


async def segment_complexity_node(state: PipelineState) -> PipelineState:
    """Node 9 (Story 2-1 AC-2): score one section's reading complexity.

    Send()-dispatched once per section (see AC-0) — reads `state["_section"]`,
    not `state["sections"]`. Returns only its own reduced key (fan-out-safe,
    see quiz_generator_node's docstring for why).
    """
    from app.config import get_settings
    from app.providers.llm.openai import OpenAILLMProvider
    from app.schemas.lesson import SegmentComplexity

    lesson_id = state["lesson_id"]
    section = state["_section"]
    section_id = section.get("title") or f"section_{state.get('_section_index', 0)}"
    logger.info("[%s] segment_complexity_node: %s", lesson_id, section_id)

    settings = get_settings()
    provider = OpenAILLMProvider(lesson_id)
    messages = [
        {
            "role": "system",
            "content": (
                "Score this section's reading complexity for an adaptive learning "
                "platform. Return level (low/medium/high), cognitive_load, "
                "abstraction_level, prerequisite_concepts, narration_style, "
                "quiz_difficulty, and intervention_sensitivity (a float in [0.0, 1.0])."
            ),
        },
        {"role": "user", "content": section.get("body", "")[:6000]},
    ]
    response = await provider.complete_structured(messages, settings.llm_mini, SegmentComplexity)

    score: dict[str, Any] = {
        "segment_id": section_id,
        "level": response.level,
        "cognitive_load": response.cognitive_load,
        "abstraction_level": response.abstraction_level,
        "prerequisite_concepts": response.prerequisite_concepts,
        "narration_style": response.narration_style,
        "quiz_difficulty": response.quiz_difficulty,
        "intervention_sensitivity": _clamp(
            float(response.intervention_sensitivity), 0.0, 1.0, label="intervention_sensitivity"
        ),
    }

    return {"complexity_scores": [score]}


async def jargon_extractor_node(state: PipelineState) -> PipelineState:
    """Node 10 (S2-4, not yet implemented): extract jargon for one section.

    Send()-dispatched per section (AC-0) — stub return is fan-out-safe (own
    reduced key only, see quiz_generator_node's docstring for why).
    """
    lesson_id = state["lesson_id"]
    logger.info("[%s] jargon_extractor_node: %s", lesson_id, state.get("_section", {}).get("title"))

    # TODO (S2-4): OpenAILLMProvider(lesson_id).complete_structured(messages, llm_mini, Glossary)
    return {"glossary": []}


async def intervention_messages_node(state: PipelineState) -> PipelineState:
    """Node 11 (S2-5, not yet implemented): pre-generate intervention prompts
    for one section. Send()-dispatched per section (AC-0) — fan-out-safe stub.
    """
    lesson_id = state["lesson_id"]
    logger.info("[%s] intervention_messages_node: %s", lesson_id, state.get("_section", {}).get("title"))

    # TODO (S2-5): generate distraction, confusion, fatigue message variants (3x3)
    return {"intervention_prompts": []}


async def narration_generator_node(state: PipelineState) -> PipelineState:
    """Node 12 (S2-6, not yet implemented): write a narration script for one
    section. Send()-dispatched per section (AC-0) — fan-out-safe stub.
    """
    lesson_id = state["lesson_id"]
    logger.info("[%s] narration_generator_node: %s", lesson_id, state.get("_section", {}).get("title"))

    # TODO (S2-6): OpenAILLMProvider(lesson_id).complete with speaker-voice prompt
    return {"narration_scripts": []}


async def tts_node(state: PipelineState) -> PipelineState:
    """Node 13: Synthesise narration scripts to audio with word timestamps."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] tts_node: synthesising %d narrations", lesson_id, len(state.get("narration_scripts", [])))
    await _update_job_progress(lesson_id, 80.0, "tts_node")

    # TODO: ElevenLabsTTSProvider().synthesize(script, voice_id)
    # TODO: upload audio to Supabase Storage (lesson-audio bucket)
    audio_assets: list[dict[str, Any]] = []
    return {**state, "audio_assets": audio_assets, "progress_pct": 86.0}


async def image_generator_node(state: PipelineState) -> PipelineState:
    """Node 14: Generate illustrative images for slides that require visuals."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] image_generator_node", lesson_id)
    await _update_job_progress(lesson_id, 88.0, "image_generator")

    # TODO: DalleImageProvider(lesson_id).generate(slide_image_prompt)
    # TODO: download URL and upload to Supabase Storage (lesson-images bucket)
    slide_images: list[dict[str, Any]] = []
    return {**state, "slide_images": slide_images, "progress_pct": 93.0}


# [DEV1-SPRINT2-PENDING] This still builds a flat ad-hoc dict, not the frozen
# LessonPackage shape (packages/shared/lesson_package.schema.json /
# app/schemas/lesson.py). Story S2-11 replaces this with a schema-validated
# segments[] package. Do not build a parallel real-content path elsewhere
# against this stub shape -- it will be reconciled when Sprint 2 lands.
# Ping Dev 1 (developer1-cybersmith) before changing this shape.
async def package_builder_node(state: PipelineState) -> PipelineState:
    """Node 15: Assemble all outputs into the final lesson JSON package."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] package_builder_node: assembling lesson package", lesson_id)
    await _update_job_progress(lesson_id, 95.0, "package_builder")

    lesson_package: dict[str, Any] = {
        "lesson_id": lesson_id,
        "lesson_plan": state.get("lesson_plan", {}),
        "slides": state.get("slides", []),
        "audio_assets": state.get("audio_assets", []),
        "slide_images": state.get("slide_images", []),
        "quiz_questions": state.get("quiz_questions", []),
        "glossary": state.get("glossary", []),
        "intervention_prompts": state.get("intervention_prompts", []),
        "segment_summaries": state.get("segment_summaries", []),
    }

    # Final DB update
    await _update_job_progress(lesson_id, 100.0, "complete")

    return {**state, "lesson_package": lesson_package, "progress_pct": 100.0}


# ── Graph construction ────────────────────────────────────────────────────────


def _fan_out_phase1_economy_nodes(state: PipelineState) -> list[Send]:
    """Story 2-1 AC-0 router: dispatch every Phase 1 economy node once per
    `state["sections"]` entry. Each dispatched call receives a copy of the
    accumulated state plus `_section`/`_section_index` for that one section —
    it must NOT loop over `state["sections"]` itself (that would silently
    redo the whole chapter N times over instead of one section per call).
    """
    sections = state.get("sections", [])
    return [
        Send(node_name, {**state, "_section": section, "_section_index": idx})
        for idx, section in enumerate(sections)
        for node_name in _ECONOMY_NODES
    ]


def _build_pipeline_graph() -> Any:
    """Build and compile the content pipeline StateGraph.

    Returns the compiled graph with MemorySaver checkpointing.
    NOTE: PostgresSaver is explicitly BANNED per PRD §24 — always use MemorySaver.
    """
    # MemorySaver for in-process checkpointing (PostgresSaver is BANNED per PRD §24)
    checkpointer = MemorySaver()

    graph: StateGraph = StateGraph(PipelineState)

    # Register all 14 nodes
    graph.add_node("extract", extract_node)
    graph.add_node("structure", structure_node)
    graph.add_node("chunk", chunk_node)
    graph.add_node("embed", embed_node)
    graph.add_node("lesson_planner", lesson_planner_node)
    graph.add_node("slide_generator", slide_generator_node)
    graph.add_node("summarise_segment", summarise_segment_node)
    graph.add_node("quiz_generator", quiz_generator_node)
    graph.add_node("segment_complexity", segment_complexity_node)
    graph.add_node("jargon_extractor", jargon_extractor_node)
    graph.add_node("intervention_messages", intervention_messages_node)
    graph.add_node("narration_generator", narration_generator_node)
    graph.add_node("tts_node", tts_node)
    graph.add_node("image_generator", image_generator_node)
    graph.add_node("package_builder", package_builder_node)

    # Linear pipeline edges (Phase A + fan-out/join Phase B.1 → B.2 → B.3)
    graph.set_entry_point("extract")
    graph.add_edge("extract", "structure")
    graph.add_edge("structure", "chunk")
    graph.add_edge("chunk", "embed")

    # Story 2-1 AC-0: embed fans out to all 6 Phase 1 economy nodes, once per
    # section, via Send() — replacing the old direct embed -> lesson_planner
    # edge that let lesson_planner run with zero segment summaries available
    # (the exact 5x-cost-overrun bug this AC fixes).
    graph.add_conditional_edges("embed", _fan_out_phase1_economy_nodes, _ECONOMY_NODES)

    # Join: lesson_planner only runs once ALL fanned-out economy-node dispatches
    # (6 nodes x N sections) have completed for this superstep.
    for node_name in _ECONOMY_NODES:
        graph.add_edge(node_name, "lesson_planner")

    graph.add_edge("lesson_planner", "slide_generator")
    graph.add_edge("slide_generator", "tts_node")
    graph.add_edge("tts_node", "image_generator")
    graph.add_edge("image_generator", "package_builder")
    graph.add_edge("package_builder", END)

    return graph.compile(checkpointer=checkpointer)


# Module-level compiled graph (lazy-initialised to avoid import-time side effects)
_compiled_graph: Any | None = None


def get_pipeline_graph() -> Any:
    """Return the cached compiled pipeline graph."""
    global _compiled_graph  # noqa: PLW0603
    if _compiled_graph is None:
        _compiled_graph = _build_pipeline_graph()
    return _compiled_graph


# ── Entry point ───────────────────────────────────────────────────────────────


async def run_pipeline(
    lesson_id: str,
    chapter_content: str = "",
    user_id: str = "",
    source_pdf_path: str = "",
    book_id: str = "",
) -> dict[str, Any]:
    """Execute the full content pipeline for a lesson.

    Args:
        lesson_id:        UUID of the lesson (maps to lesson_jobs table row).
        chapter_content:  Raw text content (used when PDF has already been extracted,
                          or for testing without a PDF file).
        user_id:          UUID of the lesson owner.
        source_pdf_path:  Storage path of the source PDF in Supabase Storage.
        book_id:          UUID of the parent book (for books.page_count write).

    Returns:
        The final ``lesson_package`` dict from package_builder_node.

    Raises:
        RuntimeError: If the cost ceiling is exceeded mid-pipeline.
        Exception:    Any unhandled node error (caller should mark job as failed).
    """
    graph = get_pipeline_graph()

    initial_state: PipelineState = {
        "lesson_id": lesson_id,
        "user_id": user_id,
        "book_id": book_id,
        "chapter_content": chapter_content,
        "source_pdf_path": source_pdf_path,
        "progress_pct": 0.0,
        "error": None,
    }

    config = {"configurable": {"thread_id": lesson_id}}

    logger.info("Pipeline starting for lesson_id=%s", lesson_id)

    final_state: PipelineState = await graph.ainvoke(initial_state, config=config)

    logger.info("Pipeline complete for lesson_id=%s", lesson_id)
    return final_state.get("lesson_package", {})


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _update_job_progress(lesson_id: str, progress_pct: float, node_name: str) -> None:
    """Write progress to the lesson_jobs table.

    Uses Supabase client (not PostgresSaver — that is BANNED per PRD §24).
    Failures are logged but never raise — they must not abort the pipeline.
    """
    try:
        from app.core.db import get_supabase  # lazy import

        supabase = get_supabase()
        supabase.table("lesson_jobs").update(
            {
                "last_node": node_name,
                "status": "running",
            }
        ).eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to update job progress for lesson %s at node %s", lesson_id, node_name)
