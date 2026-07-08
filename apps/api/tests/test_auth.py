"""Integration tests for local JWT verification (Dev 4 — Sprint 1 jwt_all_routes).

Exercises the REAL ``get_current_user`` dependency from ``app.dependencies``. Two mounting styles
are used so the contract is both isolated and demonstrated end-to-end:

1. A synthetic ``GET /protected`` route — isolates the verification logic itself.
2. The real ``app.modules.tutor.router`` mounted under ``/api/tutor`` — proves at least one real
   module router actually enforces ``CurrentUser`` (no-token requests are rejected before the
   handler runs). The verification logic is shared verbatim across all eight ``CurrentUser``-protected
   HTTP routers (analytics, tutor, admin, content, auth, media, assessment), so this proves the
   contract for every such route.

Scope note: the WebSocket endpoint (``core/websocket.py`` ``/ws/{session_id}``) is intentionally
NOT covered here — it does not use ``CurrentUser`` and its auth is a separate, not-yet-implemented
concern. This suite covers HTTP route JWT enforcement only.

All tests are ``@pytest.mark.unit`` — no network, no Supabase. Tokens are minted in-test with PyJWT
using a known secret injected via the ``get_settings`` dependency override. ``get_current_user``
itself is NEVER overridden — it is the code under test.

Time note: PyJWT validates ``exp``/``iat`` against real wall-clock time. The valid token uses a
fixed FUTURE epoch (year 2100); the expired token uses fixed PAST epochs (2023). Both are provably
correct regardless of the day the suite runs.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from unittest.mock import MagicMock

from app.config import get_settings
from app.dependencies import CurrentUser

# ── Constants ──────────────────────────────────────────────────────────────────

_SECRET = "test-jwt-secret-padded-to-32-bytes!!"  # PyJWT ≥2.9 enforces 32-byte minimum for HS256
_PAST_EPOCH = 1_700_000_000        # 2023-11-14 — provably in the past
_FUTURE_EPOCH = 4_102_444_800      # 2100-01-01 — provably in the future
_DROP = object()                   # sentinel: omit a claim from the minted token


# ── App under test ───────────────────────────────────────────────────────────


def _fake_settings() -> MagicMock:
    settings = MagicMock()
    settings.supabase_jwt_secret = _SECRET
    return settings


_app = FastAPI()


@_app.get("/protected")
async def _protected(current_user: CurrentUser) -> dict:
    return {"sub": current_user["sub"]}


# Override ONLY get_settings — inject the known secret. get_current_user stays real.
_app.dependency_overrides[get_settings] = _fake_settings
_client = TestClient(_app, raise_server_exceptions=False)


# Second app: mount the REAL tutor router to prove a real module route enforces auth.
from app.modules.tutor.router import router as _tutor_router  # noqa: E402

_real_app = FastAPI()
_real_app.include_router(_tutor_router, prefix="/api/tutor")
_real_app.dependency_overrides[get_settings] = _fake_settings
_real_client = TestClient(_real_app, raise_server_exceptions=False)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _token(secret: str = _SECRET, **overrides) -> str:
    """Mint an HS256 JWT with valid default claims; per-test overrides merge in.

    Pass a claim set to the ``_DROP`` sentinel to omit it entirely (tests the
    ``options={"require": [...]}`` enforcement path).
    """
    claims = {"sub": "user-001", "iat": _PAST_EPOCH, "exp": _FUTURE_EPOCH}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not _DROP}
    return jwt.encode(claims, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_auth_header_rejected() -> None:
    """AC 1: no Authorization header → HTTPBearer auto_error fires (401/403)."""
    resp = _client.get("/protected")
    assert resp.status_code in (401, 403)


@pytest.mark.unit
def test_valid_token_returns_200() -> None:
    """AC 2: valid signature + sub/iat/future-exp → 200, sub echoed to handler."""
    resp = _client.get("/protected", headers=_auth(_token()))
    assert resp.status_code == 200
    assert resp.json() == {"sub": "user-001"}


@pytest.mark.unit
def test_expired_token_returns_401() -> None:
    """AC 3: an otherwise-valid token whose exp is in the past → 401.

    iat < exp, both in 2023, so the ONLY reason for rejection is expiry
    (ExpiredSignatureError), not a malformed/immature token.
    """
    resp = _client.get(
        "/protected",
        headers=_auth(_token(iat=_PAST_EPOCH, exp=_PAST_EPOCH + 3600)),
    )
    assert resp.status_code == 401


@pytest.mark.unit
def test_wrong_secret_returns_401() -> None:
    """AC 4: token signed with a different secret → InvalidSignatureError → 401."""
    resp = _client.get("/protected", headers=_auth(_token(secret="a-completely-different-secret!!!")))
    assert resp.status_code == 401


@pytest.mark.unit
def test_malformed_token_returns_401() -> None:
    """AC 5: non-JWT bearer string → DecodeError (InvalidTokenError) → 401."""
    resp = _client.get("/protected", headers=_auth("not-a-jwt"))
    assert resp.status_code == 401


@pytest.mark.unit
def test_alg_none_token_rejected() -> None:
    """Security: an unsigned ``alg: none`` token must be rejected (algorithms=["HS256"]).

    This is the classic JWT bypass — the dependency restricts accepted algorithms, so an
    attacker-supplied unsigned token must never authenticate.
    """
    unsigned = jwt.encode(
        {"sub": "user-001", "iat": _PAST_EPOCH, "exp": _FUTURE_EPOCH},
        key="",
        algorithm="none",
    )
    resp = _client.get("/protected", headers=_auth(unsigned))
    assert resp.status_code == 401


@pytest.mark.unit
def test_missing_sub_claim_returns_401() -> None:
    """AC 6: valid signature but no sub claim → MissingRequiredClaimError → 401."""
    resp = _client.get("/protected", headers=_auth(_token(sub=_DROP)))
    assert resp.status_code == 401


@pytest.mark.unit
def test_empty_sub_claim_returns_401() -> None:
    """AC 6: a present-but-empty sub passes signature + require, but the explicit
    ``if not payload.get("sub")`` guard in get_current_user must still reject it → 401.

    Distinct code path from a dropped claim (which trips require=[...] instead).
    """
    resp = _client.get("/protected", headers=_auth(_token(sub="")))
    assert resp.status_code == 401


@pytest.mark.unit
def test_missing_iat_claim_returns_401() -> None:
    """AC 6/7: valid signature but no iat claim → require=["...","iat"] enforced → 401."""
    resp = _client.get("/protected", headers=_auth(_token(iat=_DROP)))
    assert resp.status_code == 401


@pytest.mark.unit
def test_real_router_requires_auth() -> None:
    """A real module router (tutor) mounted normally rejects an unauthenticated request.

    Proves the contract is actually wired on a production router, not just the synthetic
    /protected proxy. Without a token the request is rejected (401/403) before the handler
    (which would otherwise return 501) ever runs.
    """
    resp = _real_client.get("/api/tutor/session/sess-001/state")
    assert resp.status_code in (401, 403)
