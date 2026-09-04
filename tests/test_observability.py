import json
import os
import unittest
from unittest.mock import patch
import sentry_sdk
from sentry_sdk.transport import Transport
from app import observability as monitoring


class SafeEventsTest(unittest.TestCase):
    def tearDown(self):
        if monitoring._client:
            monitoring._client.close()
        monitoring._client = None

    def test_disabled_without_dsn(self):
        with patch.dict(os.environ, {}, clear=True), patch("sentry_sdk.Client") as client:
            self.assertFalse(monitoring.initialize("core"))
            client.assert_not_called()

    def test_real_sdk_strips_every_sensitive_surface(self):
        captured = []
        class MemoryTransport(Transport):
            def capture_envelope(self, envelope):
                for item in envelope.items:
                    if item.type == "event":
                        captured.append(item.payload.json)
        real = sentry_sdk.Client
        def factory(**options):
            self.assertFalse(options["send_default_pii"])
            self.assertFalse(options["default_integrations"])
            self.assertEqual(options["max_breadcrumbs"], 0)
            return real(**options, transport=MemoryTransport)
        with patch.dict(os.environ, {"SENTRY_DSN":"https://public@example.invalid/1"}), patch("sentry_sdk.Client",side_effect=factory):
            monitoring.initialize("core")
        monitoring._client.capture_event({
            "message":"private assignment", "tags":{"category":"synthetic_check","secret":"private"},
            "request":{"headers":{"Cookie":"private","Authorization":"private"},"data":"private","query_string":"code=private"},
            "user":{"id":"private"}, "extra":{"DATABASE_URL":"private"},
            "exception":{"values":[{"type":"Error","value":"private","stacktrace":{"frames":[{"vars":{"key":"private"}}]}}]},
            "breadcrumbs":{"values":[{"message":"private"}]}, "contexts":{"photo":"private"}})
        self.assertEqual(len(captured),1)
        self.assertNotIn("private",json.dumps(captured))
        self.assertEqual(set(captured[0]), {"event_id","message","level","tags"})
        self.assertIsNone(monitoring.scrub({"event_id":"a"*32,"tags":{"category":"unknown"}}))
