import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.cloud_worker import main, validate, build


class CloudReadinessTest(unittest.TestCase):
    def test_build_installs_only_bridge_without_polling(self):
        values = dict(student_os_bridge_enabled=True, outbox_database_url='postgresql://example',
                      student_os_api_url='https://core.example', student_os_bridge_secret='x'*48,
                      telegram_bot_token='synthetic')
        settings = SimpleNamespace(**values)
        with patch('app.cloud_worker.Application') as factory, patch('app.cloud_worker.install') as install:
            app = factory.builder.return_value.token.return_value.post_init.return_value.post_shutdown.return_value.build.return_value
            self.assertIs(build(settings), app)
            install.assert_called_once_with(app, settings)
            app.run_polling.assert_not_called()

    def test_polling_disabled_before_credentials_or_bot_creation(self):
        with patch.dict(os.environ, {}, clear=True), patch('app.cloud_worker.load_settings') as load:
            with self.assertRaisesRegex(RuntimeError, 'polling disabled'):
                main()
            load.assert_not_called()

    def test_fail_closed_config(self):
        values = dict(student_os_bridge_enabled=True, outbox_database_url='postgresql://example',
                      student_os_api_url='https://core.example', student_os_bridge_secret='x'*48)
        validate(SimpleNamespace(**values))
        for key, value in [('student_os_bridge_enabled',False), ('outbox_database_url','local.db'),
                           ('student_os_api_url','http://core.example'), ('student_os_bridge_secret','weak')]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate(SimpleNamespace(**{**values,key:value}))
