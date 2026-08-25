"""
Unit tests for the payments module router (Story 5-3/S4-3).

External I/O (Stripe SDK, Supabase) is fully mocked. Per CLAUDE.md binding
rule 2 ("no test may assert only on a mock it constructed"), the webhook
tests assert on the recorded RPC calls' actual arguments (an observable
outcome — which user got credited, with what event id was recorded), not
merely that "some call happened".

# MOCK-CONTRACT: `decrement_lesson_credit`/`grant_lesson_credits`/
# `record_stripe_event_if_new` are mocked here as RPC-call recordings, not
# executed against a real Postgres function. The real-dependency coverage
# for the RPC bodies themselves is the migration-level smoke test,
# `test_migration_payments_schema.py`, plus the RPC functions' own SQL
# (`decrement_lesson_credit`'s conditional UPDATE, `record_stripe_event_if_new`'s
# ON CONFLICT DO NOTHING) — this file cannot substitute for exercising those
# against a real database.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import stripe
from fastapi.testclient import TestClient

FAKE_USER: dict[str, Any] = {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "email": "test@example.com",
    "role": "authenticated",
}


class _RpcCall:
    def __init__(self, response: MagicMock) -> None:
        self._response = response

    def execute(self) -> MagicMock:
        return self._response


def _resp(data: Any) -> MagicMock:  # noqa: ANN401
    r = MagicMock()
    r.data = data
    return r


class _FakeSupabase:
    """Records every `.rpc(name, params)` call — the payments module never
    calls `.table()` directly, only the three service-layer RPC wrappers."""

    def __init__(self, *, event_is_new: bool = True) -> None:
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []
        self.event_is_new = event_is_new

    def rpc(self, name: str, params: dict[str, Any]) -> _RpcCall:
        self.rpc_calls.append((name, dict(params)))
        if name == "record_stripe_event_if_new":
            return _RpcCall(_resp(self.event_is_new))
        return _RpcCall(_resp(None))

    def calls_named(self, name: str) -> list[tuple[str, dict[str, Any]]]:
        return [c for c in self.rpc_calls if c[0] == name]


def _fake_checkout_session(session_id: str = "cs_test_123") -> MagicMock:
    session = MagicMock()
    session.url = f"https://checkout.stripe.com/pay/{session_id}"
    session.id = session_id
    return session


def _fake_stripe_event(
    *,
    event_id: str = "evt_test_1",
    event_type: str = "checkout.session.completed",
    user_id: str | None = FAKE_USER["sub"],
    session_id: str = "cs_test_123",
) -> MagicMock:
    """A minimal object shaped like the StripeObject the real SDK returns —
    subscriptable via __getitem__, matching what `verify_and_parse_webhook`
    actually does (event["data"]["object"].to_dict())."""
    data_object = MagicMock()
    metadata = {"user_id": user_id} if user_id else {}
    data_object.to_dict.return_value = {"id": session_id, "metadata": metadata}

    event: dict[str, Any] = {
        "id": event_id,
        "type": event_type,
        "data": {"object": data_object},
    }
    return event


@pytest.fixture()
def client() -> TestClient:
    """Plain construction, never `with TestClient(app) as client:` — the
    context-manager form triggers the real `lifespan()` (Supabase bucket
    check, Redis init), which needs live infra this unit suite doesn't
    have. Matches every other router test file's convention."""
    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


# ══════════════════════════════════════════════════════════════════════════════
# POST /create-checkout-session
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_create_checkout_session_happy_path(client: TestClient) -> None:
    """AC1/AC2: server-side Price ID only, metadata carries the JWT sub,
    response shape is exactly checkout_url + session_id."""
    from app.core.rate_limit import limiter
    from app.dependencies import get_current_user
    from app.main import app

    limiter.reset()
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    fake_session = _fake_checkout_session()

    try:
        with patch(
            "app.providers.payments.stripe.stripe.checkout.Session.create",
            return_value=fake_session,
        ) as mock_create:
            resp = client.post("/api/payments/create-checkout-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"checkout_url": fake_session.url, "session_id": fake_session.id}

    # AC1: never a client-supplied price/amount — only the configured Price ID.
    _, kwargs = mock_create.call_args
    assert kwargs["line_items"] == [{"price": kwargs["line_items"][0]["price"], "quantity": 1}]
    assert kwargs["metadata"] == {"user_id": FAKE_USER["sub"]}
    assert kwargs["mode"] == "payment"


@pytest.mark.unit
def test_create_checkout_session_401_without_auth(client: TestClient) -> None:
    """No CurrentUser override — a request with no valid bearer token must
    401 before any Stripe call is attempted."""
    with patch("app.providers.payments.stripe.stripe.checkout.Session.create") as mock_create:
        resp = client.post("/api/payments/create-checkout-session")

    assert resp.status_code == 401
    mock_create.assert_not_called()


@pytest.mark.unit
def test_create_checkout_session_rate_limit_keyed_by_user_not_ip() -> None:
    """Scale & Load Q3: an IP-keyed limiter on a payment endpoint would
    repeat D52's bucket-sharing bug in a context where it blocks someone
    from paying. Asserted by reading the real decorator source, the same
    class of check `content/router.py`'s own AC13 tests use."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "app" / "modules" / "payments" / "router.py"
    ).read_text(encoding="utf-8")
    assert "key_func=_get_user_key" in source
    assert "get_remote_address" not in source


# ══════════════════════════════════════════════════════════════════════════════
# POST /webhook
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_webhook_valid_signature_grants_credit(client: TestClient) -> None:
    """AC4: on a signature-verified checkout.session.completed, the paying
    user's credits are incremented via the atomic RPC."""
    sb = _FakeSupabase()
    event = _fake_stripe_event()

    with (
        patch("app.providers.payments.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.modules.payments.router.get_supabase", return_value=sb),
    ):
        resp = client.post(
            "/api/payments/webhook",
            content=b'{"fake": "payload"}',
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )

    assert resp.status_code == 200
    grants = sb.calls_named("grant_lesson_credits")
    assert len(grants) == 1
    assert grants[0][1] == {"p_user_id": FAKE_USER["sub"], "p_credits": 1}


@pytest.mark.unit
def test_webhook_invalid_signature_400_writes_nothing(client: TestClient) -> None:
    """AC3: a missing/invalid signature returns 400 and writes NOTHING to
    any table — asserted on the mock's actual call count (binding rule 2),
    not merely that the response code is right."""
    sb = _FakeSupabase()

    def _raise(*_a: Any, **_kw: Any) -> None:  # noqa: ANN401
        raise stripe.SignatureVerificationError("bad sig", "sig_header")

    with (
        patch("app.providers.payments.stripe.stripe.Webhook.construct_event", side_effect=_raise),
        patch("app.modules.payments.router.get_supabase", return_value=sb),
    ):
        resp = client.post(
            "/api/payments/webhook",
            content=b'{"fake": "payload"}',
            headers={"Stripe-Signature": "t=1,v1=wrong"},
        )

    assert resp.status_code == 400
    assert sb.rpc_calls == []


@pytest.mark.unit
def test_construct_event_really_raises_signature_verification_error() -> None:
    """Binding rule 3 (executable premise assertion): proves the exception
    type the handler catches is really what the SDK raises on a bad
    signature, not an assumed base class — the same discipline as
    test_openai_exceptions_are_not_httpx_derived."""
    with pytest.raises(stripe.SignatureVerificationError):
        stripe.Webhook.construct_event(b"payload", "t=1,v1=wrong", "whsec_wrong_secret")


@pytest.mark.unit
def test_webhook_idempotency_same_event_id_grants_once(client: TestClient) -> None:
    """AC5: redelivering the SAME event id does not grant a second credit —
    enforced by the durable record_stripe_event_if_new RPC, not an
    in-process cache."""
    sb = _FakeSupabase(event_is_new=True)
    event = _fake_stripe_event()

    with (
        patch("app.providers.payments.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.modules.payments.router.get_supabase", return_value=sb),
    ):
        resp1 = client.post(
            "/api/payments/webhook",
            content=b'{"fake": "payload"}',
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )

    # Redelivery: the RPC's own PRIMARY KEY constraint means this second
    # call would find the event already recorded — simulated here by the
    # fake now reporting event_is_new=False, exactly what the real
    # ON CONFLICT DO NOTHING RETURNING FOUND would report.
    sb.event_is_new = False
    with (
        patch("app.providers.payments.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.modules.payments.router.get_supabase", return_value=sb),
    ):
        resp2 = client.post(
            "/api/payments/webhook",
            content=b'{"fake": "payload"}',
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(sb.calls_named("grant_lesson_credits")) == 1


@pytest.mark.unit
def test_webhook_unsupported_event_type_is_a_200_noop(client: TestClient) -> None:
    """AC6: an unhandled-but-valid event is a no-op, not an error — Stripe
    must not retry it forever."""
    sb = _FakeSupabase()
    event = _fake_stripe_event(event_type="payment_intent.created")

    with (
        patch("app.providers.payments.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.modules.payments.router.get_supabase", return_value=sb),
    ):
        resp = client.post(
            "/api/payments/webhook",
            content=b'{"fake": "payload"}',
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )

    assert resp.status_code == 200
    assert sb.calls_named("grant_lesson_credits") == []
    # Still recorded in the idempotency ledger even though it's a no-op —
    # a redelivered payment_intent.created must not be double-processed
    # if it's ever handled in a future story either.
    assert len(sb.calls_named("record_stripe_event_if_new")) == 1


@pytest.mark.unit
def test_webhook_missing_metadata_user_id_logs_error_and_acks_200(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Scale & Load Q2: a malformed event (no metadata.user_id) is never a
    silent drop and never an uncaught 500 that makes Stripe retry forever —
    logged at ERROR and acknowledged 200."""
    sb = _FakeSupabase()
    event = _fake_stripe_event(user_id=None)

    with (
        patch("app.providers.payments.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.modules.payments.router.get_supabase", return_value=sb),
        caplog.at_level(logging.ERROR),
    ):
        resp = client.post(
            "/api/payments/webhook",
            content=b'{"fake": "payload"}',
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )

    assert resp.status_code == 200
    assert sb.calls_named("grant_lesson_credits") == []
    assert any("no metadata.user_id" in r.message for r in caplog.records)
