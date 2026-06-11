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
    source_pdf_path: str
    chapter_content: str  # Raw text passed directly (for testing without PDF)

    # Node 1: extract
    raw_text: str
    extracted_images: list[dict[str, Any]]  # [{page: int, path: str, caption: str}]

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
    """Node 1: Extract raw text and images from the source PDF.

    Uses PyMuPDF (fitz) for text extraction and pytesseract for OCR fallback.
    TODO (Sprint 1): Implement full PDF extraction.
    """
    lesson_id = state["lesson_id"]
    logger.info("[%s] extract_node: starting PDF extraction", lesson_id)
    await _update_job_progress(lesson_id, 5.0, "extract")

    # TODO: fitz.open(pdf_path) → extract text per page
    # TODO: OCR fallback via pytesseract for image-heavy pages
    # TODO: extract embedded images and store to Supabase Storage

    return {**state, "raw_text": state.get("chapter_content", ""), "extracted_images": [], "progress_pct": 7.0}


async def structure_node(state: PipelineState) -> PipelineState:
    """Node 2: Parse raw text into structured sections/chapters."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] structure_node: structuring document", lesson_id)
    await _update_job_progress(lesson_id, 10.0, "structure")

    # TODO: heading detection (regex + LLM fallback for structure inference)
    sections: list[dict[str, Any]] = [
        {"id": "s0", "title": "Introduction", "body": state.get("raw_text", ""), "page_start": 1, "page_end": 1}
    ]
    return {**state, "sections": sections, "progress_pct": 14.0}


async def chunk_node(state: PipelineState) -> PipelineState:
    """Node 3: Split sections into token-bounded chunks for LLM processing."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] chunk_node: chunking %d sections", lesson_id, len(state.get("sections", [])))
    await _update_job_progress(lesson_id, 16.0, "chunk")

    # TODO: tiktoken-based chunking with 512-token target, 64-token overlap
    chunks: list[dict[str, Any]] = [
        {"id": f"c{i}", "section_id": s["id"], "text": s["body"], "token_count": len(s["body"].split())}
        for i, s in enumerate(state.get("sections", []))
    ]
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


async def run_pipeline(lesson_id: str, chapter_content: str, user_id: str = "") -> dict[str, Any]:
    """Execute the full content pipeline for a lesson.

    Args:
        lesson_id:       UUID of the lesson (maps to lesson_jobs table row).
        chapter_content: Raw text content (used when PDF has already been extracted,
                         or for testing without a PDF file).
        user_id:         UUID of the lesson owner.

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
        "chapter_content": chapter_content,
        "source_pdf_path": "",
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
                "progress_pct": progress_pct,
                "current_node": node_name,
                "status": "running",
            }
        ).eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to update job progress for lesson %s at node %s", lesson_id, node_name)
