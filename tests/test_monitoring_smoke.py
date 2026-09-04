import contextlib
import io
import unittest
from unittest.mock import Mock, patch
from app import monitoring_smoke


class MonitoringSmokeTest(unittest.TestCase):
    def test_explicit_constant_event_and_bounded_flush(self):
        client = Mock()
        client.capture_event.return_value = "a" * 32
        with patch.object(monitoring_smoke.observability, "initialize", return_value=True) as init, patch.object(monitoring_smoke.observability, "_client", client), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(monitoring_smoke.main(["bot"]), 0)
        init.assert_called_once_with("bot")
        client.capture_event.assert_called_once_with({"message":"synthetic_check", "level":"error", "tags":{"category":"synthetic_check"}})
        client.flush.assert_called_once_with(timeout=10)
        self.assertIn("SENTRY_EVENT_QUEUED", output.getvalue())

    def test_missing_config_and_private_failure_are_safe(self):
        for result, error in [(False, None), (None, ValueError("private credential"))]:
            with patch.object(monitoring_smoke.observability, "initialize", return_value=result, side_effect=error), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(monitoring_smoke.main(["core"]), 1)
            self.assertNotIn("private", output.getvalue())
