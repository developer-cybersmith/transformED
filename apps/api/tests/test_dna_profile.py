"""
Tests for Story 3-26 — Learner DNA Profile Text Generation (GPT-4o-mini).

Test count: 23
ACs covered: 1-19

Modules under test:
  - app.modules.assessment.dna_profile  (refresh_dna_profile)
  - app.modules.assessment.prompts      (_dim_descriptor, build_dna_profile_prompt,
                                         generate_dna_profile_text)
"""
from __future__ import annotations

import ast
import pathlib

import pytest
import pytest_asyncio  # noqa: F401 — registers asyncio mode
from unittest.mock import AsyncMock, MagicMock, patch

# ── Test helpers ──────────────────────────────────────────────────────────────

def _settings():
    s = MagicMock()
    s.llm_mini = "gpt-4o-mini"
    s.openai_api_key = "test-key"
    return s


def _all_dims(value: float = 65.0) -> dict[str, float]:
    """Return a 9-dim dict with a uniform value."""
    return {
        "pattern_recognition": value,
        "logical_deduction": value,
        "processing_speed": value,
        "frustration_tolerance": value,
        "persistence": value,
        "help_seeking": value,
        "goal_orientation": value,
        "curiosity_index": value,
        "study_independence": value,
    }


def _supabase_mock(
    badge_labels: list[str] | None = None,
    upsert_raises: bool = False,
    badge_read_raises: bool = False,
    upsert_error: bool = False,
):
    """Mock supabase.table() routing by table name for dna_profile tests."""
    supabase = MagicMock()

    def _resp(data):
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    def _table(name):
        tbl = MagicMock()
        if name == "learner_dna":
            if badge_read_raises:
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = Exception("DB badge read failed")
            else:
                row = {"badge_labels": badge_labels} if badge_labels is not None else None
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp(row)

            if upsert_raises:
                tbl.upsert.return_value.execute.side_effect = Exception("DB upsert failed")
            elif upsert_error:
                err_resp = MagicMock()
                err_resp.error = "some db error"
                err_resp.data = None
                tbl.upsert.return_value.execute.return_value = err_resp
            else:
                tbl.upsert.return_value.execute.return_value = _resp([])
        return tbl

    supabase.table.side_effect = _table
    return supabase


# ── Task 3 Tests ──────────────────────────────────────────────────────────────

# ─ 3.1 __all__ export ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_dunder_all_exports_only_refresh_dna_profile():
    from app.modules.assessment.dna_profile import __all__ as exported
    assert exported == ["refresh_dna_profile"]


# ─ 3.2 Keyword-only enforcement ───────────────────────────────────────────────

@pytest.mark.unit
def test_positional_args_raise_type_error():
    from app.modules.assessment.dna_profile import refresh_dna_profile
    with pytest.raises(TypeError):
        refresh_dna_profile("u1", _all_dims(), 1, MagicMock(), _settings())  # type: ignore[call-arg]


# ─ 3.3–3.7 _dim_descriptor ────────────────────────────────────────────────────

@pytest.mark.unit
def test_dim_descriptor_strong():
    from app.modules.assessment.prompts import _dim_descriptor
    assert _dim_descriptor(82.0) == "strong"


@pytest.mark.unit
def test_dim_descriptor_developing():
    from app.modules.assessment.prompts import _dim_descriptor
    assert _dim_descriptor(62.0) == "developing"


@pytest.mark.unit
def test_dim_descriptor_building():
    from app.modules.assessment.prompts import _dim_descriptor
    assert _dim_descriptor(45.0) == "building"


@pytest.mark.unit
def test_dim_descriptor_emerging():
    from app.modules.assessment.prompts import _dim_descriptor
    assert _dim_descriptor(20.0) == "emerging"


@pytest.mark.unit
def test_dim_descriptor_boundary_75_is_strong():
    from app.modules.assessment.prompts import _dim_descriptor
    assert _dim_descriptor(75.0) == "strong"


# ─ 3.8 build_dna_profile_prompt — no raw floats ───────────────────────────────

@pytest.mark.unit
def test_build_prompt_contains_no_raw_floats():
    from app.modules.assessment.prompts import build_dna_profile_prompt
    import re
    dims = {
        "pattern_recognition": 82.5,
        "logical_deduction": 47.3,
        "processing_speed": 91.1,
        "frustration_tolerance": 33.7,
        "persistence": 68.0,
        "help_seeking": 55.5,
        "goal_orientation": 72.2,
        "curiosity_index": 28.9,
        "study_independence": 60.0,
    }
    result = build_dna_profile_prompt(dims=dims, session_count=3, badge_labels=["Pattern Thinker"])
    # No raw floats like "82.5", "47.3" should appear in the prompt
    for val in dims.values():
        assert str(val) not in result, f"Raw float {val} found in prompt"
    # Ensure descriptors appear instead
    assert "strong" in result or "developing" in result or "building" in result or "emerging" in result


# ─ 3.9 build_dna_profile_prompt — badges included ─────────────────────────────

@pytest.mark.unit
def test_build_prompt_with_badges_includes_badge_text():
    from app.modules.assessment.prompts import build_dna_profile_prompt
    result = build_dna_profile_prompt(
        dims=_all_dims(70.0),
        session_count=2,
        badge_labels=["Pattern Thinker", "Curious Explorer"],
    )
    assert "Pattern Thinker" in result
    assert "Curious Explorer" in result


# ─ 3.10 build_dna_profile_prompt — empty badges ───────────────────────────────

@pytest.mark.unit
def test_build_prompt_empty_badges_says_no_badges():
    from app.modules.assessment.prompts import build_dna_profile_prompt
    result = build_dna_profile_prompt(dims=_all_dims(), session_count=1, badge_labels=[])
    assert "No badges" in result


# ─ 3.11 build_dna_profile_prompt — injection sanitization ─────────────────────

@pytest.mark.unit
def test_build_prompt_sanitizes_injection_in_badge_labels():
    from app.modules.assessment.prompts import build_dna_profile_prompt
    malicious = "<script>alert('xss')</script>"
    result = build_dna_profile_prompt(dims=_all_dims(), session_count=1, badge_labels=[malicious])
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


# ─ 3.12 build_dna_profile_prompt — session_count=0 ───────────────────────────

@pytest.mark.unit
def test_build_prompt_session_count_zero_says_first_session():
    from app.modules.assessment.prompts import build_dna_profile_prompt
    result = build_dna_profile_prompt(dims=_all_dims(), session_count=0, badge_labels=[])
    assert "first session" in result.lower()


# ─ 3.13 build_dna_profile_prompt — session_count positive ────────────────────

@pytest.mark.unit
def test_build_prompt_session_count_positive():
    from app.modules.assessment.prompts import build_dna_profile_prompt
    result = build_dna_profile_prompt(dims=_all_dims(), session_count=5, badge_labels=[])
    assert "5" in result


# ─ 3.14 generate_dna_profile_text — appends DPDP disclaimer ──────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_profile_text_appends_dpdp_disclaimer():
    from app.modules.assessment.prompts import generate_dna_profile_text, DPDP_DISCLAIMER
    provider = MagicMock()
    provider.complete = AsyncMock(return_value="You learn well through patterns.")

    with patch("app.modules.assessment.prompts.get_settings", return_value=_settings()):
        result = await generate_dna_profile_text(
            dims=_all_dims(70.0),
            session_count=2,
            badge_labels=["Pattern Thinker"],
            provider=provider,
        )

    assert result.endswith(DPDP_DISCLAIMER)


# ─ 3.15 generate_dna_profile_text — uses llm_mini from settings ───────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_profile_text_uses_llm_mini_from_settings():
    from app.modules.assessment.prompts import generate_dna_profile_text
    provider = MagicMock()
    provider.complete = AsyncMock(return_value="Your learning profile.")

    mock_settings = _settings()
    mock_settings.llm_mini = "test-mini-model"

    with patch("app.modules.assessment.prompts.get_settings", return_value=mock_settings):
        await generate_dna_profile_text(
            dims=_all_dims(),
            session_count=1,
            badge_labels=[],
            provider=provider,
        )

    provider.complete.assert_called_once()
    call_kwargs = provider.complete.call_args
    assert call_kwargs.kwargs.get("model") == "test-mini-model" or \
           (call_kwargs.args and call_kwargs.args[1] == "test-mini-model") or \
           call_kwargs.kwargs.get("model") == "test-mini-model"


# ─ 3.16 refresh_dna_profile — success returns profile_text ───────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_dna_profile_success_returns_profile_text():
    from app.modules.assessment.dna_profile import refresh_dna_profile
    from app.modules.assessment.prompts import DPDP_DISCLAIMER

    supabase = _supabase_mock(badge_labels=["Pattern Thinker"])
    provider_instance = MagicMock()
    provider_instance.complete = AsyncMock(return_value="You learn through patterns.")

    with patch("app.modules.assessment.dna_profile.OpenAILLMProvider", return_value=provider_instance), \
         patch("app.modules.assessment.prompts.get_settings", return_value=_settings()):
        result = await refresh_dna_profile(
            user_id="u1",
            dims=_all_dims(72.0),
            session_count=3,
            supabase=supabase,
            settings=_settings(),
        )

    assert result is not None
    assert DPDP_DISCLAIMER in result


# ─ 3.17 refresh_dna_profile — upsert payload only has user_id + profile_text ──

@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_dna_profile_upsert_payload_only_has_user_id_and_profile_text():
    from app.modules.assessment.dna_profile import refresh_dna_profile

    captured_payload: dict = {}

    supabase = MagicMock()

    def _resp(data):
        r = MagicMock(); r.data = data; r.error = None; return r

    def _table(name):
        tbl = MagicMock()
        if name == "learner_dna":
            tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp({"badge_labels": []})

            def _upsert(payload, **kwargs):
                captured_payload.update(payload)
                mock_resp = MagicMock()
                mock_resp.error = None
                mock_resp.data = []
                result_mock = MagicMock()
                result_mock.execute.return_value = mock_resp
                return result_mock

            tbl.upsert.side_effect = _upsert
        return tbl

    supabase.table.side_effect = _table

    provider_instance = MagicMock()
    provider_instance.complete = AsyncMock(return_value="You are a strong learner.")

    with patch("app.modules.assessment.dna_profile.OpenAILLMProvider", return_value=provider_instance), \
         patch("app.modules.assessment.prompts.get_settings", return_value=_settings()):
        await refresh_dna_profile(
            user_id="u1",
            dims=_all_dims(75.0),
            session_count=3,
            supabase=supabase,
            settings=_settings(),
        )

    # Payload MUST only contain user_id and profile_text
    assert set(captured_payload.keys()) == {"user_id", "profile_text"}
    # Ensure no dimension columns leaked in
    forbidden = {"pattern_recognition", "logical_deduction", "badge_labels", "session_count"}
    assert not (forbidden & set(captured_payload.keys()))


# ─ 3.18 refresh_dna_profile — LLM failure returns None ───────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_dna_profile_llm_failure_returns_none():
    from app.modules.assessment.dna_profile import refresh_dna_profile

    supabase = _supabase_mock(badge_labels=[])
    provider_instance = MagicMock()
    provider_instance.complete = AsyncMock(side_effect=RuntimeError("Circuit breaker open"))

    with patch("app.modules.assessment.dna_profile.OpenAILLMProvider", return_value=provider_instance), \
         patch("app.modules.assessment.prompts.get_settings", return_value=_settings()):
        result = await refresh_dna_profile(
            user_id="u1",
            dims=_all_dims(),
            session_count=2,
            supabase=supabase,
            settings=_settings(),
        )

    assert result is None


# ─ 3.19 refresh_dna_profile — upsert failure raises 503 ──────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_dna_profile_upsert_failure_raises_503():
    from app.modules.assessment.dna_profile import refresh_dna_profile
    from fastapi import HTTPException

    supabase = _supabase_mock(badge_labels=[], upsert_raises=True)
    provider_instance = MagicMock()
    provider_instance.complete = AsyncMock(return_value="You are a persistent learner.")

    with patch("app.modules.assessment.dna_profile.OpenAILLMProvider", return_value=provider_instance), \
         patch("app.modules.assessment.prompts.get_settings", return_value=_settings()), \
         pytest.raises(HTTPException) as exc_info:
        await refresh_dna_profile(
            user_id="u1",
            dims=_all_dims(),
            session_count=1,
            supabase=supabase,
            settings=_settings(),
        )

    assert exc_info.value.status_code == 503


# ─ 3.20 refresh_dna_profile — badge_labels read failure continues with empty ──

@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_dna_profile_badge_labels_read_failure_continues_with_empty():
    from app.modules.assessment.dna_profile import refresh_dna_profile
    from app.modules.assessment.prompts import DPDP_DISCLAIMER

    supabase = _supabase_mock(badge_labels=None, badge_read_raises=True)
    provider_instance = MagicMock()
    provider_instance.complete = AsyncMock(return_value="You work independently.")

    with patch("app.modules.assessment.dna_profile.OpenAILLMProvider", return_value=provider_instance), \
         patch("app.modules.assessment.prompts.get_settings", return_value=_settings()):
        result = await refresh_dna_profile(
            user_id="u1",
            dims=_all_dims(60.0),
            session_count=2,
            supabase=supabase,
            settings=_settings(),
        )

    # Must still succeed (non-fatal badge read failure)
    assert result is not None
    assert DPDP_DISCLAIMER in result


# ─ 3.21 refresh_dna_profile — badge_labels row not found → uses empty ─────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_dna_profile_badge_labels_row_not_found_uses_empty():
    from app.modules.assessment.dna_profile import refresh_dna_profile
    from app.modules.assessment.prompts import DPDP_DISCLAIMER

    # badge_labels=None means the DB row was not found (data=None in mock)
    supabase = _supabase_mock(badge_labels=None, badge_read_raises=False)
    provider_instance = MagicMock()
    provider_instance.complete = AsyncMock(return_value="You tend to explore topics deeply.")

    with patch("app.modules.assessment.dna_profile.OpenAILLMProvider", return_value=provider_instance), \
         patch("app.modules.assessment.prompts.get_settings", return_value=_settings()):
        result = await refresh_dna_profile(
            user_id="u1",
            dims=_all_dims(50.0),
            session_count=1,
            supabase=supabase,
            settings=_settings(),
        )

    assert result is not None
    assert DPDP_DISCLAIMER in result


# ─ 3.22 AST scan — no openai import in dna_profile.py ────────────────────────

@pytest.mark.unit
def test_no_openai_import_in_dna_profile():
    """AC 14: dna_profile.py must not import the openai PyPI package directly.

    app.providers.llm.openai is our provider abstraction — that path is allowed.
    Direct 'import openai' or 'from openai import ...' would bypass the abstraction.
    """
    src_path = pathlib.Path("app/modules/assessment/dna_profile.py")
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = (alias.name or "").split(".")[0]
                assert top != "openai", \
                    f"Direct openai PyPI import found in dna_profile.py: {alias.name}"
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".")[0]
            assert top != "openai", \
                f"Direct openai PyPI ImportFrom found in dna_profile.py: from {module}"


# ─ 3.23 AST scan — no hardcoded model string in dna_profile.py ───────────────

@pytest.mark.unit
def test_no_hardcoded_model_string_in_dna_profile():
    src_path = pathlib.Path("app/modules/assessment/dna_profile.py")
    src = src_path.read_text(encoding="utf-8")
    assert "gpt-4o-mini" not in src, "Hardcoded 'gpt-4o-mini' found in dna_profile.py"
    assert '"gpt-4o"' not in src, "Hardcoded 'gpt-4o' found in dna_profile.py"
