"""D52: the rate-limit bucket key must be the USER, not the IP.

`_get_user_key` decodes the bearer token purely to read `sub`. Before this suite
existed it called `pyjwt.decode(...)` with no `audience=` while every Supabase
token carries `aud: "authenticated"` — PyJWT raises `InvalidAudienceError` in
exactly that case, the bare `except` swallowed it, and the function returned
`get_remote_address(request)` for EVERY authenticated request.

The effect was a shared bucket: one caller exhausting `3/minute` on the generate
endpoint locked out every other user behind the same egress IP, and behind a
proxy or CDN that is all of them. Nothing above DEBUG said so.

Found by the Story 1-14 live gate (AC20 step 7d), which expected a 404 for
another user's book and got a 429 — not by any of the 69 endpoint unit tests,
because the failure is silent and the decorator was present and correct.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import app.dependencies as dependencies_module
from app.config import get_settings
from app.core.rate_limit import _get_user_key

SUB = "8200720f-c76a-404f-91d0-64faa2b534d9"


def _request(token: str | None) -> Any:
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"} if token else {}
    req.client.host = "203.0.113.7"
    return req


def _token(**overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        # `aud` is the whole point: Supabase always sets it, and its presence is
        # what used to break the decode.
        "aud": "authenticated",
        "role": "authenticated",
        "sub": SUB,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return pyjwt.encode(claims, get_settings().supabase_jwt_secret, algorithm="HS256")


@pytest.mark.unit
def test_a_supabase_shaped_token_keys_the_bucket_by_user() -> None:
    """The regression itself. If this returns an IP, every user shares a bucket
    and one caller can deny the endpoint to everyone else."""
    assert _get_user_key(_request(_token())) == f"user:{SUB}"


@pytest.mark.unit
def test_the_aud_claim_is_really_present_and_really_breaks_a_naive_decode() -> None:
    """Premise (binding rule 3): proves the failure mode is what we think it is.

    Without this, the fix above looks like a superstitious option flag. It asserts
    the exact PyJWT behaviour the production code now compensates for.
    """
    token = _token()
    assert pyjwt.decode(token, options={"verify_signature": False})["aud"] == "authenticated"

    with pytest.raises(pyjwt.InvalidAudienceError):
        pyjwt.decode(
            token,
            get_settings().supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_exp": False},  # the OLD options — no verify_aud
        )


@pytest.mark.unit
def test_two_different_users_get_two_different_buckets() -> None:
    """The property that actually matters, stated directly: user A's traffic must
    not consume user B's allowance."""
    other = "11111111-2222-3333-4444-555555555555"
    assert _get_user_key(_request(_token())) != _get_user_key(_request(_token(sub=other)))


@pytest.mark.unit
def test_an_expired_token_still_keys_by_user() -> None:
    """`verify_exp: False` is deliberate — `get_current_user` has already rejected
    an expired token before any handler runs, and re-checking here would demote a
    stale request to the shared IP bucket."""
    assert _get_user_key(_request(_token(exp=int(time.time()) - 60))) == f"user:{SUB}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("no header", None),
        ("not a jwt", "garbage"),
        (
            "wrong signature",
            # 32+ bytes: PyJWT raises InsecureKeyLengthWarning below that, which
            # would fail collection rather than exercise the fallback.
            pyjwt.encode(
                {"sub": SUB, "aud": "authenticated"},
                "a-different-secret-at-least-32-chars-long!!",
            ),
        ),
    ],
)
def test_unauthenticated_or_forged_tokens_fall_back_to_ip(label: str, token: str | None) -> None:
    """The fallback must survive — it is correct for callers with no usable
    identity. What was wrong was reaching it with a VALID token."""
    assert _get_user_key(_request(token)) == "203.0.113.7", label


@pytest.mark.unit
def test_an_es256_token_keys_the_bucket_by_user_not_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """D59: the same regression class as D52, one signing scheme later.

    Supabase projects that migrated to asymmetric "JWT Signing Keys" issue
    ES256 tokens. `dependencies.get_current_user` branches on `alg` and
    verifies these via JWKS; before this fix, `_get_user_key`'s OWN separate
    decode hardcoded `algorithms=["HS256"]` only, so every ES256 token raised
    `InvalidAlgorithmError`, was swallowed by the bare `except`, and fell back
    to the shared IP bucket -- reopening exactly what D52 closed.
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    claims = {
        "aud": "authenticated",
        "role": "authenticated",
        "sub": SUB,
        "iat": now,
        "exp": now + 3600,
    }
    token = pyjwt.encode(claims, private_key, algorithm="ES256")

    fake_signing_key = MagicMock()
    fake_signing_key.key = private_key.public_key()
    fake_jwks_client = MagicMock()
    fake_jwks_client.get_signing_key_from_jwt.return_value = fake_signing_key
    monkeypatch.setattr(
        dependencies_module, "_get_jwks_client", lambda settings: fake_jwks_client
    )

    assert _get_user_key(_request(token)) == f"user:{SUB}"


@pytest.mark.unit
def test_a_token_without_sub_falls_back_to_ip() -> None:
    """A signed token carrying no subject cannot key a user bucket."""
    now = int(time.time())
    token = pyjwt.encode(
        {"aud": "authenticated", "iat": now, "exp": now + 3600},
        get_settings().supabase_jwt_secret,
        algorithm="HS256",
    )
    assert _get_user_key(_request(token)) == "203.0.113.7"
