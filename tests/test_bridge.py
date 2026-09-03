import hashlib
import hmac
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import os
from urllib.error import HTTPError, URLError

from app.bridge_client import BridgeError, StudentOSBridgeClient
from app.payment_outbox import PaymentOutbox


def payment():
    return {"charge_id": "synthetic-charge", "product_id": "task_help_1_v1",
            "stars_paid": 25, "telegram": {"telegram_user_id": 123, "display_name": "Әлия"}}


class BridgeTest(unittest.TestCase):
    def test_bridge_mode_does_not_require_legacy_ai_key(self):
        from app.config import load_settings
        env = {"TELEGRAM_BOT_TOKEN": "synthetic-token", "STUDENT_OS_BRIDGE_ENABLED": "true",
               "STUDENT_OS_API_URL": "https://core.example", "STUDENT_OS_BRIDGE_SECRET": "synthetic-secret"}
        with patch("app.config.load_dotenv"), patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_settings().openai_api_key, "")
            os.environ["STUDENT_OS_BRIDGE_ENABLED"] = "false"
            with self.assertRaises(RuntimeError):
                load_settings()

    def test_signs_exact_unicode_body_and_uses_timeout(self):
        client = StudentOSBridgeClient("https://core.example", "test-only-secret")
        client._opener = Mock()
        client._opener.open.return_value = io.BytesIO(b'{"ok":true}')
        self.assertEqual(client.record_payment(payment()), {"ok": True})
        req = client._opener.open.call_args.args[0]
        headers = dict((k.lower(), v) for k, v in req.header_items())
        expected = hmac.new(b"test-only-secret", b"v2.POST./api/internal/v1/payments/telegram-stars." + headers["x-bridge-timestamp"].encode() + b"."
                            + headers["x-bridge-nonce"].encode() + b"." + req.data, hashlib.sha256).hexdigest()
        self.assertEqual(headers["x-bridge-signature"], expected)
        self.assertEqual(json.loads(req.data), payment())
        self.assertEqual(client._opener.open.call_args.kwargs["timeout"], 10)

    def test_url_and_response_bounds_and_safe_errors(self):
        for url in ("http://example.com", "https://user:secret@example.com", "https://example.com?key=x", "file:///tmp/a"):
            with self.assertRaises(ValueError):
                StudentOSBridgeClient(url, "test-secret")
        client = StudentOSBridgeClient("http://127.0.0.1:8001", "test-secret")
        client._opener = Mock()
        for raw in (b"[]", b"bad", b"x" * (256 * 1024 + 1)):
            client._opener.open.return_value = io.BytesIO(raw)
            with self.assertRaises(BridgeError):
                client.get_products()
        for exc in (URLError("sensitive body"), HTTPError("secret-url", 401, "private", {}, None)):
            client._opener.open.side_effect = exc
            with self.assertRaises(BridgeError) as caught:
                client.get_products()
            self.assertNotIn("secret", str(caught.exception))
        with self.assertRaises(BridgeError):
            client.post("study/text", {"assignment": "x" * 70000})

    def test_outage_restart_duplicate_and_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "outbox.db"
            outbox = PaymentOutbox(path)
            outbox.enqueue(payment())
            core = Mock()
            core.record_payment.side_effect = BridgeError()
            self.assertEqual(outbox.retry(core), 0)
            reopened = PaymentOutbox(path)
            self.assertEqual(reopened.pending()[0]["attempts"], 1)
            reopened.enqueue(payment())
            self.assertEqual(len(reopened.pending()), 1)
            altered = payment()
            altered["stars_paid"] = 100
            with self.assertRaises(ValueError):
                reopened.enqueue(altered)
            stale = reopened.pending()[0]
            core.record_payment.side_effect = None
            core.record_payment.return_value = {"payment": {"telegram_payment_charge_id": "synthetic-charge",
                "product_id": "task_help_1_v1", "stars_paid": 25, "telegram_user_id": "123"}}
            self.assertEqual(reopened.retry(core), 1)
            core.record_payment.side_effect = BridgeError()
            reopened.deliver(core, stale)
            self.assertEqual(reopened.pending(), [])

    def test_invalid_receipt_stays_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            outbox = PaymentOutbox(Path(temp) / "outbox.db")
            outbox.enqueue(payment())
            core = Mock()
            core.record_payment.return_value = {}
            self.assertEqual(outbox.retry(core), 0)
            self.assertEqual(outbox.pending()[0]["last_error"], "core_http_502")
            outbox.enqueue(payment())
            self.assertEqual(len(outbox.pending()), 1)

    def test_outage_stops_batch_after_one_delivery_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            outbox = PaymentOutbox(Path(temp) / "outbox.db")
            for number in range(5):
                outbox.enqueue({**payment(), "charge_id": f"charge-{number}"})
            core = Mock()
            core.record_payment.side_effect = BridgeError(503)
            self.assertEqual(outbox.retry(core), 0)
            self.assertEqual(core.record_payment.call_count, 1)
            self.assertEqual(len(outbox.pending()), 5)
