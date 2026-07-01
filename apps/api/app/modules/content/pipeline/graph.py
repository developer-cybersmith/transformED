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
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)


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
    segment_summaries: list[dict[str, Any]]  # [{segment_id, summary}]

    # Node 8: quiz_generator
    quiz_questions: list[dict[str, Any]]  # [{id, question, options, correct, explanation}]

    # Node 9: segment_complexity
    complexity_scores: list[dict[str, Any]]  # [{segment_id, flesch_kincaid, grade_level}]

    # Node 10: jargon_extractor
    glossary: list[dict[str, Any]]  # [{term, definition, segment_id}]

    # Node 11: intervention_messages
    intervention_prompts: list[dict[str, Any]]  # [{trigger, message, type}]

    # Node 12: narration_generator
    narration_scripts: list[dict[str, Any]]  # [{slide_id, script}]

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
    import sys
    import tempfile

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

        proc = await asyncio.create_subprocess_exec(  # noqa: S603
            sys.executable,
            "-m", "app.modules.content.pipeline.nodes.extract_subprocess",
            local_pdf,
            img_dir,
            str(settings.ocr_text_yield_threshold),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # P2: 600-second hard limit — prevents scanned PDFs / Tesseract from
        # blocking an ARQ worker coroutine indefinitely.
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()  # reap child so event loop releases pipe FDs
            raise RuntimeError(
                f"PDF extraction timed out after 600s for lesson_id={lesson_id}"
            )

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

        # ── Upload extracted images to Supabase Storage ────────────────────────
        storage_images: list[dict[str, Any]] = []
        for idx, img_info in enumerate(image_files):
            local_path: str = img_info["local_path"]
            page_num: int = img_info["page"]
            storage_path = f"{lesson_id}/p{page_num}_{idx}.png"
            if os.path.exists(local_path):
                with open(local_path, "rb") as imgf:
                    supabase.storage.from_("lesson-images").upload(
                        path=storage_path,
                        file=imgf.read(),
                        file_options={"content-type": "image/png", "upsert": "true"},
                    )
                storage_images.append({"page": page_num, "path": storage_path, "caption": ""})

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
    book_id: str = state.get("book_id", "")
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

    chapter_resp = supabase.table("chapters").insert({
        "lesson_id": lesson_id,
        "book_id": book_id,
        "title": chapter_title,
        "page_start": chapter_page_start,
        "page_end": chapter_page_end,
        "chapter_index": 1,
    }).execute()
    chapter_id: str = chapter_resp.data[0]["chapter_id"]

    # ── Bulk-upsert chunk rows (embedding column left NULL — Story 1.5 fills it) ─
    if chunks:
        rows = [
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
        ]
        supabase.table("chunks").upsert(rows).execute()

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


async def embed_node(state: PipelineState) -> PipelineState:
    """Node 4: Generate and store vector embeddings for all chunks."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] embed_node: embedding %d chunks", lesson_id, len(state.get("chunks", [])))
    await _update_job_progress(lesson_id, 22.0, "embed")

    # TODO: openai.embeddings.create(model="text-embedding-3-small", input=texts)
    # TODO: bulk upsert to Supabase pgvector table (lesson_embeddings)
    return {**state, "embeddings_stored": True, "progress_pct": 28.0}


async def lesson_planner_node(state: PipelineState) -> PipelineState:
    """Node 5: Generate a structured lesson plan from the document chunks.

    Uses llm_lesson_planner model (gpt-4o by default, PRD §6.4).
    """
    lesson_id = state["lesson_id"]
    logger.info("[%s] lesson_planner_node: generating lesson plan", lesson_id)
    await _update_job_progress(lesson_id, 30.0, "lesson_planner")

    # TODO: OpenAILLMProvider(lesson_id).complete_structured(messages, model, LessonPlan)
    from app.config import get_settings
    settings = get_settings()
    _model = settings.llm_lesson_planner  # noqa: F841 (used in TODO)

    lesson_plan: dict[str, Any] = {
        "title": "TODO: LLM-generated title",
        "objectives": [],
        "segments": [],
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


async def summarise_segment_node(state: PipelineState) -> PipelineState:
    """Node 7: Generate a short intro summary for each lesson segment."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] summarise_segment_node", lesson_id)
    await _update_job_progress(lesson_id, 50.0, "summarise_segment")

    # TODO: parallel LLM calls per segment using llm_mini
    segment_summaries: list[dict[str, Any]] = []
    return {**state, "segment_summaries": segment_summaries, "progress_pct": 54.0}


async def quiz_generator_node(state: PipelineState) -> PipelineState:
    """Node 8: Generate MCQs for each lesson segment."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] quiz_generator_node", lesson_id)
    await _update_job_progress(lesson_id, 56.0, "quiz_generator")

    # TODO: OpenAILLMProvider(lesson_id).complete_structured(messages, llm_mini, QuizSet)
    quiz_questions: list[dict[str, Any]] = []
    return {**state, "quiz_questions": quiz_questions, "progress_pct": 60.0}


async def segment_complexity_node(state: PipelineState) -> PipelineState:
    """Node 9: Score each segment's reading complexity."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] segment_complexity_node", lesson_id)
    await _update_job_progress(lesson_id, 62.0, "segment_complexity")

    # TODO: textstat.flesch_reading_ease() + LLM grade-level estimation
    complexity_scores: list[dict[str, Any]] = []
    return {**state, "complexity_scores": complexity_scores, "progress_pct": 65.0}


async def jargon_extractor_node(state: PipelineState) -> PipelineState:
    """Node 10: Extract domain jargon and generate definitions."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] jargon_extractor_node", lesson_id)
    await _update_job_progress(lesson_id, 66.0, "jargon_extractor")

    # TODO: OpenAILLMProvider(lesson_id).complete_structured(messages, llm_mini, Glossary)
    glossary: list[dict[str, Any]] = []
    return {**state, "glossary": glossary, "progress_pct": 69.0}


async def intervention_messages_node(state: PipelineState) -> PipelineState:
    """Node 11: Pre-generate intervention prompts based on complexity + jargon."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] intervention_messages_node", lesson_id)
    await _update_job_progress(lesson_id, 70.0, "intervention_messages")

    # TODO: generate distraction, fatigue, encouragement message variants
    intervention_prompts: list[dict[str, Any]] = []
    return {**state, "intervention_prompts": intervention_prompts, "progress_pct": 73.0}


async def narration_generator_node(state: PipelineState) -> PipelineState:
    """Node 12: Write narration scripts for each slide."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] narration_generator_node: %d slides", lesson_id, len(state.get("slides", [])))
    await _update_job_progress(lesson_id, 74.0, "narration_generator")

    # TODO: OpenAILLMProvider(lesson_id).complete for each slide with speaker-voice prompt
    narration_scripts: list[dict[str, Any]] = []
    return {**state, "narration_scripts": narration_scripts, "progress_pct": 78.0}


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

    # Linear pipeline edges
    graph.set_entry_point("extract")
    graph.add_edge("extract", "structure")
    graph.add_edge("structure", "chunk")
    graph.add_edge("chunk", "embed")
    graph.add_edge("embed", "lesson_planner")
    graph.add_edge("lesson_planner", "slide_generator")
    graph.add_edge("slide_generator", "summarise_segment")
    graph.add_edge("summarise_segment", "quiz_generator")
    graph.add_edge("quiz_generator", "segment_complexity")
    graph.add_edge("segment_complexity", "jargon_extractor")
    graph.add_edge("jargon_extractor", "intervention_messages")
    graph.add_edge("intervention_messages", "narration_generator")
    graph.add_edge("narration_generator", "tts_node")
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
