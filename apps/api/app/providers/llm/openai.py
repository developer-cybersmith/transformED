"""
OpenAI LLM provider implementation.

Responsibilities
----------------
- Implements LLMProvider using the ``openai`` async client.
- Tracks token usage via Langfuse for cost observability.
- Applies circuit breaker (``openai`` provider key) before every call.
- Integrates with the cost tracker to accumulate per-lesson spend.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx
from langfuse import Langfuse
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.config import get_settings
from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.langfuse import deterministic_trace_context, get_langfuse
from app.core.retry import with_retry
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "openai"

# Approximate cost per 1 000 tokens (USD) — used for cost tracking estimates.
# Update these when OpenAI changes pricing.
_COST_PER_1K: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.000150, "output": 0.000600},
}


def _price_tokens(
    model: str, input_tokens: int | None, output_tokens: int | None
) -> tuple[float, float, float]:
    """Return (input_cost, output_cost, total_cost) in USD for one completion.

    Extracted from `_maybe_accumulate_cost` (Story 4-28) so a caller that
    needs a bare cost figure — with no lesson_id, no accumulation side
    effect, no $3.00 ceiling check (tutor Q&A's `complete_with_meta`) — gets
    the exact same fail-closed pricing/clamping behavior as the
    lesson-generation path, not a second, potentially-drifting copy of it.
    Story 2-33's fail-closed contract is preserved verbatim: an unpriced
    model is charged at the most expensive KNOWN rate, never skipped.
    """
    pricing = _COST_PER_1K.get(model)
    if pricing is None:
        # Fail CLOSED — see _maybe_accumulate_cost's own docstring for why
        # (Story 2-33: an early return here let an unpriced model spend
        # without limit).
        pricing = {
            "input": max(p["input"] for p in _COST_PER_1K.values()),
            "output": max(p["output"] for p in _COST_PER_1K.values()),
        }
        logger.error(
            "No pricing data for model %r — charging at the most expensive known rate "
            "($%.6f/1k in, $%.6f/1k out).",
            model,
            pricing["input"],
            pricing["output"],
        )

    safe_input = max(0, input_tokens or 0)
    safe_output = max(0, output_tokens or 0)
    if (input_tokens or 0) < 0 or (output_tokens or 0) < 0:
        logger.error(
            "Negative token counts from model %r (in=%s, out=%s) — clamped to 0. "
            "The resulting cost is now an UNDER-estimate.",
            model,
            input_tokens,
            output_tokens,
        )
    elif input_tokens is None or output_tokens is None:
        logger.warning(
            "Missing token counts from model %r (in=%s, out=%s) — charging the known half "
            "only. The resulting cost is an under-estimate.",
            model,
            input_tokens,
            output_tokens,
        )

    input_cost = safe_input / 1000 * pricing["input"]
    output_cost = safe_output / 1000 * pricing["output"]
    return input_cost, output_cost, input_cost + output_cost


def _safe_trace(call: Callable[[], Any]) -> Any | None:  # noqa: ANN401
    """Run a Langfuse tracing call; observability failures must NEVER fail the pipeline."""
    try:
        return call()
    except Exception:
        # WARNING (not DEBUG): an observability outage must be visible in prod
        # logs even though it never fails the pipeline.
        logger.warning("Langfuse tracing call failed — ignored, pipeline continues", exc_info=True)
        return None


class OpenAILLMProvider(LLMProvider):
    """Production LLM provider backed by OpenAI."""

    def __init__(self, lesson_id: str | None = None) -> None:
        settings = get_settings()
        # Story 2-32: max_retries=0 — the SDK defaults to 2, so layering
        # with_retry(max_attempts=N) on top of it means N x 3 HTTP requests per
        # logical call with two independent backoff schedules. `core/retry.py` is
        # the only layer that knows the PRD §14 rules and the circuit-breaker
        # state, so it owns retry entirely.
        #
        # Timeout is an explicit httpx.Timeout, NEVER a bare float: a bare float
        # sets connect= to the same value, replacing the SDK's 5s connect guard
        # with (here) 120s and making a connect hang strictly worse.
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            max_retries=0,
            timeout=httpx.Timeout(settings.openai_request_timeout_s, connect=5.0),
        )
        # AC-3 never-fail clause: a bad LANGFUSE_* env must degrade to
        # no-tracing, never crash the provider mid-job.
        self._langfuse: Langfuse | None
        try:
            self._langfuse = get_langfuse()
        except Exception:
            logger.warning(
                "Langfuse init failed — tracing disabled for OpenAILLMProvider",
                exc_info=True,
            )
            self._langfuse = None
        self._lesson_id = lesson_id

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> str:
        """Return a plain-text chat completion from OpenAI.

        Story 2-32 AC-3: breaker accounting lives HERE, outside the retry
        decorator, so one logical call records at most one outcome no matter how
        many times `_complete_inner` retries. See `guard_breaker`.
        """
        return await guard_breaker(
            _PROVIDER_KEY, lambda: self._complete_inner(messages, model, **kwargs)
        )

    async def complete_with_meta(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> tuple[str, str | None, float]:
        """Return (content, finish_reason, cost_usd) — additive, Story 4-28.

        `complete()` above is completely unchanged and remains every existing
        pipeline node's call path (lesson planner, slide generator, etc.) —
        this is a NEW, separate public method, used only by tutor Q&A
        (`assessment/service.py::answer_tutor_question`), which needs
        `finish_reason` (so a `max_tokens`-truncated answer is visible on the
        record, not indistinguishable from a complete one — Story 4-28 Scale
        & Load Q2) and a per-call `cost_usd` that does NOT depend on
        `self._lesson_id` (Q&A is priced per question, never accumulated
        against any lesson's $3.00 generation ceiling — a different unit of
        work, see that story's Dev Notes).

        Deliberately NOT merged into `_complete_inner`/`complete()`'s own
        retry+breaker+tracing scaffolding to avoid any risk to the
        heavily-used existing path — some duplication here is the safer
        trade against destabilizing every pipeline node's completion call.
        """
        return await guard_breaker(
            _PROVIDER_KEY, lambda: self._complete_inner_with_meta(messages, model, **kwargs)
        )

    @with_retry(max_attempts=3)
    async def _complete_inner_with_meta(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> tuple[str, str | None, float]:
        """Retried body of `complete_with_meta`. Records NO breaker outcome — see AC-3."""
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        response: ChatCompletion = await self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        choice = response.choices[0]
        content = choice.message.content or ""
        finish_reason = choice.finish_reason

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        _input_cost, _output_cost, cost = _price_tokens(model, prompt_tokens, completion_tokens)

        return content, finish_reason, cost

    @with_retry(max_attempts=3)
    async def _complete_inner(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> str:
        """Retried body of `complete`. Records NO breaker outcome — see AC-3."""
        # Checked on EVERY attempt (AC-4 documented semantics): if concurrent
        # traffic trips the breaker while we are backing off, stop rather than
        # finish the remaining attempts against a provider known to be down.
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        # Langfuse 4.x (OTel-based): one generation-type observation per call.
        # Tracing is best-effort — the OpenAI call must never fail because of it.
        # self._langfuse is None when init failed (AC-3) — skip tracing entirely.
        generation = None
        langfuse = self._langfuse
        if langfuse is not None:
            generation = _safe_trace(
                lambda: langfuse.start_observation(
                    # Verb-first, model-agnostic name per Langfuse's naming
                    # guidance (best-practices.md, fetched fresh in the
                    # Langfuse-skill self-audit): names are referenced by
                    # evaluators/dashboards/saved filters and should describe
                    # the ACTION, not the model — the model is already the
                    # separate `model=` attribute below.
                    name="generate-chat-completion",
                    as_type="generation",
                    model=model,
                    input=messages,
                    metadata={"model": model, "lesson_id": self._lesson_id},
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            response: ChatCompletion = await self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
            content = response.choices[0].message.content or ""

            # Cost accumulation reads response.usage directly — never depends on tracing.
            usage = response.usage
            if usage:
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
                if generation is not None:
                    _safe_trace(
                        lambda: generation.update(
                            output=content,
                            usage_details={
                                "input": prompt_tokens,
                                "output": completion_tokens,
                            },
                        )
                    )
                await self._maybe_accumulate_cost(
                    model, prompt_tokens, completion_tokens, generation=generation
                )

            return content

        except Exception as exc:
            if generation is not None:
                error_message = str(exc)
                _safe_trace(lambda: generation.update(level="ERROR", status_message=error_message))
            raise

        finally:
            if generation is not None:
                _safe_trace(generation.end)

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_format: type,
        **kwargs: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Return a structured completion parsed into *response_format* (a Pydantic model).

        Story 2-32 AC-3: breaker accounting is outside the retry decorator — a
        second `@with_retry` call site that needs the same fix as `complete`.
        """
        return await guard_breaker(
            _PROVIDER_KEY,
            lambda: self._complete_structured_inner(messages, model, response_format, **kwargs),
        )

    @with_retry(max_attempts=3)
    async def _complete_structured_inner(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_format: type,
        **kwargs: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Retried body of `complete_structured`. Records NO breaker outcome."""
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        # self._langfuse is None when init failed (AC-3) — skip tracing entirely.
        generation = None
        langfuse = self._langfuse
        if langfuse is not None:
            generation = _safe_trace(
                lambda: langfuse.start_observation(
                    name="generate-structured-completion",
                    as_type="generation",
                    model=model,
                    input=messages,
                    metadata={
                        "model": model,
                        "response_format": response_format.__name__,
                        "lesson_id": self._lesson_id,
                    },
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            # Use OpenAI's beta structured-output parse helper
            response = await self._client.beta.chat.completions.parse(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                response_format=response_format,
                **kwargs,
            )
            parsed = response.choices[0].message.parsed

            # Cost accumulation reads response.usage directly — never depends on tracing.
            usage = response.usage
            if usage:
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
                if generation is not None:
                    _safe_trace(
                        lambda: generation.update(
                            output=str(parsed),
                            usage_details={
                                "input": prompt_tokens,
                                "output": completion_tokens,
                            },
                        )
                    )
                await self._maybe_accumulate_cost(
                    model, prompt_tokens, completion_tokens, generation=generation
                )

            return parsed

        except Exception as exc:
            if generation is not None:
                error_message = str(exc)
                _safe_trace(lambda: generation.update(level="ERROR", status_message=error_message))
            raise

        finally:
            if generation is not None:
                _safe_trace(generation.end)

    async def _maybe_accumulate_cost(
        self,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        generation: Any | None = None,  # noqa: ANN401
    ) -> None:
        """Accumulate cost for the current lesson if a lesson_id is set.

        Story 2-33: an unpriced model is charged at the most expensive KNOWN
        rate, never skipped. This method previously returned early when the
        model was absent from `_COST_PER_1K`, so `accumulate_cost` was never
        called, the lesson total stayed at $0.00, and the $3.00 ceiling could
        not fire — an unpriced model spent without limit.

        That mattered because CLAUDE.md mandates "swapping models is an env var
        change only", and its own evaluation-candidate list (Claude 3.5 Sonnet,
        o1-mini, Gemini 2.0 Flash) is mostly absent from the table. Running the
        model evaluation the PRD asks for was exactly what disabled the ceiling.

        The ONLY legitimate early return is `self._lesson_id is None` — a
        provider built outside a pipeline run has no lesson to bill. That case
        is guarded by test_no_early_return_before_accumulate_except_the_lesson_id_guard,
        which fails if any other early exit is reintroduced here.
        """
        if self._lesson_id is None:
            return

        # Review round 2, D17: token counts must never be trusted to be usable
        # ints. `usage.prompt_tokens` is typed `int` by the OpenAI SDK, but
        # CLAUDE.md mandates that swapping models is an env var change only, and
        # OpenAI-COMPATIBLE endpoints do return `null` usage fields. `None` here
        # raised `TypeError: unsupported operand type(s) for /: 'NoneType' and
        # 'int'` — an unknown exception, so `with_retry` would not retry it and
        # the node died. Verified reachable before this fix.
        #
        # The completion has already been made and BILLED by the provider.
        # Throwing over missing billing metadata would make ARQ re-run and
        # re-pay for the node — turning a reporting gap into real money.
        # Pricing/clamping logic lives in `_price_tokens` (Story 4-28 extraction) —
        # this call site is now identical in behavior to before the extraction.
        input_cost, output_cost, cost = _price_tokens(model, input_tokens, output_tokens)

        # S3-5: mirror usage_details' input/output split onto Langfuse's own
        # cost_details field, the same field the other 4 priced providers
        # (Sarvam, Azure TTS, Imagen, GPT Image) already use — so this number
        # is visible on the span itself, not just in cost_tracker's Redis total.
        if generation is not None:
            _safe_trace(
                lambda: generation.update(cost_details={"input": input_cost, "output": output_cost})
            )

        from app.core.cost_tracker import accumulate_cost, check_ceiling  # lazy to avoid circular

        total = await accumulate_cost(self._lesson_id, cost)
        if await check_ceiling(self._lesson_id):
            from app.core.cost_tracker import CostCeilingError

            raise CostCeilingError(
                f"Lesson {self._lesson_id} exceeded cost ceiling at ${total:.4f} — pipeline aborted"
            )
