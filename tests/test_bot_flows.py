import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.ai_service import AIAnswer
from app.bot import (
    admin,
    admin_callback,
    admin_or_question,
    defense_callback,
    feedback_callback,
    funnel,
    funnel_csv,
    handle_photo,
    handle_question,
    photo_callback,
    post_init,
    post_shutdown,
)
from app.database import Database


class FakeMessage:
    def __init__(self) -> None:
        self.photo = [SimpleNamespace(file_id="photo-1", file_size=100)]
        self.caption = "Реши задачу 1"
        self.text = "Теперь реши задачу 2"
        self.sent = []
        self.sent_documents = []

    async def reply_text(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return self

    async def reply_document(self, document, **kwargs):
        self.sent_documents.append((document, kwargs))
        return self


class FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))

    async def edit_message_reply_markup(self, **kwargs):
        self.edits.append(("reply_markup", kwargs))


class FakeTelegramFile:
    async def download_as_bytearray(self):
        return bytearray(b"photo")


class FakeBot:
    def __init__(self):
        self.command_sets = []

    async def send_chat_action(self, *args, **kwargs):
        return None

    async def get_file(self, file_id):
        return FakeTelegramFile()

    async def set_my_commands(self, commands, **kwargs):
        self.command_sets.append((commands, kwargs))

    async def send_message(self, *args, **kwargs):
        return None


class FailingAI:
    def extract_image_tasks(self, image_bytes):
        raise RuntimeError("technical test failure")


class SuccessfulAI:
    def __init__(self):
        self.defense_calls = 0

    def extract_image_tasks(self, image_bytes):
        return AIAnswer("Задача 1 и задача 2", 10, 20, 0.01)

    def answer_photo_session(self, recognized_tasks, request, previous_request=""):
        return AIAnswer(f"Решение для: {request}", 5, 10, 0.005)

    def defense_explanation(self, task_context, answer_text):
        self.defense_calls += 1
        return AIAnswer("Короткое объяснение для защиты", 3, 6, 0.003)


class BotFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.user = SimpleNamespace(id=501, username="student")
        self.message = FakeMessage()
        self.context = SimpleNamespace(
            application=SimpleNamespace(bot_data={
                "settings": SimpleNamespace(single_price_stars=25, pack_credits=5,
                                             pack_price_stars=100,
                                             owner_telegram_id=999),
                "db": self.db,
                "ai": FailingAI(),
            }),
            user_data={},
            bot=FakeBot(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def update(self, query=None):
        return SimpleNamespace(
            message=self.message,
            effective_message=self.message,
            effective_user=self.user,
            effective_chat=SimpleNamespace(id=99),
            callback_query=query,
        )

    async def test_first_photo_is_offered_free_and_failure_restores_trial(self) -> None:
        await handle_photo(self.update(), self.context)
        self.assertTrue(self.context.user_data["pending_photo"]["trial_offer"])
        self.assertIn("первый фоторазбор бесплатный", self.message.sent[-1][0])

        query = FakeQuery("photo:confirm")
        with self.assertLogs("app.bot", level="ERROR"):
            await photo_callback(self.update(query), self.context)

        self.assertEqual(self.db.balance(self.user.id), (True, 0))
        self.assertIn("Бесплатная попытка восстановлена", self.message.sent[-1][0])
        self.assertEqual(self.db.funnel_stats(7).answer_users, 0)

    async def test_free_photo_success_and_followup_do_not_charge_twice(self) -> None:
        self.context.application.bot_data["ai"] = SuccessfulAI()
        await handle_photo(self.update(), self.context)
        await photo_callback(self.update(FakeQuery("photo:confirm")), self.context)

        self.assertEqual(self.db.balance(self.user.id), (False, 0))
        session = self.db.photo_session(self.user.id)
        self.assertEqual(session.access_source, "trial")
        self.assertIn("answer_contexts", self.context.user_data)

        await handle_question(self.update(), self.context)
        self.assertEqual(self.db.balance(self.user.id), (False, 0))
        with self.db._connection() as connection:
            followups = connection.execute(
                "SELECT COUNT(*) FROM requests WHERE access_source='photo_followup'"
            ).fetchone()[0]
        self.assertEqual(followups, 1)

    async def test_whole_test_phrase_reuses_active_photo_session(self) -> None:
        self.context.application.bot_data["ai"] = SuccessfulAI()
        await handle_photo(self.update(), self.context)
        await photo_callback(self.update(FakeQuery("photo:confirm")), self.context)

        self.message.text = "все это тест"
        await handle_question(self.update(), self.context)

        self.assertIn("Решение для: все это тест", self.message.sent[-1][0])
        self.assertEqual(self.db.photo_session(self.user.id).last_request, "все это тест")
        self.assertEqual(self.db.balance(self.user.id), (False, 0))

    async def test_used_text_trial_keeps_paid_photo_offer(self) -> None:
        self.db.claim_access(self.user.id, self.user.username)
        await handle_photo(self.update(), self.context)
        self.assertFalse(self.context.user_data["pending_photo"]["trial_offer"])
        self.assertIn("Фоторазбор стоит 100", self.message.sent[-1][0])
        with self.db._connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_name='photo_price_shown'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    async def test_repeated_photo_cancel_is_counted_once(self) -> None:
        await handle_photo(self.update(), self.context)
        query = FakeQuery("photo:cancel")
        await photo_callback(self.update(query), self.context)
        await photo_callback(self.update(query), self.context)
        with self.db._connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_name='photo_cancelled'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    async def test_trial_used_after_offer_falls_back_to_price_without_charging_credit(self) -> None:
        await handle_photo(self.update(), self.context)
        self.db.claim_access(self.user.id, self.user.username)
        query = FakeQuery("photo:confirm")

        await photo_callback(self.update(query), self.context)

        self.assertIn("Бесплатная попытка уже использована", query.edits[-1][0])
        self.assertFalse(self.context.user_data["pending_photo"]["trial_offer"])
        self.assertEqual(self.db.balance(self.user.id), (False, 0))

    async def test_repeated_paid_confirm_charges_five_credits_only_once(self) -> None:
        self.context.application.bot_data["ai"] = SuccessfulAI()
        self.db.claim_access(self.user.id, self.user.username)
        self.db.add_payment(self.user.id, "ten-credits", 200, 10)
        await handle_photo(self.update(), self.context)
        query = FakeQuery("photo:confirm")

        await photo_callback(self.update(query), self.context)
        await photo_callback(self.update(query), self.context)

        self.assertEqual(self.db.balance(self.user.id), (False, 5))

    async def test_repeated_feedback_callback_counts_once(self) -> None:
        request_id = self.db.log_request(
            self.user.id, "trial", 1, 2, 0.0, "completed"
        )
        query = FakeQuery(f"feedback:{request_id}:positive")
        update = self.update(query)

        await feedback_callback(update, self.context)
        await feedback_callback(update, self.context)

        stats = self.db.funnel_stats(7)
        self.assertEqual(stats.feedback_positive, 1)
        self.assertIn("Отзыв уже учтён", query.answers)

    async def test_funnel_is_owner_only_and_supports_period(self) -> None:
        self.context.args = []
        await funnel(self.update(), self.context)
        self.assertIn("только владельцу", self.message.sent[-1][0])

        self.user.id = 999
        self.context.args = ["30"]
        self.db.log_event(999, "start")
        await funnel(self.update(), self.context)
        self.assertIn("последние 30 дн.", self.message.sent[-1][0])
        self.assertIn("Уникальные старты: <b>1</b>", self.message.sent[-1][0])

    async def test_funnel_csv_is_owner_only_and_privacy_safe(self) -> None:
        self.context.args = ["30"]
        await funnel_csv(self.update(), self.context)
        self.assertIn("только владельцу", self.message.sent[-1][0])

        self.user.id = 999
        self.db.log_event(777, "start")
        await funnel_csv(self.update(), self.context)

        document, kwargs = self.message.sent_documents[-1]
        content = document.input_file_content.decode("utf-8-sig")
        self.assertIn("date_utc,starts,task_submitters", content)
        self.assertNotIn("777", content)
        self.assertIn("Без Telegram ID", kwargs["caption"])

    async def test_admin_is_owner_only_and_opens_overview(self) -> None:
        await admin(self.update(), self.context)
        self.assertEqual(self.message.sent[-1][0], "Команда недоступна.")

        self.user.id = 999
        self.db.ensure_user(999, "owner")
        await admin(self.update(), self.context)
        text, kwargs = self.message.sent[-1]
        self.assertIn("Админ-панель TaskMentor", text)
        self.assertIn("Пользователи: <b>1</b>", text)
        callbacks = [
            button.callback_data
            for row in kwargs["reply_markup"].inline_keyboard for button in row
        ]
        self.assertIn("admin:allusers:0", callbacks)
        self.assertIn("admin:payments:0", callbacks)

    async def test_admin_search_and_user_mutations_are_audited(self) -> None:
        self.user.id = 999
        self.db.ensure_user(777, "target_user")

        search = FakeQuery("admin:search")
        await admin_callback(self.update(search), self.context)
        self.assertTrue(self.context.user_data["admin_search_pending"])
        self.message.text = "@target"
        await admin_or_question(self.update(), self.context)
        self.assertIn("target_user", self.message.sent[-1][0])

        credit = FakeQuery("admin:credits:777:p5")
        await admin_callback(self.update(credit), self.context)
        self.assertEqual(self.db.balance(777), (True, 5))
        self.assertIn("Кредиты: <b>5</b>", credit.edits[-1][0])

        unlimited = FakeQuery("admin:unlimited:777:1")
        await admin_callback(self.update(unlimited), self.context)
        self.assertTrue(self.db.has_unlimited_access(777))
        actions, total = self.db.admin_actions(limit=10)
        self.assertEqual(total, 2)
        self.assertEqual(actions[0].action, "unlimited_changed")

    async def test_admin_callbacks_reject_non_owner(self) -> None:
        query = FakeQuery("admin:home")
        await admin_callback(self.update(query), self.context)
        self.assertEqual(query.answers, ["Недоступно"])
        self.assertEqual(query.edits, [])

    async def test_admin_command_is_visible_only_in_owner_chat_scope(self) -> None:
        bot = FakeBot()
        application = SimpleNamespace(
            bot=bot,
            bot_data={
                "settings": SimpleNamespace(
                    owner_telegram_id=999, reactivation_days=3, reactivation_credits=3
                ),
                "db": self.db,
            },
        )
        await post_init(application)
        await post_shutdown(application)

        public_commands = [item.command for item in bot.command_sets[0][0]]
        owner_commands = [item.command for item in bot.command_sets[1][0]]
        self.assertNotIn("admin", public_commands)
        self.assertNotIn("funnel", public_commands)
        self.assertIn("admin", owner_commands)
        self.assertEqual(bot.command_sets[1][1]["scope"].chat_id, 999)

    async def test_defense_callback_is_free_and_reuses_cached_result(self) -> None:
        ai = SuccessfulAI()
        self.context.application.bot_data["ai"] = ai
        self.db.claim_access(self.user.id, self.user.username)
        request_id = self.db.log_request(
            self.user.id, "trial", 1, 2, 0.0, "completed"
        )
        self.context.user_data["answer_contexts"] = {
            str(request_id): {"task": "2 + 2", "answer": "4", "defense": None}
        }
        query = FakeQuery(f"defense:{request_id}")

        await defense_callback(self.update(query), self.context)
        await defense_callback(self.update(query), self.context)

        self.assertEqual(self.db.balance(self.user.id), (False, 0))
        self.assertEqual(ai.defense_calls, 1)
        with self.db._connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM requests WHERE access_source='defense_followup'"
            ).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
