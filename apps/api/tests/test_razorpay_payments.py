"""
Unit tests for Razorpay payment backend (Story 4-1).

AC coverage:
  AC-1: create-order response shape + no secret leak
  AC-2: webhook HMAC verification (raw bytes, not re-serialized JSON)
  AC-3: payment.captured calls handle_payment_captured
  AC-4: idempotent duplicate webhook returns 200
  AC-5: provider is called (not direct httpx)
  AC-6: env vars present in Settings
  AC-8: all 8 test cases
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

LESSON_ID  = "aaaaaaaa-0000-0000-0000-000000000001"
USER_ID    = "bbbbbbbb-0000-0000-0000-000000000002"
ORDER_ID   = "order_TestXYZ"
PAYMENT_ID = "pay_TestABC"


# ─── Helper: sign a raw body the same way Razorpay would ─────────────────────

def _sign(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


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
        mock_resp.json.return_value = {"id": ORDER_ID, "amount": 50000, "currency": "INR"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await self.provider.create_order(
                amount_paise=50000,
                currency="INR",
                notes={"user_id": USER_ID, "lesson_id": LESSON_ID},
            )
        assert result["id"] == ORDER_ID

    @pytest.mark.asyncio
    async def test_create_order_secret_not_in_body(self) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": ORDER_ID}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await self.provider.create_order(amount_paise=1000, currency="INR", notes={})
            # Secret must not appear in the JSON body (it should only appear in Basic Auth header)
            call_kwargs = mock_post.call_args
            json_body = str(call_kwargs.kwargs.get("json", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}))
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
            model_dump=lambda: {"order_id": ORDER_ID, "key_id": _SETTINGS.razorpay_key_id},
        )
        resp = self.client.post(
            "/api/payments/create-order",
            json={"lesson_id": LESSON_ID, "amount_paise": 50000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_id"] == ORDER_ID
        assert data["key_id"] == _SETTINGS.razorpay_key_id

    @patch("app.modules.payments.service.create_order")
    def test_response_has_no_secret(self, mock_svc: Any) -> None:
        mock_svc.return_value = MagicMock(
            order_id=ORDER_ID,
            key_id=_SETTINGS.razorpay_key_id,
            model_dump=lambda: {"order_id": ORDER_ID, "key_id": _SETTINGS.razorpay_key_id},
        )
        resp = self.client.post(
            "/api/payments/create-order",
            json={"lesson_id": LESSON_ID, "amount_paise": 50000},
        )
        assert _SETTINGS.razorpay_key_secret not in resp.text
        assert _SETTINGS.razorpay_webhook_secret not in resp.text


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
                        "amount": 50000,
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
