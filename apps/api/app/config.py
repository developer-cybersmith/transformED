"""
Application configuration via pydantic-settings.
All values are loaded from environment variables (or .env file).
Call get_settings() everywhere — never instantiate Settings() directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    supabase_service_role_key: str = Field(..., description="Supabase service-role key (never expose to client)")
    supabase_jwt_secret: str = Field(..., description="JWT secret from Supabase dashboard — used for local verification")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = Field(..., description="OpenAI API key")

    # ── Anthropic (Phase 2, optional) ─────────────────────────────────────────
    anthropic_api_key: str | None = Field(default=None, description="Anthropic API key — optional, Phase 2 only")

    # ── Google AI (optional — Gemini evaluation in Sprint 1) ──────────────────
    google_api_key: str | None = Field(default=None, description="Google AI / Vertex AI key — optional, for Gemini model evaluation")

    # ── TTS providers ─────────────────────────────────────────────────────────
    # Fallback chain: Sarvam → Azure → Browser Speech (PRD §14)
    sarvam_api_key: str = Field(..., description="Sarvam AI Bulbul v2 API key — primary TTS")
    azure_tts_key: str | None = Field(default=None, description="Azure Cognitive Services TTS key — fallback")
    azure_tts_region: str = Field(default="centralindia", description="Azure TTS region")
    elevenlabs_api_key: str | None = Field(default=None, description="ElevenLabs API key — deprecated, replaced by Sarvam")

    # ── HeyGen ────────────────────────────────────────────────────────────────
    heygen_api_key: str = Field(..., description="HeyGen API key for avatar clips")

    # ── Langfuse ──────────────────────────────────────────────────────────────
    langfuse_public_key: str = Field(..., description="Langfuse public key")
    langfuse_secret_key: str = Field(..., description="Langfuse secret key")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", description="Langfuse host URL")

    # ── PostHog ───────────────────────────────────────────────────────────────
    posthog_api_key: str = Field(
        default="",
        description="PostHog API key — leave empty to disable event capture",
    )
    posthog_host: str = Field(
        default="https://us.i.posthog.com",
        description="PostHog ingest endpoint (change to https://eu.i.posthog.com for EU data residency)",
    )

    # ── Sentry ────────────────────────────────────────────────────────────────
    sentry_dsn: str | None = Field(default=None, description="Sentry DSN — leave empty to disable")

    # ── Cost limits (PRD §12) ─────────────────────────────────────────────────
    max_lesson_cost_usd: float = Field(
        default=3.00,
        description="Hard ceiling per lesson pipeline run in USD",
    )
    max_daily_spend_per_user_usd: float = Field(
        default=10.00,
        description="Daily per-user AI spend cap in USD",
    )

    # ── LLM model names ────────────────────────────────────────────────────────
    # All model IDs are env-var driven. Never hardcode model strings in business logic.
    # Status: evaluation sprint planned for Sprint 1, Week 1.
    # Defaults below are conservative (confirmed working). Swap via env vars to test.
    llm_lesson_planner: str = Field(
        default="gpt-4o",
        description="Premium model for lesson-planner node. Eval candidates: gpt-4o, claude-3-5-sonnet-20241022, o1-mini.",
    )
    llm_slide_generator: str = Field(
        default="gpt-4o",
        description="Premium model for slide-generator node. Shares eval candidates with llm_lesson_planner.",
    )
    llm_mini: str = Field(
        default="gpt-4o-mini",
        description="Economy model for quiz, jargon, complexity, narration, intervention nodes. Eval candidates: gpt-4o-mini, gemini-2.0-flash.",
    )
    llm_tutor: str = Field(
        default="gpt-4o",
        description="Model for Phase 2 tutor Q&A. Eval candidates: gpt-4o, claude-3-5-sonnet-20241022.",
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
    def _ces_weights_must_sum_to_one(self) -> "Settings":
        total = (
            self.ces_weight_quiz
            + self.ces_weight_teachback
            + self.ces_weight_behavioral
            + self.ces_weight_head_pose
            + self.ces_weight_blink
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"CES weights must sum to 1.0 (got {total:.4f}). "
                "Check CES_WEIGHT_* env vars."
            )
        return self

    # ── Intervention tuning ───────────────────────────────────────────────────
    intervention_cooldown_seconds: int = Field(
        default=120,
        description="Minimum seconds between successive interventions (PRD §10)",
    )
    max_distraction_per_session: int = Field(
        default=3,
        description="Maximum number of distraction interventions per session before escalating",
    )

    # ── PDF extraction ────────────────────────────────────────────────────────
    ocr_text_yield_threshold: int = Field(
        default=50,
        description="Min chars/page from pdfplumber before Tesseract OCR fallback (env: OCR_TEXT_YIELD_THRESHOLD)",
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    Usage::

        from app.config import get_settings

        settings = get_settings()
    """
    return Settings()  # type: ignore[call-arg]
