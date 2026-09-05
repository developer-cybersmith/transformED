"""
Unit tests for Razorpay payment backend (Story 4-1).

AC coverage:
  AC-1: create-order response shape + no secret leak
  AC-2: webhook HMAC verification (raw bytes, not re-serialized JSON)
  AC-3: payment.captured calls handle_payment_captured
  AC-4: idempotent duplicate webhook returns 200
  AC-5: provider is called (not direct httpx)
  AC-6: env vars present in Settings
  AC-8: all test cases

S4-1 patch 1: server uses DB price, not client amount_paise
S4-1 patch 2: 23505 idempotency catch tested directly (not via mock)
S4-1 patch 3: 23503 FK violation emits logger.critical and returns 200
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings

# ─── Test settings fixture ────────────────────────────────────────────────────


def _make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "supabase_url": "https://x.supabase.co",
        "supabase_anon_key": "anon",
        "supabase_service_role_key": "service",
        "supabase_jwt_secret": "secret",
        "openai_api_key": "sk-test",
        "sarvam_api_key": "sarvam",
        "heygen_api_key": "heygen",
        "langfuse_public_key": "pk",
        "langfuse_secret_key": "sk",
        "razorpay_key_id": "rzp_test_KEYID",
        "razorpay_key_secret": "test_SECRET",
        "razorpay_webhook_secret": "whsec_TEST",
    }
    base.update(overrides)
    return Settings(**base)


_SETTINGS = _make_settings()

LESSON_ID = "aaaaaaaa-0000-0000-0000-000000000001"
USER_ID = "bbbbbbbb-0000-0000-0000-000000000002"
ORDER_ID = "order_TestXYZ"
PAYMENT_ID = "pay_TestABC"
DB_PRICE = 99900  # ₹999 in paise — the canonical DB price


# ─── Helper: sign a raw body the same way Razorpay would ─────────────────────


def _sign(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


# ─── Helper: mock Supabase client returning a lesson row ─────────────────────


def _mock_supabase_lesson(price_paise: int = DB_PRICE) -> MagicMock:
    """Return a mock Supabase client whose lessons query returns a lesson row."""
    mock_sb = MagicMock()
    (
        mock_sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data
    ) = {"price_paise": price_paise}
    return mock_sb


def _mock_supabase_no_lesson() -> MagicMock:
    """Return a mock Supabase client whose lessons query returns no row (lesson gone)."""
    mock_sb = MagicMock()
    (
        mock_sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data
    ) = None
    return mock_sb


# ─── AC-6: Razorpay env vars are present in Settings ─────────────────────────


def test_settings_has_razorpay_key_id() -> None:
    assert _SETTINGS.razorpay_key_id == "rzp_test_KEYID"


def test_settings_has_razorpay_key_secret() -> None:
    assert _SETTINGS.razorpay_key_secret == "test_SECRET"


def test_settings_has_razorpay_webhook_secret() -> None:
    assert _SETTINGS.razorpay_webhook_secret == "whsec_TEST"


# ─── AC-2 + AC-5: RazorpayProvider.verify_signature ─────────────────────────


class TestVerifySignature:
    def setup_method(self) -> None:
        from app.providers.payments.razorpay import RazorpayProvider

        self.provider = RazorpayProvider(settings=_SETTINGS)

    def test_valid_signature_returns_true(self) -> None:
        body = b'{"event":"payment.captured"}'
        sig = _sign(_SETTINGS.razorpay_webhook_secret, body)
        assert self.provider.verify_signature(body, sig) is True

    def test_invalid_signature_returns_false(self) -> None:
        body = b'{"event":"payment.captured"}'
        assert self.provider.verify_signature(body, "deadbeef") is False

    def test_empty_signature_returns_false(self) -> None:
        body = b'{"event":"payment.captured"}'
        assert self.provider.verify_signature(body, "") is False

    def test_raw_bytes_not_reserialized_json(self) -> None:
        """AC-2: signature must be over raw bytes — re-dumping JSON is a different byte string."""
        raw_body = b'{ "b": 2,  "a": 1 }'
        sig = _sign(_SETTINGS.razorpay_webhook_secret, raw_body)

        # Correct path: raw bytes match
        assert self.provider.verify_signature(raw_body, sig) is True

        # If provider had re-serialized, it would produce {"a":1,"b":2} — different bytes
        re_serialized = json.dumps(json.loads(raw_body), separators=(",", ":")).encode()
        re_sig = _sign(_SETTINGS.razorpay_webhook_secret, re_serialized)
        # Different body → different signature → verify would return False if given re_sig
        assert raw_body != re_serialized
        assert sig != re_sig
        assert self.provider.verify_signature(raw_body, re_sig) is False


# ─── AC-1 + AC-5: RazorpayProvider.create_order ──────────────────────────────


class TestCreateOrderProvider:
    def setup_method(self) -> None:
        from app.providers.payments.razorpay import RazorpayProvider

        self.provider = RazorpayProvider(settings=_SETTINGS)

    @pytest.mark.asyncio
    async def test_create_order_returns_order_id(self) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": ORDER_ID, "amount": DB_PRICE, "currency": "INR"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await self.provider.create_order(
                amount_paise=DB_PRICE,
                currency="INR",
                notes={"user_id": USER_ID, "lesson_id": LESSON_ID},
            )
        assert result["id"] == ORDER_ID

    @pytest.mark.asyncio
    async def test_create_order_secret_not_in_body(self) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": ORDER_ID}

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_post:
            await self.provider.create_order(amount_paise=1000, currency="INR", notes={})
            # Secret must not appear in the JSON body (it should only appear in Basic Auth header)
            call_kwargs = mock_post.call_args
            fallback = call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
            json_body = str(call_kwargs.kwargs.get("json", fallback))
            assert _SETTINGS.razorpay_key_secret not in json_body


# ─── Endpoint test app factory ────────────────────────────────────────────────


def _build_test_app() -> FastAPI:
    from app.config import get_settings
    from app.dependencies import require_approved_user
    from app.modules.payments.router import router as payments_router

    app = FastAPI()
    app.include_router(payments_router, prefix="/api/payments")
    app.dependency_overrides[get_settings] = lambda: _SETTINGS
    app.dependency_overrides[require_approved_user] = lambda: {
        "sub": USER_ID,
        "email": "test@test.com",
    }
    return app


# ─── AC-1: POST /api/payments/create-order ────────────────────────────────────


class TestCreateOrderEndpoint:
    def setup_method(self) -> None:
        self.client = TestClient(_build_test_app(), raise_server_exceptions=True)

    @patch("app.modules.payments.service.create_order")
    def test_response_has_order_id_and_key_id(self, mock_svc: Any) -> None:
        mock_svc.return_value = MagicMock(
            order_id=ORDER_ID,
            key_id=_SETTINGS.razorpay_key_id,
            price_paise=DB_PRICE,
            model_dump=lambda: {
                "order_id": ORDER_ID,
                "key_id": _SETTINGS.razorpay_key_id,
                "price_paise": DB_PRICE,
            },
        )
        resp = self.client.post(
            "/api/payments/create-order",
            json={"lesson_id": LESSON_ID, "amount_paise": 50000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_id"] == ORDER_ID
        assert data["key_id"] == _SETTINGS.razorpay_key_id
        assert data["price_paise"] == DB_PRICE

    @patch("app.modules.payments.service.create_order")
    def test_response_has_no_secret(self, mock_svc: Any) -> None:
        mock_svc.return_value = MagicMock(
            order_id=ORDER_ID,
            key_id=_SETTINGS.razorpay_key_id,
            price_paise=DB_PRICE,
            model_dump=lambda: {
                "order_id": ORDER_ID,
                "key_id": _SETTINGS.razorpay_key_id,
                "price_paise": DB_PRICE,
            },
        )
        resp = self.client.post(
            "/api/payments/create-order",
            json={"lesson_id": LESSON_ID, "amount_paise": 50000},
        )
        assert _SETTINGS.razorpay_key_secret not in resp.text
        assert _SETTINGS.razorpay_webhook_secret not in resp.text

    @patch("app.modules.payments.service.create_order")
    def test_lesson_not_found_returns_404(self, mock_svc: Any) -> None:
        """S4-1 patch 1: missing lesson_id should return 404, not 500."""
        from app.modules.payments.service import LessonNotFoundError

        mock_svc.side_effect = LessonNotFoundError("nonexistent-uuid")
        resp = self.client.post(
            "/api/payments/create-order",
            json={"lesson_id": "nonexistent-uuid", "amount_paise": 50000},
        )
        assert resp.status_code == 404


# ─── AC-2, AC-3, AC-4: POST /api/payments/webhook ────────────────────────────


class TestWebhookEndpoint:
    def setup_method(self) -> None:
        self.client = TestClient(_build_test_app(), raise_server_exceptions=False)

    def _raw_and_headers(self, event: str = "payment.captured") -> tuple[bytes, dict[str, str]]:
        payload = {
            "event": event,
            "payload": {
                "payment": {
                    "entity": {
                        "id": PAYMENT_ID,
                        "order_id": ORDER_ID,
                        "amount": DB_PRICE,
                        "currency": "INR",
                        "notes": {"user_id": USER_ID, "lesson_id": LESSON_ID},
                    }
                }
            },
        }
        raw = json.dumps(payload).encode()
        sig = _sign(_SETTINGS.razorpay_webhook_secret, raw)
        return raw, {"X-Razorpay-Signature": sig, "Content-Type": "application/json"}

    @patch("app.modules.payments.service.handle_payment_captured", new_callable=AsyncMock)
    def test_valid_signature_captured_returns_200(self, mock_handle: Any) -> None:
        raw, headers = self._raw_and_headers("payment.captured")
        mock_handle.return_value = None
        resp = self.client.post("/api/payments/webhook", content=raw, headers=headers)
        assert resp.status_code == 200

    def test_invalid_signature_returns_400(self) -> None:
        raw, headers = self._raw_and_headers()
        headers["X-Razorpay-Signature"] = "badsig"
        resp = self.client.post("/api/payments/webhook", content=raw, headers=headers)
        assert resp.status_code == 400

    def test_missing_signature_returns_400(self) -> None:
        raw, _ = self._raw_and_headers()
        resp = self.client.post(
            "/api/payments/webhook",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    @patch("app.modules.payments.service.handle_payment_captured", new_callable=AsyncMock)
    def test_non_captured_event_does_not_call_handle(self, mock_handle: Any) -> None:
        raw, headers = self._raw_and_headers("payment.failed")
        resp = self.client.post("/api/payments/webhook", content=raw, headers=headers)
        assert resp.status_code == 200
        mock_handle.assert_not_called()

    @patch("app.modules.payments.service.handle_payment_captured", new_callable=AsyncMock)
    def test_duplicate_webhook_both_return_200(self, mock_handle: Any) -> None:
        raw, headers = self._raw_and_headers("payment.captured")
        mock_handle.return_value = None
        r1 = self.client.post("/api/payments/webhook", content=raw, headers=headers)
        r2 = self.client.post("/api/payments/webhook", content=raw, headers=headers)
        assert r1.status_code == 200
        assert r2.status_code == 200

    @patch("app.modules.payments.service.handle_payment_captured", new_callable=AsyncMock)
    def test_captured_event_calls_handle_payment_captured(self, mock_handle: Any) -> None:
        raw, headers = self._raw_and_headers("payment.captured")
        mock_handle.return_value = None
        self.client.post("/api/payments/webhook", content=raw, headers=headers)
        mock_handle.assert_called_once()


# ─── S4-1 patch 1: service.create_order uses DB price, not client amount ──────


class TestCreateOrderServicePrice:
    """Direct service-layer tests for price enforcement (S4-1 patch 1)."""

    @pytest.mark.asyncio
    async def test_create_order_uses_db_price_not_client_amount(self) -> None:
        """Server must use lessons.price_paise, ignoring any client-supplied amount."""
        from app.modules.payments.service import create_order

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": ORDER_ID}

        with patch("app.core.db.get_supabase", return_value=_mock_supabase_lesson(DB_PRICE)):
            with patch(
                "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
            ) as mock_post:
                result = await create_order(
                    lesson_id=LESSON_ID,
                    user_id=USER_ID,
                    settings=_SETTINGS,
                )

        json_body = mock_post.call_args.kwargs["json"]
        assert json_body["amount"] == DB_PRICE, (
            f"Server must use DB price {DB_PRICE!r}, not any client-supplied value"
        )
        assert result.price_paise == DB_PRICE

    @pytest.mark.asyncio
    async def test_create_order_raises_lesson_not_found(self) -> None:
        """create_order must raise LessonNotFoundError when lesson_id is absent."""
        from app.modules.payments.service import LessonNotFoundError, create_order

        with patch("app.core.db.get_supabase", return_value=_mock_supabase_no_lesson()):
            with pytest.raises(LessonNotFoundError):
                await create_order(
                    lesson_id="00000000-0000-0000-0000-000000000000",
                    user_id=USER_ID,
                    settings=_SETTINGS,
                )


# ─── S4-1 patch 2: handle_payment_captured idempotency — tested directly ──────


class TestHandlePaymentCapturedIdempotency:
    """Direct tests for the 23505 catch in handle_payment_captured (patch 2).

    Previously this logic was only tested via a mock that bypassed the function
    entirely (MOCK-CONTRACT). These tests exercise the real exception-catch path.
    """

    def _entity(self) -> dict[str, Any]:
        return {
            "id": PAYMENT_ID,
            "order_id": ORDER_ID,
            "amount": DB_PRICE,
            "currency": "INR",
            "notes": {"user_id": USER_ID, "lesson_id": LESSON_ID},
        }

    @pytest.mark.asyncio
    async def test_23505_unique_violation_returns_cleanly(self) -> None:
        """23505 error string → function returns without re-raising (idempotent)."""
        from app.modules.payments.service import handle_payment_captured

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception(
            "ERROR: duplicate key value violates unique constraint 23505"
        )

        with patch("app.core.db.get_supabase", return_value=mock_sb):
            # Must not raise — the idempotency catch should absorb it
            await handle_payment_captured(self._entity())

    @pytest.mark.asyncio
    async def test_duplicate_key_phrase_returns_cleanly(self) -> None:
        """'duplicate key' phrase (lowercase) also triggers idempotency catch."""
        from app.modules.payments.service import handle_payment_captured

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint"
        )

        with patch("app.core.db.get_supabase", return_value=mock_sb):
            await handle_payment_captured(self._entity())

    @pytest.mark.asyncio
    async def test_unexpected_exception_reraises(self) -> None:
        """An unrecognised exception must propagate so webhook returns 500."""
        from app.modules.payments.service import handle_payment_captured

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError(
            "connection pool exhausted"
        )

        with patch("app.core.db.get_supabase", return_value=mock_sb):
            with pytest.raises(RuntimeError, match="connection pool exhausted"):
                await handle_payment_captured(self._entity())


# ─── S4-1 patch 3: FK violation (23503) emits critical alert ──────────────────


class TestHandlePaymentCapturedFKViolation:
    """Direct tests for the 23503 catch added in S4-1 patch 3."""

    def _entity(self) -> dict[str, Any]:
        return {
            "id": PAYMENT_ID,
            "order_id": ORDER_ID,
            "amount": DB_PRICE,
            "currency": "INR",
            "notes": {"user_id": USER_ID, "lesson_id": LESSON_ID},
        }

    @pytest.mark.asyncio
    async def test_23503_fk_violation_emits_critical_and_returns(self) -> None:
        """FK violation (deleted lesson) must emit logger.critical and return 200."""
        from app.modules.payments.service import handle_payment_captured

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception(
            "ERROR: insert violates foreign key constraint 23503"
        )

        with patch("app.core.db.get_supabase", return_value=mock_sb):
            with patch("app.modules.payments.service.logger") as mock_logger:
                # Must not raise — return 200 to stop Razorpay retrying
                await handle_payment_captured(self._entity())
                mock_logger.critical.assert_called_once()
                critical_msg: str = mock_logger.critical.call_args[0][0]
                assert "MANUAL REFUND" in critical_msg

    @pytest.mark.asyncio
    async def test_foreign_key_phrase_triggers_critical(self) -> None:
        """'foreign key' phrase also triggers the FK violation catch."""
        from app.modules.payments.service import handle_payment_captured

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception(
            "foreign key violation on table lesson_access"
        )

        with patch("app.core.db.get_supabase", return_value=mock_sb):
            with patch("app.modules.payments.service.logger") as mock_logger:
                await handle_payment_captured(self._entity())
                mock_logger.critical.assert_called_once()
