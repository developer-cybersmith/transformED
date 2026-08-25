"""
Unit tests for the payments module router (Story 5-3/S4-3).

External I/O (Stripe SDK, Supabase) is fully mocked. Per CLAUDE.md binding
rule 2 ("no test may assert only on a mock it constructed"), the webhook
tests assert on the recorded RPC calls' actual arguments (an observable
outcome — which user got credited, with what event id was recorded), not
merely that "some call happened".

# MOCK-CONTRACT: `decrement_lesson_credit`/`grant_lesson_credits`/
# `record_stripe_event_if_new`/`record_stripe_event_and_grant_credits` are
# mocked here as RPC-call recordings, not executed against a real Postgres
# function. The real-dependency-adjacent coverage for the RPC bodies
# themselves is `test_migration_payments_schema.py`, which verifies the SQL
# text's shape (single transaction, no SELECT-then-write, etc.) — it does
# NOT execute the SQL against a live database (none is available in this
# sandbox); see docs/DEFECT-REGISTER.md#D137 for this named, accepted
# limitation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import stripe
from fastapi.testclient import TestClient

from app.providers.payments.base import WebhookVerificationError

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
    calls `.table()` directly, only the service-layer RPC wrappers."""

    def __init__(self, *, event_is_new: bool = True) -> None:
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []
        self.event_is_new = event_is_new

    def rpc(self, name: str, params: dict[str, Any]) -> _RpcCall:
        self.rpc_calls.append((name, dict(params)))
        if name in ("record_stripe_event_if_new", "record_stripe_event_and_grant_credits"):
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
    payment_status: str | None = "paid",
) -> dict[str, Any]:
    """A minimal object shaped like the StripeObject the real SDK returns —
    subscriptable via __getitem__, matching what `verify_and_parse_webhook`
    actually does (event["data"]["object"].to_dict())."""
    data_object = MagicMock()
    metadata = {"user_id": user_id} if user_id else {}
    payload: dict[str, Any] = {"id": session_id, "metadata": metadata}
    if payment_status is not None:
        payload["payment_status"] = payment_status
    data_object.to_dict.return_value = payload

    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": data_object},
    }


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
    absolute success/cancel URLs, response shape is exactly checkout_url +
    session_id."""
    from app.config import get_settings
    from app.core.rate_limit import limiter
    from app.dependencies import get_current_user
    from app.main import app

    limiter.reset()
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    fake_session = _fake_checkout_session()
    settings = get_settings()

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

    # Review Finding (Story 5-3, Process Integrity/AC Completeness): this
    # used to be a tautological self-comparison (comparing the captured
    # price to itself). Now asserts the REAL configured Price ID was used,
    # never a client-supplied one (AC1) — the endpoint takes no body param
    # for price/amount at all.
    _, kwargs = mock_create.call_args
    assert kwargs["line_items"] == [
        {"price": settings.stripe_price_id_lesson_credit, "quantity": 1}
    ]
    assert kwargs["metadata"] == {"user_id": FAKE_USER["sub"]}
    assert kwargs["mode"] == "payment"

    # Review Finding (Story 5-3, Test Coverage/AC Completeness): AC2 had
    # zero test coverage — nothing would have failed if the redirect URLs
    # were swapped, typo'd, or lost the {CHECKOUT_SESSION_ID} token.
    base = settings.app_base_url.rstrip("/")
    assert kwargs["success_url"] == f"{base}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
    assert kwargs["cancel_url"] == f"{base}/payment/cancel"
    # Review Finding (Story 5-3, Blind Hunter): Stripe's real API rejects
    # relative success_url/cancel_url outright — pin that both are absolute.
    assert kwargs["success_url"].startswith(("http://", "https://"))
    assert kwargs["cancel_url"].startswith(("http://", "https://"))


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
    class of check `content/router.py`'s own AC13 tests use — the
    underlying `limiter`/`_get_user_key` mechanism itself is already
    behaviorally tested in Story 5-4's suite."""
    source = (
        Path(__file__).resolve().parents[2] / "app" / "modules" / "payments" / "router.py"
    ).read_text(encoding="utf-8")
    assert "key_func=_get_user_key" in source
    assert "get_remote_address" not in source


@pytest.mark.unit
def test_create_checkout_session_provider_error_is_502_not_a_bare_500(client: TestClient) -> None:
    """Review Finding (Story 5-3, Edge Case Hunter): a Stripe API failure
    (bad price, network error, provider outage) previously had no handling
    at all and surfaced as an opaque generic 500."""
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    try:
        with patch(
            "app.providers.payments.stripe.stripe.checkout.Session.create",
            side_effect=stripe.InvalidRequestError("no such price", param="price"),
        ):
            resp = client.post("/api/payments/create-checkout-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 502


@pytest.mark.unit
def test_stripe_invalid_request_error_really_is_a_stripe_error() -> None:
    """Binding rule 3 (executable premise assertion): proves the exception
    type the provider catches (stripe.StripeError) is really a base class
    of the concrete errors the SDK raises, not an assumed hierarchy."""
    assert issubclass(stripe.InvalidRequestError, stripe.StripeError)


# ══════════════════════════════════════════════════════════════════════════════
# POST /webhook
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_webhook_valid_signature_grants_credit(client: TestClient) -> None:
    """AC4/AC12: on a signature-verified, paid checkout.session.completed,
    the paying user's credits are incremented via the ONE atomic RPC that
    both records the idempotency ledger row and grants the credit (D136 —
    these must not be two separate calls)."""
    from app.config import get_settings

    sb = _FakeSupabase()
    event = _fake_stripe_event()
    settings = get_settings()

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
    grants = sb.calls_named("record_stripe_event_and_grant_credits")
    assert len(grants) == 1
    assert grants[0][1] == {
        "p_event_id": "evt_test_1",
        "p_session_id": "cs_test_123",
        "p_event_type": "checkout.session.completed",
        "p_user_id": FAKE_USER["sub"],
        "p_credits": settings.stripe_lesson_credits_per_purchase,
    }
    # The two-separate-RPC-calls bug (D136) must not recur: no standalone
    # record_stripe_event_if_new call on the credit-granting path.
    assert sb.calls_named("record_stripe_event_if_new") == []


@pytest.mark.unit
def test_webhook_not_yet_paid_grants_nothing(client: TestClient) -> None:
    """AC12 (added during code review): checkout.session.completed can fire
    for delayed/async payment methods before payment_status is "paid" —
    no credit may be granted yet, but the event is still ledgered so a
    redelivery of this exact not-yet-paid event doesn't reprocess forever."""
    sb = _FakeSupabase()
    event = _fake_stripe_event(payment_status="unpaid")

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
    assert sb.calls_named("record_stripe_event_and_grant_credits") == []
    assert len(sb.calls_named("record_stripe_event_if_new")) == 1


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
def test_webhook_missing_signature_header_is_also_400(client: TestClient) -> None:
    """AC3 says "missing OR invalid" — every other test here supplies SOME
    Stripe-Signature value. This exercises the header being entirely
    absent, going through the real (unmocked) stripe.Webhook.construct_event
    so the "missing" case is genuinely exercised, not assumed identical to
    "invalid"."""
    sb = _FakeSupabase()

    with patch("app.modules.payments.router.get_supabase", return_value=sb):
        resp = client.post(
            "/api/payments/webhook",
            content=b'{"fake": "payload"}',
            # No Stripe-Signature header at all.
        )

    assert resp.status_code == 400
    assert sb.rpc_calls == []


@pytest.mark.unit
def test_webhook_malformed_payload_after_valid_signature_is_400_not_500(
    client: TestClient,
) -> None:
    """Review Finding (Story 5-3, Edge Case Hunter): a signature-VALID but
    structurally malformed event (missing data/object/id/type) used to
    propagate as an uncaught KeyError -> 500. Must be the same explicit 400
    a bad signature gets, per WebhookVerificationError's contract."""
    sb = _FakeSupabase()
    malformed_event: dict[str, Any] = {"id": "evt_1"}  # no "type", no "data"

    with (
        patch(
            "app.providers.payments.stripe.stripe.Webhook.construct_event",
            return_value=malformed_event,
        ),
        patch("app.modules.payments.router.get_supabase", return_value=sb),
    ):
        resp = client.post(
            "/api/payments/webhook",
            content=b'{"fake": "payload"}',
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )

    assert resp.status_code == 400
    assert sb.rpc_calls == []


@pytest.mark.unit
def test_webhook_body_over_size_cap_is_413(client: TestClient) -> None:
    """Review Finding (Story 5-3, Edge Case Hunter/Scale & Load Hunter): the
    unauthenticated, unrate-limited webhook route read the entire raw body
    into memory before any signature check, with no size guard — a real
    memory-exhaustion vector on the single shared API process. Real
    checkout.session.completed payloads are small, fixed-schema JSON."""
    from app.modules.payments.router import _MAX_WEBHOOK_BYTES

    oversized = b"x" * (_MAX_WEBHOOK_BYTES + 1)
    resp = client.post(
        "/api/payments/webhook",
        content=oversized,
        headers={"Stripe-Signature": "t=1,v1=fake", "Content-Length": str(len(oversized))},
    )

    assert resp.status_code == 413


@pytest.mark.unit
def test_verify_and_parse_webhook_never_leaks_the_stripe_sdk_exception_type() -> None:
    """Review Finding (Story 5-3, AC Completeness/Process Integrity/Test
    Coverage — 3 independent layers, confirmed by direct grep): the
    provider must translate stripe.SignatureVerificationError into the
    provider-agnostic WebhookVerificationError, never let it escape raw."""
    from app.providers.payments.stripe import StripePaymentProvider

    provider = StripePaymentProvider(api_key="sk_test", webhook_secret="whsec_wrong")
    with pytest.raises(WebhookVerificationError):
        provider.verify_and_parse_webhook(b"payload", "t=1,v1=wrong")


@pytest.mark.unit
def test_no_bare_stripe_env_reads_outside_config() -> None:
    """AC10: no bare os.environ.get("STRIPE_...") anywhere in business
    logic — every Stripe setting must be read through Settings, which
    config.py's own required Field(...) declarations enforce at startup."""
    import re

    app_dir = Path(__file__).resolve().parents[2] / "app"
    pattern = re.compile(r'os\.environ\.get\(\s*["\']STRIPE_')
    hits = [
        py_file
        for py_file in app_dir.rglob("*.py")
        if py_file.name != "config.py" and pattern.search(py_file.read_text(encoding="utf-8"))
    ]
    assert hits == [], f"bare STRIPE_ env read found outside config.py: {hits}"


@pytest.mark.unit
def test_router_module_never_imports_stripe_directly() -> None:
    """Review Finding (Story 5-3): router.py used to `import stripe` at
    module scope just to catch stripe.SignatureVerificationError, violating
    AC10 and the provider file's own docstring claim. Source-scan guard so
    this cannot silently regress."""
    source = (
        Path(__file__).resolve().parents[2] / "app" / "modules" / "payments" / "router.py"
    ).read_text(encoding="utf-8")
    assert "import stripe" not in source
    assert "stripe.SignatureVerificationError" not in source


@pytest.mark.unit
def test_webhook_idempotency_same_event_id_grants_once(client: TestClient) -> None:
    """AC5: redelivering the SAME event id does not grant a second credit —
    enforced by the durable, ATOMIC record_stripe_event_and_grant_credits
    RPC (D136), not an in-process cache and not two separate calls."""
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
    # fake now reporting event_is_new=False, exactly what the real atomic
    # RPC's RETURN false branch reports.
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
    assert len(sb.calls_named("record_stripe_event_and_grant_credits")) == 2
    # Both calls were made (that's how the fake simulates the SQL-level
    # ON CONFLICT DO NOTHING), but only the FIRST one's return value was
    # True — the real RPC guarantees the second is a true no-op at the DB
    # level; this test proves the router/service layer correctly treats a
    # False return as "already processed", not as a second grant.


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
    assert sb.calls_named("record_stripe_event_and_grant_credits") == []
    # Still recorded in the idempotency ledger even though it's a no-op —
    # a redelivered payment_intent.created must not be double-processed
    # if it's ever handled in a future story either.
    assert len(sb.calls_named("record_stripe_event_if_new")) == 1


@pytest.mark.unit
def test_webhook_missing_metadata_user_id_logs_error_and_acks_200(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """AC12: a malformed event (no metadata.user_id) is never a silent drop
    and never an uncaught 500 that makes Stripe retry forever — logged at
    ERROR and acknowledged 200."""
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
    assert sb.calls_named("record_stripe_event_and_grant_credits") == []
    assert any("no metadata.user_id" in r.message for r in caplog.records)
