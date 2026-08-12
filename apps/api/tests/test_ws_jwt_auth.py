"""Tests for Story S3-43 — WebSocket JWT auth gate (HS256 pin, D80).

All tests are @pytest.mark.unit — no real Redis/Supabase/network.

ACs covered:
  AC1  — no ?token → close(4001) before accept()
  AC2  — malformed token (not JWT, empty, Bearer-prefixed) → close(4001)
  AC3  — expired JWT → close(4001)
  AC4  — JWT signed with wrong secret → close(4001)
  AC5  — missing sub or iat claim → close(4001)
  AC6  — RS256/ES256 alg header → close(4001); JWKS never consulted
  AC7  — algorithms=["HS256"] is a hard-coded literal in websocket.py
  AC8  — valid JWT but session not found OR user_id != sub → close(4003)
  AC9  — user A JWT on user B's session → close(4003)
  AC10 — ownership query carries # BOUNDED: PK lookup comment
  AC11 — valid HS256 JWT + matching owner → accept() called, bootstrap runs
  AC12 — malformed UUID → close(4003) before any token decode or DB read
  AC13 — no JWKS client instantiated during WebSocket auth
  AC14 — JWT without aud=authenticated → close(4001)
  AC15 — rejection WARNING logs session_id[:8] only; no JWT string or sub logged
"""

from __future__ import annotations

import base64
import inspect
import json
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

# Matches conftest.py SUPABASE_JWT_SECRET stub so no settings mock needed
_SECRET = "test-jwt-secret-that-is-long-enough-32-bytes"
_UID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_OTHER_UID = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
_SID = "11111111-2222-3333-4444-555555555555"  # valid UUID


# ── Token helpers ─────────────────────────────────────────────────────────────


def _tok(secret: str = _SECRET, **overrides: object) -> str:
    """Encode a valid HS256 JWT; override any claim via kwargs."""
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": _UID,
        "aud": "authenticated",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return pyjwt.encode(claims, secret, algorithm="HS256")


def _forge_alg(alg: str) -> str:
    """Craft a fake JWT with the given alg header; signature is intentionally invalid.

    Used for AC6: the endpoint must reject RS256/ES256 alg tokens with close(4001)
    WITHOUT attempting JWKS verification, regardless of signature validity.
    """
    header = (
        base64.urlsafe_b64encode(json.dumps({"typ": "JWT", "alg": alg}).encode())
        .rstrip(b"=")
        .decode()
    )
    payload_data = {
        "sub": _UID,
        "aud": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    payload = (
        base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
    )
    sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"


# ── WebSocket mock factory ────────────────────────────────────────────────────


def _ws(token: str | None) -> AsyncMock:
    """Return a mock WebSocket whose ?token query param returns *token*."""
    ws = AsyncMock()
    ws.query_params = MagicMock()
    ws.query_params.get = MagicMock(
        side_effect=lambda k, d=None: token if k == "token" else d
    )
    return ws


# ── Supabase ownership mock ───────────────────────────────────────────────────


def _mock_supabase(owner_uid: str | None) -> MagicMock:
    """Return a mock Supabase client whose sessions table returns *owner_uid*.

    When *owner_uid* is None, data=None (session not found).
    """
    sb = MagicMock()
    table_chain = MagicMock()
    sb.table.return_value = table_chain
    table_chain.select.return_value = table_chain
    table_chain.eq.return_value = table_chain
    table_chain.maybe_single.return_value = table_chain
    if owner_uid is None:
        table_chain.execute.return_value = MagicMock(data=None)
    else:
        table_chain.execute.return_value = MagicMock(data={"user_id": owner_uid})
    return sb


# ── Endpoint call helper ──────────────────────────────────────────────────────


async def _call(
    ws: AsyncMock,
    session_id: str = _SID,
    owner: str | None = _UID,
) -> None:
    """Invoke websocket_endpoint with Supabase ownership + manager.connect mocked."""
    from app.core.websocket import websocket_endpoint

    with patch("app.core.db.get_supabase", return_value=_mock_supabase(owner)):
        with patch("app.core.websocket.manager.connect", new=AsyncMock()):
            await websocket_endpoint(ws, session_id)


# ─────────────────────────────────────────────────────────────────────────────
# AC1 — No ?token query param → close(4001) before accept()
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_no_token_param_closes_4001() -> None:
    """AC1: connection with no ?token is closed 4001 before accept()."""
    ws = _ws(token=None)
    await _call(ws)

    ws.close.assert_called_once()
    call_kwargs = ws.close.call_args
    assert call_kwargs.kwargs.get("code") == 4001 or (
        call_kwargs.args and call_kwargs.args[0] == 4001
    ), f"Expected close(code=4001), got {call_kwargs}"
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — Malformed/non-JWT/Bearer-prefixed token → close(4001)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_empty_token_param_closes_4001() -> None:
    """AC2a: empty ?token string is rejected 4001."""
    ws = _ws(token="")
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


@pytest.mark.unit
async def test_not_a_jwt_string_closes_4001() -> None:
    """AC2b: a token value that is not a JWT format is rejected 4001."""
    ws = _ws(token="not-a-jwt-at-all")
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


@pytest.mark.unit
async def test_bearer_prefix_token_closes_4001() -> None:
    """AC2c: token value with 'Bearer ' prefix is not a raw JWT and is rejected 4001."""
    raw = _tok()
    ws = _ws(token=f"Bearer {raw}")
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — Expired token → close(4001)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_expired_token_closes_4001() -> None:
    """AC3: valid signature but exp in the past → close(4001)."""
    expired = _tok(exp=int(time.time()) - 3600)  # 1h in the past
    ws = _ws(token=expired)
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — Token signed with wrong secret → close(4001)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_wrong_secret_closes_4001() -> None:
    """AC4: JWT signed with a different secret is rejected 4001."""
    wrong = _tok(secret="wrong-secret-that-is-definitely-not-the-right-one")
    ws = _ws(token=wrong)
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC5 — Missing required claim → close(4001)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_missing_sub_claim_closes_4001() -> None:
    """AC5a: JWT without 'sub' claim is rejected 4001."""
    # Build claims without sub
    now = int(time.time())
    claims = {"aud": "authenticated", "iat": now, "exp": now + 3600}
    token = pyjwt.encode(claims, _SECRET, algorithm="HS256")
    ws = _ws(token=token)
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


@pytest.mark.unit
async def test_missing_iat_claim_closes_4001() -> None:
    """AC5b: JWT without 'iat' claim is rejected 4001."""
    now = int(time.time())
    claims = {"sub": _UID, "aud": "authenticated", "exp": now + 3600}
    token = pyjwt.encode(claims, _SECRET, algorithm="HS256")
    ws = _ws(token=token)
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC6 — RS256/ES256 alg header → close(4001); JWKS never consulted
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_rs256_alg_header_closes_4001_no_jwks_attempt() -> None:
    """AC6a: token with RS256 alg header → close(4001); no JWKS client created."""
    rs256_token = _forge_alg("RS256")
    ws = _ws(token=rs256_token)

    with patch("app.core.db.get_supabase", return_value=_mock_supabase(_UID)):
        with patch("app.core.websocket.manager.connect", new=AsyncMock()):
            # Ensure no PyJWKClient is constructed
            with patch("app.core.websocket.jwt.PyJWKClient") as mock_jwks_cls:
                await (
                    __import__("app.core.websocket", fromlist=["websocket_endpoint"])
                    .websocket_endpoint(ws, _SID)
                )

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    mock_jwks_cls.assert_not_called()
    ws.accept.assert_not_called()


@pytest.mark.unit
async def test_es256_alg_header_closes_4001_no_jwks_attempt() -> None:
    """AC6b: token with ES256 alg header → close(4001); no JWKS client created."""
    es256_token = _forge_alg("ES256")
    ws = _ws(token=es256_token)

    with patch("app.core.db.get_supabase", return_value=_mock_supabase(_UID)):
        with patch("app.core.websocket.manager.connect", new=AsyncMock()):
            with patch("app.core.websocket.jwt.PyJWKClient") as mock_jwks_cls:
                await (
                    __import__("app.core.websocket", fromlist=["websocket_endpoint"])
                    .websocket_endpoint(ws, _SID)
                )

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    mock_jwks_cls.assert_not_called()
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC7 — algorithms=["HS256"] is a hard-coded literal in websocket.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_hs256_literal_in_websocket_source() -> None:
    """AC7: websocket.py must contain algorithms=["HS256"] as a literal string.

    Source-inspection guard — ensures the algorithm pin cannot drift to a variable
    or be sourced from the token header (CLAUDE.md binding rule 7 pattern).
    """
    import app.core.websocket as ws_mod

    source = inspect.getsource(ws_mod)
    assert 'algorithms=["HS256"]' in source, (
        'websocket.py must contain algorithms=["HS256"] as a hard-coded literal '
        "(D80 — never read from token header or env var)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC8 — Valid JWT but session not found OR user_id != sub → close(4003)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_session_not_found_closes_4003() -> None:
    """AC8a: valid JWT but no sessions row for session_id → close(4003)."""
    ws = _ws(token=_tok())
    await _call(ws, owner=None)  # None = session not found

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4003
    ws.accept.assert_not_called()


@pytest.mark.unit
async def test_user_id_mismatch_closes_4003() -> None:
    """AC8b: valid JWT but sessions.user_id != jwt sub → close(4003)."""
    ws = _ws(token=_tok())  # token sub=_UID
    await _call(ws, owner=_OTHER_UID)  # session owned by different user

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4003
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC9 — User A JWT on user B's session → close(4003)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_ownership_mismatch_closes_4003() -> None:
    """AC9: user A's valid JWT cannot connect to user B's session → close(4003)."""
    user_a_token = _tok(sub=_UID)
    ws = _ws(token=user_a_token)
    # Session is owned by user B
    await _call(ws, owner=_OTHER_UID)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4003
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC10 — Ownership query carries # BOUNDED: PK lookup comment
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ownership_query_has_bounded_pk_comment() -> None:
    """AC10: websocket.py must contain '# BOUNDED: PK lookup' in the ownership query.

    Source-inspection guard per test_unbounded_queries.py convention.
    The primary key on sessions.session_id guarantees ≤1 row — no .limit() needed.
    """
    import app.core.websocket as ws_mod

    source = inspect.getsource(ws_mod)
    assert "# BOUNDED: PK lookup" in source, (
        "websocket.py ownership query must carry '# BOUNDED: PK lookup' comment "
        "to satisfy test_unbounded_queries.py convention"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC11 — Valid HS256 JWT + matching owner → accept() called, bootstrap runs
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_valid_token_matching_owner_connects() -> None:
    """AC11: valid HS256 JWT + sessions.user_id == sub → manager.connect() called."""
    ws = _ws(token=_tok())

    from app.core.websocket import websocket_endpoint

    mock_connect = AsyncMock()
    with patch("app.core.db.get_supabase", return_value=_mock_supabase(_UID)):
        with patch("app.core.websocket.manager.connect", mock_connect):
            await websocket_endpoint(ws, _SID)

    mock_connect.assert_called_once_with(ws, _SID)
    ws.close.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC12 — Malformed UUID → close(4003) before token decode or DB read
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_invalid_uuid_closes_4003_no_db_call() -> None:
    """AC12: malformed UUID session_id → close(4003) before token decode or DB read."""
    ws = _ws(token=_tok())
    mock_supabase = _mock_supabase(_UID)

    from app.core.websocket import websocket_endpoint

    with patch("app.core.db.get_supabase", return_value=mock_supabase) as mock_get_sb:
        with patch("app.core.websocket.manager.connect", new=AsyncMock()):
            # jwt.decode must also NOT be called
            with patch("app.core.websocket.jwt.decode") as mock_decode:
                await websocket_endpoint(ws, "not-a-valid-uuid")

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4003

    # DB must not be read and JWT must not be decoded for invalid UUIDs
    mock_get_sb.assert_not_called()
    mock_decode.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC13 — No network call (no JWKS fetch, no HTTP client) during WS auth
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_no_jwks_client_instantiated_during_auth() -> None:
    """AC13: no jwt.PyJWKClient is created during WebSocket JWT verification."""
    ws = _ws(token=_tok())

    from app.core.websocket import websocket_endpoint

    with patch("app.core.db.get_supabase", return_value=_mock_supabase(_UID)):
        with patch("app.core.websocket.manager.connect", new=AsyncMock()):
            with patch("app.core.websocket.jwt.PyJWKClient") as mock_jwks_cls:
                await websocket_endpoint(ws, _SID)

    mock_jwks_cls.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC14 — JWT without aud=authenticated → close(4001)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_missing_aud_claim_closes_4001() -> None:
    """AC14a: JWT without any aud claim → close(4001)."""
    now = int(time.time())
    claims = {"sub": _UID, "iat": now, "exp": now + 3600}  # no aud
    token = pyjwt.encode(claims, _SECRET, algorithm="HS256")
    ws = _ws(token=token)
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


@pytest.mark.unit
async def test_wrong_aud_claim_closes_4001() -> None:
    """AC14b: JWT with aud != 'authenticated' → close(4001)."""
    token = _tok(aud="wrong-audience")
    ws = _ws(token=token)
    await _call(ws)

    ws.close.assert_called_once()
    args = ws.close.call_args
    code = args.kwargs.get("code") or (args.args[0] if args.args else None)
    assert code == 4001
    ws.accept.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AC15 — Rejection logs WARNING with session_id[:8] only; no JWT string or sub
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_rejection_logs_warning_with_truncated_session_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC15a: no-token rejection logs WARNING; log contains first 8 chars of session_id."""
    ws = _ws(token=None)

    with caplog.at_level(logging.WARNING, logger="app.core.websocket"):
        await _call(ws)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "Expected at least one WARNING for rejected connection"

    # session_id[:8] must appear
    sid_prefix = _SID[:8]
    assert any(sid_prefix in r.getMessage() for r in warnings), (
        f"Expected session_id prefix '{sid_prefix}' in warning log, got: "
        f"{[r.getMessage() for r in warnings]}"
    )


@pytest.mark.unit
async def test_rejection_does_not_log_full_jwt_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC15b: rejection log must never contain the full JWT token string."""
    full_token = _tok()
    ws = _ws(token=full_token)

    with caplog.at_level(logging.DEBUG, logger="app.core.websocket"):
        # Use a wrong secret so auth fails
        wrong_token = _tok(secret="totally-wrong-secret-that-does-not-match-xxxxx")
        ws2 = _ws(token=wrong_token)
        await _call(ws2)

    all_log_text = " ".join(r.getMessage() for r in caplog.records)
    assert wrong_token not in all_log_text, (
        "Full JWT token string must never appear in log output (AC15)"
    )


@pytest.mark.unit
async def test_rejection_does_not_log_unverified_sub(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC15c: rejection log for wrong-secret token must not contain unverified sub value."""
    wrong_token = _tok(secret="wrong-secret-for-this-test-xxxxxxxxxxxxx", sub=_UID)
    ws = _ws(token=wrong_token)

    with caplog.at_level(logging.DEBUG, logger="app.core.websocket"):
        await _call(ws)

    all_log_text = " ".join(r.getMessage() for r in caplog.records)
    # The unverified sub (_UID) must not appear in logs when token is rejected
    # (it was never verified, so it's untrusted data)
    assert _UID not in all_log_text, (
        f"Unverified sub '{_UID}' must not appear in rejection log output (AC15)"
    )
