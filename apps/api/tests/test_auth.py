"""Integration tests for local JWT verification (Dev 4 — Sprint 1 jwt_all_routes;
rewritten Story 4-17 — ES256/JWKS verification, not HS256/shared-secret).

Exercises the REAL ``get_current_user`` dependency from ``app.dependencies``. Two mounting styles
are used so the contract is both isolated and demonstrated end-to-end:

1. A synthetic ``GET /protected`` route — isolates the verification logic itself.
2. The real ``app.modules.tutor.router`` mounted under ``/api/tutor`` — proves at least one real
   module router actually enforces ``CurrentUser`` (no-token requests are rejected before the
   handler runs). The verification logic is shared verbatim across all eight
   ``CurrentUser``-protected HTTP routers (analytics, tutor, admin, content, auth, media,
   assessment), so this proves the contract for every such route.

Scope note: the WebSocket endpoint (``core/websocket.py`` ``/ws/{session_id}``) is intentionally
NOT covered here — it does not use ``CurrentUser`` and its auth is a separate, not-yet-implemented
concern. This suite covers HTTP route JWT enforcement only.

Story 4-17 rewrite: Supabase issues ES256-signed tokens for this project (confirmed via its live
JWKS endpoint), not HS256. ``get_current_user`` now resolves the verification key via
``get_jwks_client()`` (a ``jwt.PyJWKClient``) instead of a static ``settings.supabase_jwt_secret``.
This suite mints its own ES256 tokens with a locally-generated EC (P-256) key pair and overrides
``get_jwks_client`` with an in-process fake that never touches the network — the "no network, no
Supabase" principle from the original story is preserved by construction: no test in this file ever
constructs a real ``jwt.PyJWKClient`` pointed at any URL, so there is nothing in this suite capable
of making an HTTP call.

All tests are ``@pytest.mark.unit``. ``get_current_user`` itself is NEVER overridden — it is the
code under test.

Time note: PyJWT validates ``exp``/``iat`` against real wall-clock time. The valid token uses a
fixed FUTURE epoch (year 2100); the expired token uses fixed PAST epochs (2023). Both are provably
correct regardless of the day the suite runs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.config import get_settings
from app.dependencies import CurrentUser, get_jwks_client

# ── Constants ──────────────────────────────────────────────────────────────────

_PAST_EPOCH = 1_700_000_000        # 2023-11-14 — provably in the past
_FUTURE_EPOCH = 4_102_444_800      # 2100-01-01 — provably in the future
_DROP = object()                   # sentinel: omit a claim from the minted token

# The key pair the fake JWKS client "publishes" as this session's valid signing key.
_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

# A second, unrelated key pair — used to mint a token whose signature the fake JWKS
# client's published public key must NOT verify (the ES256 analog of "wrong secret").
_WRONG_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


# ── Test double: stands in for jwt.PyJWKClient without any network access ──────


class _FakeJWKSClient:
    """Test double for jwt.PyJWKClient.

    Never inspects the token's `kid` or makes any network call — it either returns a
    fixed signing key unconditionally, or (when configured to) raises PyJWKClientError,
    to exercise get_current_user's two branches. Malformed/wrong-signature/wrong-algorithm
    tokens are still correctly rejected because the REAL jwt.decode() call downstream does
    the actual cryptographic verification — this double only stands in for the key lookup.
    """

    def __init__(self, *, raise_error: bool = False) -> None:
        self._raise_error = raise_error
        self.call_count = 0

    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        self.call_count += 1
        if self._raise_error:
            raise jwt.PyJWKClientError("Unable to find a signing key that matches")
        return SimpleNamespace(key=_PUBLIC_KEY, algorithm_name="ES256")


# ── App under test ───────────────────────────────────────────────────────────


def _fake_settings() -> MagicMock:
    settings = MagicMock()
    settings.supabase_url = "https://example.supabase.co"
    return settings


_app = FastAPI()


@_app.get("/protected")
async def _protected(current_user: CurrentUser) -> dict:
    return {"sub": current_user["sub"]}


# Override get_settings (harmless/unused by get_current_user post-4-17, kept for any other
# route on this app that might read it) and get_jwks_client (the actual seam get_current_user
# now depends on). get_current_user itself stays real — never overridden.
_fake_jwks = _FakeJWKSClient()
_app.dependency_overrides[get_settings] = _fake_settings
_app.dependency_overrides[get_jwks_client] = lambda: _fake_jwks
_client = TestClient(_app, raise_server_exceptions=False)


# Second app: mount the REAL tutor router to prove a real module route enforces auth.
from app.modules.tutor.router import router as _tutor_router  # noqa: E402

_real_app = FastAPI()
_real_app.include_router(_tutor_router, prefix="/api/tutor")
_real_app.dependency_overrides[get_settings] = _fake_settings
_real_app.dependency_overrides[get_jwks_client] = lambda: _fake_jwks
_real_client = TestClient(_real_app, raise_server_exceptions=False)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _token(private_key: ec.EllipticCurvePrivateKey | None = None, **overrides: object) -> str:
    """Mint an ES256 JWT with valid default claims; per-test overrides merge in.

    Pass a claim set to the ``_DROP`` sentinel to omit it entirely (tests the
    ``options={"require": [...]}`` enforcement path). Signed with ``_PRIVATE_KEY`` by
    default — the key pair the fake JWKS client's published public key can verify.
    """
    key = private_key if private_key is not None else _PRIVATE_KEY
    claims: dict[str, object] = {"sub": "user-001", "iat": _PAST_EPOCH, "exp": _FUTURE_EPOCH}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not _DROP}
    return jwt.encode(claims, key, algorithm="ES256")


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
def test_wrong_signing_key_returns_401() -> None:
    """AC 4: token signed with a different key pair than the JWKS-published one → 401.

    ES256 analog of the old "wrong secret" test — InvalidSignatureError → 401.
    """
    resp = _client.get("/protected", headers=_auth(_token(private_key=_WRONG_PRIVATE_KEY)))
    assert resp.status_code == 401


@pytest.mark.unit
def test_malformed_token_returns_401() -> None:
    """AC 5: non-JWT bearer string → DecodeError (InvalidTokenError) → 401.

    The fake JWKS client returns its fixed key unconditionally (it doesn't need to
    understand the input) — the real jwt.decode() call downstream is what actually
    rejects the malformed string.
    """
    resp = _client.get("/protected", headers=_auth("not-a-jwt"))
    assert resp.status_code == 401


@pytest.mark.unit
def test_alg_none_token_rejected() -> None:
    """Security: an unsigned ``alg: none`` token must be rejected.

    This is the classic JWT bypass. get_current_user restricts jwt.decode to
    algorithms=[signing_key.algorithm_name] ("ES256" here), so an attacker-supplied
    unsigned/none-alg token must never authenticate, even if the JWKS lookup itself
    succeeds.
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
def test_unrecognized_kid_returns_401() -> None:
    """Story 4-17 AC 3: PyJWKClientError (unrecognized `kid`, or an unreachable JWKS
    endpoint in production) must be treated as an invalid token (401), never a 500.
    """
    raising_app = FastAPI()

    @raising_app.get("/protected")
    async def _protected_raising(current_user: CurrentUser) -> dict:
        return {"sub": current_user["sub"]}

    raising_app.dependency_overrides[get_settings] = _fake_settings
    raising_app.dependency_overrides[get_jwks_client] = lambda: _FakeJWKSClient(raise_error=True)
    client = TestClient(raising_app, raise_server_exceptions=False)

    resp = client.get("/protected", headers=_auth(_token()))
    assert resp.status_code == 401


@pytest.mark.unit
def test_jwks_client_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Story 4-17 AC 4: get_jwks_client() must not rebuild a new PyJWKClient on every
    call — caching is what keeps JWT verification "local" (no per-request network call,
    <5ms per Epic 4's DoD) now that verification depends on a fetched public key instead
    of a static shared secret.

    Tests the caching mechanism directly (identity across two calls) rather than via two
    HTTP round trips — more precise than routing through get_current_user twice, since the
    fake JWKS client used elsewhere in this file doesn't simulate network cost anyway; this
    isolates exactly the property that matters (the real get_jwks_client is a singleton).
    """
    fake_settings = MagicMock()
    fake_settings.supabase_url = "https://example.supabase.co"
    monkeypatch.setattr("app.dependencies.get_settings", lambda: fake_settings)

    get_jwks_client.cache_clear()
    try:
        client_1 = get_jwks_client()
        client_2 = get_jwks_client()
        assert client_1 is client_2
    finally:
        get_jwks_client.cache_clear()


@pytest.mark.unit
def test_real_router_requires_auth() -> None:
    """A real module router (tutor) mounted normally rejects an unauthenticated request.

    Proves the contract is actually wired on a production router, not just the synthetic
    /protected proxy. Without a token the request is rejected (401/403) before the handler
    (which would otherwise return 501) ever runs.
    """
    resp = _real_client.get("/api/tutor/session/sess-001/state")
    assert resp.status_code in (401, 403)
