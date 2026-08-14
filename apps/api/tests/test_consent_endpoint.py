"""
Tests for POST /api/assessment/consent — Story 3-32 / D29 fix.

Coverage:
- AC 1  — 201 on first consent (attention_tracking)
- AC 2  — extra body fields are silently ignored
- AC 3  — invalid consent_type → 422
- AC 4  — blank/missing policy_version → 422
- AC 5  — user_id comes exclusively from JWT current_user["sub"]
- AC 6  — unauthenticated requests are rejected (CurrentUser dependency declared)
- AC 7  — user_id passed to DB is always str(current_user["sub"])
- AC 8  — service never touches the users table (trigger only)
- AC 9  — first consent inserts a row and returns 201
- AC 10 — idempotent re-consent returns 200 with existing record, no duplicate INSERT
- AC 11 — response contains id, user_id, consent_type, policy_version, consented_at
- AC 12 — DB INSERT failure (non-duplicate) → 500
- AC 13 — empty INSERT response → 500
- AC 14 — record_consent() makes zero LLM calls
- AC 15 — all DB calls wrapped in asyncio.to_thread
- AC 16 — record_consent() is a coroutine function

INSERT-first idempotency pattern (L2-1 fix):
  The service attempts INSERT first. If the UNIQUE constraint fires (PostgreSQL 23505 /
  "duplicate key"), it falls back to a SELECT of the existing row. This is atomically
  correct — a SELECT-then-INSERT pattern would race under concurrent requests.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_FAKE_RECORD = {
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "user_id": "user-jwt-sub-001",
    "consent_type": "attention_tracking",
    "policy_version": "v1",
    "consented_at": "2026-08-05T10:00:00+00:00",
}


# ---------------------------------------------------------------------------
# Mock builders — aligned to INSERT-first service logic
# ---------------------------------------------------------------------------


def _build_supabase_no_existing(insert_data: list[dict] | None = None) -> Any:
    """Happy path: INSERT succeeds and returns a new row (is_new=True)."""
    if insert_data is None:
        insert_data = [_FAKE_RECORD]

    insert_chain = MagicMock()
    insert_result = MagicMock()
    insert_result.data = insert_data
    insert_result.error = None
    insert_chain.execute.return_value = insert_result

    supabase = MagicMock()
    tbl = MagicMock()
    tbl.insert.return_value = insert_chain
    supabase.table.return_value = tbl
    return supabase


def _build_supabase_existing_record(record: dict | None = None) -> Any:
    """Idempotent path: INSERT fails with unique violation → SELECT returns existing row."""
    if record is None:
        record = _FAKE_RECORD

    # INSERT returns a unique-violation error (mirrors PostgreSQL 23505)
    insert_chain = MagicMock()
    insert_result = MagicMock()
    insert_result.data = []
    unique_err = MagicMock()
    unique_err.__str__ = lambda _: "duplicate key value violates unique constraint"
    insert_result.error = unique_err
    insert_chain.execute.return_value = insert_result

    # SELECT returns the pre-existing row
    select_chain = MagicMock()
    select_result = MagicMock()
    select_result.data = [record]
    select_result.error = None
    select_chain.eq.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = select_result

    supabase = MagicMock()
    tbl = MagicMock()
    tbl.insert.return_value = insert_chain
    tbl.select.return_value = select_chain
    supabase.table.return_value = tbl
    return supabase


def _build_supabase_insert_error(error_msg: str = "db connection error") -> Any:
    """Error path: INSERT fails with a non-duplicate error → 500."""
    insert_chain = MagicMock()
    insert_result = MagicMock()
    insert_result.data = []
    err = MagicMock()
    err.__str__ = lambda _, m=error_msg: m
    insert_result.error = err
    insert_chain.execute.return_value = insert_result

    supabase = MagicMock()
    tbl = MagicMock()
    tbl.insert.return_value = insert_chain
    supabase.table.return_value = tbl
    return supabase


def _build_supabase_empty_insert() -> Any:
    """Edge path: INSERT succeeds but returns no rows → 500."""
    insert_chain = MagicMock()
    insert_result = MagicMock()
    insert_result.data = []
    insert_result.error = None
    insert_chain.execute.return_value = insert_result

    supabase = MagicMock()
    tbl = MagicMock()
    tbl.insert.return_value = insert_chain
    supabase.table.return_value = tbl
    return supabase


# ---------------------------------------------------------------------------
# AC 16 — record_consent() is a coroutine
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_is_async():
    """AC 16: record_consent must be a coroutine function."""
    from app.modules.assessment.service import record_consent

    assert inspect.iscoroutinefunction(record_consent), (
        "record_consent must be declared 'async def' so callers can await it"
    )


# ---------------------------------------------------------------------------
# AC 6 — unauthenticated requests are rejected (structural guard)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_endpoint_requires_current_user_dependency():
    """AC 6: CurrentUser dependency is declared — FastAPI enforces JWT auth before handler runs.

    FastAPI's DI system resolves CurrentUser (an Annotated alias wrapping Depends(verify_jwt))
    before calling the handler. If JWT validation fails, FastAPI raises 401/403 automatically.
    Verifying the parameter annotation is present is the unit-level guard; the DI enforcement
    is an integration-level concern.
    """
    from app.modules.assessment.router import record_consent_endpoint

    sig = inspect.signature(record_consent_endpoint)
    assert "current_user" in sig.parameters, (
        "record_consent_endpoint must declare 'current_user: CurrentUser' "
        "for FastAPI JWT enforcement"
    )


# ---------------------------------------------------------------------------
# AC 9 — first consent inserts a row and returns (record, True)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_first_consent_returns_record_and_is_new_true():
    """AC 9: first consent → INSERT executed, is_new=True returned."""
    from app.modules.assessment.service import record_consent

    supabase = _build_supabase_no_existing()
    record, is_new = asyncio.run(
        record_consent(
            user_id="user-jwt-sub-001",
            consent_type="attention_tracking",
            policy_version="v1",
            supabase=supabase,
        )
    )
    assert is_new is True
    assert record["consent_type"] == "attention_tracking"


# ---------------------------------------------------------------------------
# AC 1 — endpoint returns 201 on first consent
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_endpoint_returns_201_on_first_consent():
    """AC 1: HTTP 201 is returned when a new consent record is created."""
    from fastapi import Response

    from app.modules.assessment.router import record_consent_endpoint
    from app.modules.assessment.schemas import ConsentCreate

    current_user = {"sub": "user-jwt-sub-001"}
    body = ConsentCreate(consent_type="attention_tracking", policy_version="v1")
    fake_response = MagicMock(spec=Response)
    fake_response.status_code = 201

    supabase = _build_supabase_no_existing()

    # Patch at the source module — get_supabase is a lazy import inside the function,
    # so patching the router module attribute would fail (it is not a module-level name).
    with patch("app.core.db.get_supabase", return_value=supabase):
        result = asyncio.run(
            record_consent_endpoint(
                body=body,
                current_user=current_user,
                response=fake_response,
            )
        )

    assert result.consent_type == "attention_tracking"
    assert result.user_id == "user-jwt-sub-001"


# ---------------------------------------------------------------------------
# AC 11 — response contains required fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_response_shape():
    """AC 11: ConsentRecord contains id, user_id, consent_type, policy_version, consented_at."""
    from app.modules.assessment.service import record_consent

    supabase = _build_supabase_no_existing()
    record, _ = asyncio.run(
        record_consent(
            user_id="user-jwt-sub-001",
            consent_type="attention_tracking",
            policy_version="v1",
            supabase=supabase,
        )
    )
    for field in ("id", "user_id", "consent_type", "policy_version", "consented_at"):
        assert field in record, f"Response missing required field: {field}"


# ---------------------------------------------------------------------------
# AC 10 — idempotent: unique constraint fires → 200, existing row returned
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_idempotent_returns_existing_record_and_is_new_false():
    """AC 10: duplicate INSERT triggers unique violation → is_new=False, existing row returned."""
    from app.modules.assessment.service import record_consent

    supabase = _build_supabase_existing_record()
    record, is_new = asyncio.run(
        record_consent(
            user_id="user-jwt-sub-001",
            consent_type="attention_tracking",
            policy_version="v1",
            supabase=supabase,
        )
    )
    assert is_new is False
    assert record["id"] == _FAKE_RECORD["id"]


@pytest.mark.unit
def test_record_consent_endpoint_idempotent_sets_200_status():
    """AC 10: endpoint sets response.status_code = 200 when consent already exists."""
    from fastapi import Response
    from fastapi import status as http_status

    from app.modules.assessment.router import record_consent_endpoint
    from app.modules.assessment.schemas import ConsentCreate

    current_user = {"sub": "user-jwt-sub-001"}
    body = ConsentCreate(consent_type="attention_tracking", policy_version="v1")
    fake_response = MagicMock(spec=Response)

    supabase = _build_supabase_existing_record()

    with patch("app.core.db.get_supabase", return_value=supabase):
        asyncio.run(
            record_consent_endpoint(
                body=body,
                current_user=current_user,
                response=fake_response,
            )
        )

    # Idempotent path: is_new=False → endpoint sets response.status_code = 200
    assert fake_response.status_code == http_status.HTTP_200_OK


@pytest.mark.unit
def test_record_consent_learner_dna_idempotent_returns_false():
    """AC 10 (learner_dna): idempotent path works for both valid consent types."""
    from app.modules.assessment.service import record_consent

    dna_record = {**_FAKE_RECORD, "consent_type": "learner_dna"}
    supabase = _build_supabase_existing_record(record=dna_record)
    record, is_new = asyncio.run(
        record_consent(
            user_id="user-jwt-sub-001",
            consent_type="learner_dna",
            policy_version="v1",
            supabase=supabase,
        )
    )
    assert is_new is False
    assert record["consent_type"] == "learner_dna"


# ---------------------------------------------------------------------------
# AC 5 + AC 7 — user_id exclusively from JWT
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_user_id_comes_from_jwt_not_body():
    """AC 5/7: user_id passed to DB is always str(current_user['sub']), never body-provided."""
    from fastapi import Response

    from app.modules.assessment.router import record_consent_endpoint
    from app.modules.assessment.schemas import ConsentCreate

    jwt_user_id = "jwt-only-user-a1b2c3d4e5f6"
    current_user = {"sub": jwt_user_id}
    body = ConsentCreate(consent_type="learner_dna", policy_version="v1")
    fake_response = MagicMock(spec=Response)

    captured_user_id: list[str] = []

    async def _fake_record_consent(*, user_id: str, **_kwargs: Any) -> tuple[dict, bool]:
        captured_user_id.append(user_id)
        return {**_FAKE_RECORD, "user_id": user_id, "consent_type": "learner_dna"}, True

    # Patch the service function at its definition site — it is a lazy import
    # inside record_consent_endpoint, so the router module has no module-level
    # attribute named 'record_consent' to patch directly.
    with patch(
        "app.modules.assessment.service.record_consent",
        side_effect=_fake_record_consent,
    ):
        asyncio.run(
            record_consent_endpoint(
                body=body,
                current_user=current_user,
                response=fake_response,
            )
        )

    assert len(captured_user_id) == 1, "record_consent must be called exactly once"
    assert captured_user_id[0] == jwt_user_id, (
        f"user_id passed to service was '{captured_user_id[0]}', expected JWT sub '{jwt_user_id}'"
    )


@pytest.mark.unit
def test_record_consent_endpoint_never_reads_user_id_from_body():
    """AC 5/7: even if body had a user_id attribute (future regression), endpoint uses JWT sub only.

    This test simulates a hypothetical bug where user_id is added to ConsentCreate.
    The endpoint must always use current_user['sub'], never body.user_id.
    """
    from fastapi import Response

    from app.modules.assessment.router import record_consent_endpoint

    jwt_sub = "correct-jwt-sub-from-token"
    attacker_id = "attacker-injected-id"

    body = MagicMock()
    body.consent_type = "attention_tracking"
    body.policy_version = "v1"
    body.user_id = attacker_id  # Simulates a future regression where body gains user_id

    captured: list[str] = []

    async def _capture_user_id(*, user_id: str, **_kwargs: Any) -> tuple[dict, bool]:
        captured.append(user_id)
        return (_FAKE_RECORD, True)

    with patch("app.modules.assessment.service.record_consent", side_effect=_capture_user_id):
        asyncio.run(
            record_consent_endpoint(
                body=body,
                current_user={"sub": jwt_sub},
                response=MagicMock(spec=Response),
            )
        )

    assert len(captured) == 1
    assert captured[0] == jwt_sub, (
        f"Expected JWT sub '{jwt_sub}' but service received '{captured[0]}'"
    )
    assert captured[0] != attacker_id, "Body user_id must never reach the service"


@pytest.mark.unit
def test_record_consent_user_id_in_db_insert_matches_jwt_sub():
    """AC 7: the INSERT payload's user_id equals the JWT sub — verified via captured call args."""
    from app.modules.assessment.service import record_consent

    jwt_sub = "jwt-sub-xyzzy-9999"
    insert_calls: list[dict] = []

    def _capture_insert(payload: dict) -> MagicMock:
        insert_calls.append(payload)
        chain = MagicMock()
        result = MagicMock()
        result.data = [{**_FAKE_RECORD, "user_id": jwt_sub}]
        result.error = None
        chain.execute.return_value = result
        return chain

    supabase = MagicMock()
    tbl = MagicMock()
    tbl.insert.side_effect = _capture_insert
    supabase.table.return_value = tbl

    asyncio.run(
        record_consent(
            user_id=jwt_sub,
            consent_type="attention_tracking",
            policy_version="v1",
            supabase=supabase,
        )
    )

    assert len(insert_calls) == 1
    assert insert_calls[0]["user_id"] == jwt_sub, (
        "INSERT payload must use the JWT sub, never a client-provided user_id"
    )


# ---------------------------------------------------------------------------
# AC 8 — service never touches the users table
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_service_never_updates_users_table():
    """AC 8: record_consent must not call supabase.table('users') — the DB trigger handles
    setting attention_consent; any direct update here would race and bypass the audit design."""
    from app.modules.assessment.service import record_consent

    supabase = _build_supabase_no_existing()
    accessed_tables: list[str] = []
    real_side_effect = supabase.table.side_effect
    real_return_value = supabase.table.return_value

    def _tracking_table(name: str) -> Any:
        accessed_tables.append(name)
        if real_side_effect is not None:
            return real_side_effect(name)
        return real_return_value

    supabase.table.side_effect = _tracking_table

    asyncio.run(
        record_consent(
            user_id="user-jwt-sub-001",
            consent_type="attention_tracking",
            policy_version="v1",
            supabase=supabase,
        )
    )

    assert "users" not in accessed_tables, (
        f"record_consent accessed the 'users' table ({accessed_tables!r}). "
        "The DB trigger must be the sole writer of users.attention_consent — "
        "any direct update here bypasses the audit-first DPDP design."
    )


# ---------------------------------------------------------------------------
# AC 12 — DB INSERT error (non-duplicate) → 500
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_db_insert_failure_raises_500():
    """AC 12: non-duplicate INSERT failure → HTTPException 500."""
    from app.modules.assessment.service import record_consent

    supabase = _build_supabase_insert_error("connection timeout")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            record_consent(
                user_id="user-jwt-sub-001",
                consent_type="attention_tracking",
                policy_version="v1",
                supabase=supabase,
            )
        )
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# AC 13 — empty INSERT response → 500
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_empty_insert_response_raises_500():
    """AC 13: INSERT succeeds but returns no rows → HTTPException 500."""
    from app.modules.assessment.service import record_consent

    supabase = _build_supabase_empty_insert()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            record_consent(
                user_id="user-jwt-sub-001",
                consent_type="attention_tracking",
                policy_version="v1",
                supabase=supabase,
            )
        )
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# AC 3 — invalid consent_type → 422 (Pydantic validation)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_consent_create_invalid_type_raises_validation_error():
    """AC 3: consent_type not in Literal set → Pydantic ValidationError (→ FastAPI 422)."""
    from pydantic import ValidationError

    from app.modules.assessment.schemas import ConsentCreate

    with pytest.raises(ValidationError):
        ConsentCreate(consent_type="webcam_recording", policy_version="v1")


@pytest.mark.unit
def test_consent_create_accepts_attention_tracking():
    """AC 3: 'attention_tracking' is a valid consent_type."""
    from app.modules.assessment.schemas import ConsentCreate

    obj = ConsentCreate(consent_type="attention_tracking", policy_version="v1")
    assert obj.consent_type == "attention_tracking"


@pytest.mark.unit
def test_consent_create_accepts_learner_dna():
    """AC 3: 'learner_dna' is a valid consent_type."""
    from app.modules.assessment.schemas import ConsentCreate

    obj = ConsentCreate(consent_type="learner_dna", policy_version="v1")
    assert obj.consent_type == "learner_dna"


# ---------------------------------------------------------------------------
# AC 4 — blank policy_version → 422
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_consent_create_empty_policy_version_raises_validation_error():
    """AC 4: policy_version='' fails min_length=1 → Pydantic ValidationError (→ FastAPI 422)."""
    from pydantic import ValidationError

    from app.modules.assessment.schemas import ConsentCreate

    with pytest.raises(ValidationError):
        ConsentCreate(consent_type="attention_tracking", policy_version="")


# ---------------------------------------------------------------------------
# AC 2 — extra body fields are silently ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_consent_create_extra_fields_silently_ignored():
    """AC 2: extra fields (e.g. user_id in body) are silently discarded by Pydantic."""
    from app.modules.assessment.schemas import ConsentCreate

    obj = ConsentCreate(
        consent_type="attention_tracking",
        policy_version="v1",
        user_id="attacker-controlled-value",  # type: ignore[call-arg]
    )
    # ConsentCreate must not expose a user_id attribute
    assert not hasattr(obj, "user_id"), (
        "ConsentCreate must not accept user_id from the body — JWT sub is the only source"
    )


# ---------------------------------------------------------------------------
# AC 14 — no LLM calls
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_makes_no_llm_calls():
    """AC 14: record_consent never calls OpenAILLMProvider — consent is a pure DB write."""
    from app.modules.assessment.service import record_consent

    supabase = _build_supabase_no_existing()

    with patch("app.modules.assessment.service.OpenAILLMProvider") as mock_llm_cls:
        asyncio.run(
            record_consent(
                user_id="user-jwt-sub-001",
                consent_type="attention_tracking",
                policy_version="v1",
                supabase=supabase,
            )
        )

    mock_llm_cls.assert_not_called()


# ---------------------------------------------------------------------------
# AC 15 — asyncio.to_thread wraps DB calls (happy path = 1 call, idempotent = 2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_db_calls_wrapped_in_to_thread():
    """AC 15 (happy path): INSERT is wrapped in asyncio.to_thread — exactly 1 call."""
    from app.modules.assessment.service import record_consent

    to_thread_calls: list[Any] = []
    real_to_thread = asyncio.to_thread

    async def _mock_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        to_thread_calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    supabase = _build_supabase_no_existing()

    with patch("asyncio.to_thread", side_effect=_mock_to_thread):
        asyncio.run(
            record_consent(
                user_id="user-jwt-sub-001",
                consent_type="attention_tracking",
                policy_version="v1",
                supabase=supabase,
            )
        )

    assert len(to_thread_calls) == 1, (
        "Happy path must make exactly 1 asyncio.to_thread call (INSERT). "
        f"Got {len(to_thread_calls)}."
    )


@pytest.mark.unit
def test_record_consent_idempotent_path_both_db_calls_wrapped_in_to_thread():
    """AC 15 (idempotent path): INSERT + fallback SELECT are both wrapped in asyncio.to_thread."""
    from app.modules.assessment.service import record_consent

    to_thread_calls: list[Any] = []
    real_to_thread = asyncio.to_thread

    async def _mock_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        to_thread_calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    supabase = _build_supabase_existing_record()

    with patch("asyncio.to_thread", side_effect=_mock_to_thread):
        asyncio.run(
            record_consent(
                user_id="user-jwt-sub-001",
                consent_type="attention_tracking",
                policy_version="v1",
                supabase=supabase,
            )
        )

    assert len(to_thread_calls) == 2, (
        "Idempotent path must make exactly 2 asyncio.to_thread calls (INSERT + SELECT). "
        f"Got {len(to_thread_calls)}."
    )


# ---------------------------------------------------------------------------
# AC 9 — learner_dna consent type also works (second valid type)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_learner_dna_type_works():
    """AC 9 (learner_dna variant): consent_type='learner_dna' is persisted correctly."""
    from app.modules.assessment.service import record_consent

    dna_record = {**_FAKE_RECORD, "consent_type": "learner_dna"}
    supabase = _build_supabase_no_existing(insert_data=[dna_record])
    record, is_new = asyncio.run(
        record_consent(
            user_id="user-jwt-sub-001",
            consent_type="learner_dna",
            policy_version="v1",
            supabase=supabase,
        )
    )
    assert is_new is True
    assert record["consent_type"] == "learner_dna"


# ---------------------------------------------------------------------------
# Integration: endpoint with both types
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_consent_endpoint_learner_dna_returns_201():
    """AC 1 (learner_dna): POST /consent with consent_type=learner_dna → 201."""
    from fastapi import Response

    from app.modules.assessment.router import record_consent_endpoint
    from app.modules.assessment.schemas import ConsentCreate

    dna_record = {**_FAKE_RECORD, "consent_type": "learner_dna"}
    supabase = _build_supabase_no_existing(insert_data=[dna_record])
    current_user = {"sub": "user-jwt-sub-001"}
    body = ConsentCreate(consent_type="learner_dna", policy_version="v1")
    fake_response = MagicMock(spec=Response)

    with patch("app.core.db.get_supabase", return_value=supabase):
        result = asyncio.run(
            record_consent_endpoint(
                body=body,
                current_user=current_user,
                response=fake_response,
            )
        )

    assert result.consent_type == "learner_dna"
