import unittest
from app.cloud_preflight import issues


class PreflightTest(unittest.TestCase):
    def test_missing_reports_names_only(self):
        for service in ("core", "bot"):
            result = issues({}, service)
            self.assertIn("missing:DATABASE_URL", result)

    def test_valid_configs_and_cutover_latch(self):
        common = dict(DATABASE_URL="postgresql://synthetic", TELEGRAM_BOT_TOKEN="synthetic")
        core = dict(common, APP_ENV="staging", OPENAI_API_KEY="synthetic",
                    BOT_BRIDGE_SECRET="x"*48, TELEGRAM_CLIENT_ID="synthetic",
                    TELEGRAM_CLIENT_SECRET="synthetic",
                    TELEGRAM_REDIRECT_URI="https://student-os.dev/api/auth/telegram/callback")
        bot = dict(common, STUDENT_OS_BRIDGE_SECRET="x"*48,
                   STUDENT_OS_API_URL="https://core.example", STUDENT_OS_BRIDGE_ENABLED="true")
        self.assertEqual(issues(core, "core"), [])
        self.assertEqual(issues(bot, "bot"), [])
        self.assertIn("unsafe:CLOUD_POLLING_ENABLED", issues(dict(bot, CLOUD_POLLING_ENABLED="true"), "bot"))
        self.assertIn("invalid:APP_ENV", issues(dict(core, APP_ENV="development"), "core"))
        for url in ("http://core.example", "https://private:secret@core.example", "https://core.example/?secret=private", "https://[invalid"):
            result = issues(dict(bot, STUDENT_OS_API_URL=url), "bot")
            self.assertIn("invalid:STUDENT_OS_API_URL", result)
            self.assertNotIn("private", repr(result))
