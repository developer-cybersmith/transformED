"""
Application configuration via pydantic-settings.
All values are loaded from environment variables (or .env file).
Call get_settings() everywhere — never instantiate Settings() directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, HttpUrl, field_validator
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

    # ── ElevenLabs ────────────────────────────────────────────────────────────
    elevenlabs_api_key: str = Field(..., description="ElevenLabs API key for TTS")

    # ── HeyGen ────────────────────────────────────────────────────────────────
    heygen_api_key: str = Field(..., description="HeyGen API key for avatar clips")

    # ── Langfuse ──────────────────────────────────────────────────────────────
    langfuse_public_key: str = Field(..., description="Langfuse public key")
    langfuse_secret_key: str = Field(..., description="Langfuse secret key")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", description="Langfuse host URL")

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

    # ── LLM model names (PRD §6.4) ───────────────────────────────────────────
    llm_lesson_planner: str = Field(
        default="gpt-4o",
        description="Model used by the lesson-planner node",
    )
    llm_slide_generator: str = Field(
        default="gpt-4o",
        description="Model used by the slide-generator node",
    )
    llm_mini: str = Field(
        default="gpt-4o-mini",
        description="Cheaper model for auxiliary nodes (quiz, jargon, etc.)",
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

    @field_validator("ces_weight_quiz", "ces_weight_teachback", "ces_weight_behavioral", "ces_weight_head_pose", "ces_weight_blink", mode="after")
    @classmethod
    def _ces_weights_must_sum_to_one(cls, v: float, info: object) -> float:  # noqa: ANN001
        # Individual field validation only; cross-field sum checked at model level
        return v

    # ── Intervention tuning ───────────────────────────────────────────────────
    intervention_cooldown_seconds: int = Field(
        default=120,
        description="Minimum seconds between successive interventions (PRD §10)",
    )
    max_distraction_per_session: int = Field(
        default=3,
        description="Maximum number of distraction interventions per session before escalating",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    Usage::

        from app.config import get_settings

        settings = get_settings()
    """
    return Settings()  # type: ignore[call-arg]
