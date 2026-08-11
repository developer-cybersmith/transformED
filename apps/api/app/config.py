"""
Application configuration via pydantic-settings.
All values are loaded from environment variables (or .env file).
Call get_settings() everywhere — never instantiate Settings() directly.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    debug: bool = False
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins (JSON array string in env)",
    )

    # ── Supabase ──────────────────────────────────────────────────────────────
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_anon_key: str = Field(..., description="Supabase anon/public key")
    supabase_service_role_key: str = Field(
        ..., description="Supabase service-role key (never expose to client)"
    )
    supabase_jwt_secret: str = Field(
        ..., description="JWT secret from Supabase dashboard — used for local verification"
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = Field(..., description="OpenAI API key")

    # ── Anthropic (Phase 2, optional) ─────────────────────────────────────────
    anthropic_api_key: str | None = Field(
        default=None, description="Anthropic API key — optional, Phase 2 only"
    )

    # ── Google AI ──────────────────────────────────────────────────────────────
    google_api_key: str | None = Field(
        default=None,
        description=(
            "Google AI / Vertex AI key — used for Gemini model evaluation AND "
            "(as of Story 2-9) as the production auth key for ImagenProvider "
            "(Imagen 4 Fast, image_generator_node's fallback tier)."
        ),
    )

    # ── TTS providers ─────────────────────────────────────────────────────────
    # Fallback chain: Sarvam → Azure → Browser Speech (PRD §14)
    sarvam_api_key: str = Field(..., description="Sarvam AI Bulbul v2 API key — primary TTS")
    sarvam_voice_id: str = Field(
        default="meera", description="Sarvam Bulbul v2 speaker name for narration synthesis"
    )
    azure_tts_key: str | None = Field(
        default=None, description="Azure Cognitive Services TTS key — fallback"
    )
    azure_tts_region: str = Field(default="centralindia", description="Azure TTS region")
    azure_tts_voice: str = Field(
        default="en-IN-NeerjaNeural",
        description="Azure neural voice for fallback narration synthesis",
    )
    elevenlabs_api_key: str | None = Field(
        default=None, description="ElevenLabs API key — deprecated, replaced by Sarvam"
    )

    # ── HeyGen ────────────────────────────────────────────────────────────────
    heygen_api_key: str = Field(..., description="HeyGen API key for avatar clips")

    # ── Langfuse ──────────────────────────────────────────────────────────────
    langfuse_public_key: str = Field(..., description="Langfuse public key")
    langfuse_secret_key: str = Field(..., description="Langfuse secret key")
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com", description="Langfuse host URL"
    )

    # ── PostHog ───────────────────────────────────────────────────────────────
    posthog_api_key: str = Field(
        default="",
        description="PostHog API key — leave empty to disable event capture",
    )
    posthog_host: str = Field(
        default="https://us.i.posthog.com",
        description=(
            "PostHog ingest endpoint (change to https://eu.i.posthog.com for EU data residency)"
        ),
    )

    # ── Sentry ────────────────────────────────────────────────────────────────
    sentry_dsn: str | None = Field(default=None, description="Sentry DSN — leave empty to disable")

    # ── Admin access (Story 2-25) ─────────────────────────────────────────────
    # `NoDecode` disables pydantic-settings' default behavior of trying to
    # JSON-decode any list-typed env value before validation runs — without
    # it, a non-JSON comma-separated string (the documented format below)
    # raises a SettingsError before _parse_admin_emails ever sees it. With
    # NoDecode, the raw env string always reaches the validator untouched,
    # which then handles both a JSON array and a comma-separated string itself.
    admin_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "Comma-separated allowlist of admin emails (ADMIN_EMAILS env var). "
            "Also accepts a JSON array string. "
            "Checked against the JWT's `email` claim by require_admin(). "
            "Minimal viable admin gate — no DB migration required; see "
            "docs/stories/2-25-sprint2-audit-gapfix-dev1-items.md Dev Notes."
        ),
    )

    @field_validator("admin_emails", mode="before")
    @classmethod
    def _parse_admin_emails(cls, v: object) -> object:
        # v is either a raw env string (comma-separated or a JSON array
        # literal, thanks to NoDecode above) or an already-built list (when
        # Settings() is constructed directly, e.g. in tests). Story 2-25 code
        # review: an earlier version of this validator skipped lowercasing
        # entirely for list input, silently locking out any admin whose JWT
        # email casing differed — normalize case on every path here.
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                return [email.strip().lower() for email in parsed if str(email).strip()]
            return [email.strip().lower() for email in v.split(",") if email.strip()]
        if isinstance(v, list):
            return [
                email.strip().lower() for email in v if isinstance(email, str) and email.strip()
            ]
        return v

    # ── Cost limits (PRD §12) ─────────────────────────────────────────────────
    max_lesson_cost_usd: float = Field(
        default=3.00,
        description="Hard ceiling per lesson pipeline run in USD",
    )
    max_daily_spend_per_user_usd: float = Field(
        default=10.00,
        description="Daily per-user AI spend cap in USD",
    )

    # ── Book-scale chapter generation gates (Story 1-14, book-scale Phase 6) ──
    max_chapter_pages: int = Field(
        default=200,
        ge=1,
        description=(
            "Refuse to generate a lesson from a chapter spanning more than this "
            "many pages (page_end - page_start + 1, read from the chapters row, "
            "never from client input). This is the CATASTROPHE gate, not the "
            "truncation gate: it must sit above every real chapter, and the "
            "largest measured across the 8-book Phase 1 corpus is 138 pages "
            "(D2L Appendix A; medians 10-44). 200 clears that with headroom and "
            "still refuses a rung-5 whole-document 'chapter' (1,151/1,671 pages), "
            "which is the failure this effort exists to fix. A lower cap (80) "
            "would refuse a legitimate chapter and break the project's success "
            "criterion. Truncation is warned about separately at 40 pages "
            "(router._TRUNCATION_WARN_PAGES)."
        ),
    )
    max_concurrent_generations_per_user: int = Field(
        default=3,
        ge=1,
        description=(
            "Maximum lessons in status='generating' one user may have at once; "
            "at or above this, POST .../chapters/{id}/lessons returns 429 with "
            "Retry-After. This — not the rate limit — is the control that "
            "actually bounds per-user spend: a rate limit caps request RATE, "
            "while this caps concurrent pipelines, each of which can cost up to "
            "max_lesson_cost_usd."
        ),
    )

    # ── LLM model names ────────────────────────────────────────────────────────
    # All model IDs are env-var driven. Never hardcode model strings in business logic.
    # Status: evaluation sprint planned for Sprint 1, Week 1.
    # Defaults below are conservative (confirmed working). Swap via env vars to test.
    llm_lesson_planner: str = Field(
        default="gpt-4o",
        description=(
            "Premium model for lesson-planner node. "
            "Eval candidates: gpt-4o, claude-3-5-sonnet-20241022, o1-mini."
        ),
    )
    llm_slide_generator: str = Field(
        default="gpt-4o",
        description=(
            "Premium model for slide-generator node. "
            "Shares eval candidates with llm_lesson_planner."
        ),
    )
    llm_mini: str = Field(
        default="gpt-4o-mini",
        description=(
            "Economy model for quiz, jargon, complexity, narration, intervention nodes. "
            "Eval candidates: gpt-4o-mini, gemini-2.0-flash."
        ),
    )
    llm_tutor: str = Field(
        default="gpt-4o",
        description=(
            "Model for Phase 2 tutor Q&A. Eval candidates: gpt-4o, claude-3-5-sonnet-20241022."
        ),
    )

    # ── CES weights (PRD §11) ─────────────────────────────────────────────────
    ces_weight_quiz: float = Field(default=0.35, ge=0.0, le=1.0)
    ces_weight_teachback: float = Field(default=0.25, ge=0.0, le=1.0)
    ces_weight_behavioral: float = Field(default=0.20, ge=0.0, le=1.0)
    ces_weight_head_pose: float = Field(default=0.12, ge=0.0, le=1.0)
    ces_weight_blink: float = Field(default=0.08, ge=0.0, le=1.0)
    ces_threshold: float = Field(
        default=50.0,
        description="CES score below this triggers an intervention",
    )

    @model_validator(mode="after")
    def _ces_weights_must_sum_to_one(self) -> Settings:
        total = (
            self.ces_weight_quiz
            + self.ces_weight_teachback
            + self.ces_weight_behavioral
            + self.ces_weight_head_pose
            + self.ces_weight_blink
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"CES weights must sum to 1.0 (got {total:.4f}). Check CES_WEIGHT_* env vars."
            )
        return self

    # ── CES Baseline (Sprint 3 Task 2) ───────────────────────────────────────
    ces_baseline_window: int = Field(
        default=5,
        ge=1,
        le=50,
        description=(
            "Number of most-recent completed sessions to average for the per-learner CES baseline"
        ),
    )
    ces_baseline_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        description="TTL for the Redis user:{user_id}:ces_baseline key, in seconds (default 24 h)",
    )

    # ── Learner DNA Fusion (Sprint 3 Task 3) ──────────────────────────────────
    dna_ema_retain: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "EMA retention weight for Learner DNA dimension updates. "
            "new = retain * old + (1 - retain) * session_signal. "
            "Default 0.7 means each session contributes 30% of the new value."
        ),
    )

    # ── WebSocket tuning ──────────────────────────────────────────────────────
    ws_signal_gap_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description=(
            "Maximum seconds to wait for a WebSocket message before treating "
            "the gap as a signal-gap and finalising the session (env: WS_SIGNAL_GAP_SECONDS). "
            "Default 60s — long enough for students to read a complex slide without disconnecting."
        ),
    )

    # ── Intervention tuning ───────────────────────────────────────────────────
    intervention_cooldown_seconds: int = Field(
        default=120,
        description="Minimum seconds between successive interventions (PRD §10)",
    )
    max_distraction_per_session: int = Field(
        default=3,
        description="Maximum number of distraction interventions per session before escalating",
    )

    # ── Learner Mode — Q&A phase lengths per tier ─────────────────────────────
    learner_tier_t1_qa_seconds: int = Field(
        default=600,
        description="Q&A phase duration in seconds for T1 (beginner) tier",
    )
    learner_tier_t2_qa_seconds: int = Field(
        default=300,
        description="Q&A phase duration in seconds for T2 (intermediate) tier",
    )
    learner_tier_t3_qa_seconds: int = Field(
        default=150,
        description="Q&A phase duration in seconds for T3 (advanced) tier",
    )
    learner_tier_default_qa_seconds: int = Field(
        default=300,
        description="Q&A phase duration in seconds when tier is unknown or absent (T2 equivalent)",
    )

    # ── PDF extraction ────────────────────────────────────────────────────────
    ocr_text_yield_threshold: int = Field(
        default=50,
        description=(
            "Min chars/page from pdfplumber before Tesseract OCR fallback "
            "(env: OCR_TEXT_YIELD_THRESHOLD)"
        ),
    )

    # ── Chunking (Node 3) ─────────────────────────────────────────────────────
    chunk_target_tokens: int = Field(
        default=512,
        description="Target token count per chunk for the chunking node (cl100k_base tokens)",
    )
    chunk_overlap_tokens: int = Field(
        default=64,
        description="Token overlap between consecutive chunks to preserve context continuity",
    )
    embedding_tokenizer: str = Field(
        default="cl100k_base",
        description="tiktoken encoding name used for token counting (must match embedding model)",
    )

    # ── Structure segmentation bounds (Story 2-16, RC-1 over-segmentation) ─────
    structure_min_section_chars: int = Field(
        default=200,
        ge=0,
        description=(
            "Minimum body length (chars) for a detected section to stand alone. "
            "Sections below this are coalesced into a neighbour (text-preserving) "
            "so numbered how-to steps are not each treated as a section."
        ),
    )
    structure_max_sections: int = Field(
        default=15,
        ge=1,
        description=(
            "Upper bound on sections handed to the generation pipeline. Above "
            "this, adjacent sections are merged (text-preserving) down to the "
            "cap — keeps lesson density in the T2 range and keeps lesson_planner "
            "reliable. Independent of and well below the _MAX_PHASE1_SECTIONS "
            "fan-out DoS cap (60)."
        ),
    )

    # ── lesson_planner batching (Story 2-16, RC-3 planner 1:1 brittleness) ─────
    lesson_planner_batch_size: int = Field(
        default=15,
        gt=0,
        description=(
            "Max segment summaries sent to lesson_planner in a single LLM "
            "completion. Above this, summaries are split into ordered batches so "
            "the model reliably echoes every segment_id 1:1; at or below it the "
            "planner makes exactly one call (unchanged behaviour)."
        ),
    )

    # ── Narration timestamps (Story 2-19, package_builder) ────────────────────
    narration_words_per_minute: int = Field(
        default=150,
        gt=0,
        description=(
            "Assumed narration speaking rate used to ESTIMATE each segment's audio "
            "duration from its script word count, so package_builder can distribute "
            "the segment's slides across a contiguous timestamp track (real "
            "forced-alignment / word timing remains deferred)."
        ),
    )
    default_ms_per_slide: int = Field(
        default=5000,
        gt=0,
        description=(
            "Fallback per-slide duration (ms) when a segment's narration script is "
            "empty (word_count 0), so the estimated timestamp track is still "
            "non-degenerate (start_ms < end_ms)."
        ),
    )

    # ── Embeddings (Node 4) ───────────────────────────────────────────────────
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model — outputs 1536-dim vectors; fixed for Sprint 1. "
        "Stored embeddings are NEVER regenerated (CLAUDE.md rule).",
    )
    embedding_dimensions: int = Field(
        default=1536,
        description="Output vector dimensions of the embedding model. "
        "Must match the model; stored in embedding_metadata per chunk.",
    )
    embed_batch_token_budget: int = Field(
        default=100_000,
        description="Max tokens per OpenAI embeddings request batch (API hard cap is 300k). "
        "Batches are packed by chunk token_count up to this budget (Story 2-0 AC-6).",
    )

    # ── OpenAI client transport (Story 2-32) ──────────────────────────────────
    # The SDK defaults to max_retries=2 and a 600s read timeout. Layering
    # with_retry(max_attempts=3) on top of that is 3 x 3 = 9 HTTP requests per
    # logical call, and a worst case of tens of minutes against arq_job_timeout_s.
    # We set max_retries=0 and own retry/backoff in `core/retry.py`, which is the
    # only layer that knows the PRD §14 rules and the circuit-breaker state.
    openai_request_timeout_s: float = Field(
        default=120.0,
        description="Read/write/pool timeout for OpenAI chat + embeddings calls (seconds). "
        "Connect stays at 5s — see the note on openai_image_request_timeout_s.",
    )
    openai_image_request_timeout_s: float = Field(
        default=180.0,
        description="Read/write/pool timeout for OpenAI image generation (seconds) — "
        "image calls are legitimately slower than chat, so they get their own budget. "
        "NOTE: always build httpx.Timeout(..., connect=5.0) explicitly; passing a bare "
        "float to the SDK sets connect to that value too, destroying the 5s connect "
        "guard and making hangs WORSE than the default.",
    )

    # ── ARQ / pipeline timeouts (Story 2-0 AC-5) ──────────────────────────────
    # Invariant (contract-tested): arq_job_timeout_s >= extract_timeout_cap_s + 300
    # so the extract subprocess timeout ALWAYS fires before ARQ cancels the job,
    # letting extract_node's own cleanup (killpg) run instead of orphaning the child.
    arq_job_timeout_s: int = Field(
        default=1800,
        description="ARQ job_timeout for the whole 15-node pipeline (seconds)",
    )
    extract_timeout_cap_s: int = Field(
        default=1500,
        description="Hard cap on the PDF-extraction subprocess timeout (seconds)",
    )
    extract_timeout_base_s: int = Field(
        default=180,
        description="Base extraction timeout before the per-page allowance is added (seconds)",
    )
    extract_timeout_per_page_s: float = Field(
        default=3.0,
        description="Per-page allowance added to the extraction timeout (seconds/page). "
        "Calibrated 2026-07-10 against a real 41-page table-bearing PDF: "
        "page-scoped docling extraction measured 206-216s while the old "
        "120 + 1.3s/page formula granted only 183.7s — table pages cost "
        "docling ML time the flat rate must absorb.",
    )

    @model_validator(mode="after")
    def _extract_timeout_must_fit_inside_arq_timeout(self) -> Settings:
        required = self.extract_timeout_cap_s + 300
        if self.arq_job_timeout_s < required:
            raise ValueError(
                f"arq_job_timeout_s ({self.arq_job_timeout_s}) must be >= "
                f"extract_timeout_cap_s + 300 ({required}) so the extract "
                "subprocess timeout fires before ARQ cancels the job. "
                "Check ARQ_JOB_TIMEOUT_S / EXTRACT_TIMEOUT_CAP_S env vars."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    Usage::

        from app.config import get_settings

        settings = get_settings()
    """
    return Settings()
