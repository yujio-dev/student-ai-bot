import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.database import Database


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_trial_then_payment_credits(self) -> None:
        first = self.db.claim_access(1, "student")
        self.assertEqual((first.allowed, first.source), (True, "trial"))
        self.assertFalse(self.db.claim_access(1, "student").allowed)
        self.assertTrue(self.db.add_payment(1, "charge-1", 100, 5).added)
        self.assertFalse(self.db.add_payment(1, "charge-1", 100, 5).added)
        self.assertEqual(self.db.balance(1), (False, 5))
        self.assertEqual(self.db.claim_access(1, "student").source, "paid")
        self.assertEqual(self.db.balance(1), (False, 4))

    def test_failed_request_restores_trial(self) -> None:
        access = self.db.claim_access(2, None)
        self.db.restore_access(2, access.source)
        self.assertEqual(self.db.balance(2), (True, 0))

    def test_photo_can_atomically_claim_and_restore_shared_trial(self) -> None:
        access = self.db.claim_trial_access(52, "photo_trial")
        self.assertEqual((access.allowed, access.source), (True, "trial"))
        self.assertEqual(self.db.balance(52), (False, 0))
        self.db.restore_access(52, access.source)
        self.assertEqual(self.db.balance(52), (True, 0))

    def test_text_trial_prevents_second_free_photo_trial(self) -> None:
        self.assertEqual(self.db.claim_access(53, None).source, "trial")
        self.assertFalse(self.db.claim_trial_access(53, None).allowed)

    def test_photo_trial_prevents_second_free_text_trial(self) -> None:
        self.assertEqual(self.db.claim_trial_access(54, None).source, "trial")
        self.assertFalse(self.db.claim_access(54, None).allowed)

    def test_concurrent_photo_trial_claim_has_single_winner(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as executor:
            claims = list(executor.map(
                lambda _: self.db.claim_trial_access(55, None), range(8)
            ))
        self.assertEqual(sum(access.allowed for access in claims), 1)
        self.assertEqual(self.db.balance(55), (False, 0))

    def test_photo_claim_requires_and_restores_five_paid_credits(self) -> None:
        self.db.ensure_user(50, "photographer")
        self.assertFalse(
            self.db.claim_paid_credits(50, "photographer", 5, "photo_paid").allowed
        )
        self.assertEqual(self.db.balance(50), (True, 0))
        self.db.add_payment(50, "photo-pack", 100, 5)
        access = self.db.claim_paid_credits(50, "photographer", 5, "photo_paid")
        self.assertEqual(
            (access.allowed, access.source, access.credits_charged),
            (True, "photo_paid", 5),
        )
        self.assertEqual(self.db.balance(50), (True, 0))
        self.db.restore_access(50, access.source, access.credits_charged)
        self.assertEqual(self.db.balance(50), (True, 5))

    def test_photo_claim_does_not_consume_free_trial(self) -> None:
        self.db.add_payment(51, "partial-photo-pack", 25, 1)
        self.assertFalse(self.db.claim_paid_credits(51, None, 5, "photo_paid").allowed)
        self.assertEqual(self.db.balance(51), (True, 1))

    def test_unlimited_access_does_not_consume_trial_or_credits(self) -> None:
        self.db.ensure_user(3, "owner")
        self.assertEqual(self.db.set_unlimited_by_username("@owner"), 1)
        for _ in range(10):
            self.assertEqual(self.db.claim_access(3, "owner").source, "unlimited")
        self.assertTrue(self.db.has_unlimited_access(3))
        self.assertEqual(self.db.balance(3), (True, 0))

    def test_unlimited_username_applies_on_first_start(self) -> None:
        self.assertEqual(self.db.set_unlimited_by_username("@future_user"), 0)
        self.db.ensure_user(99, "future_user")
        self.assertTrue(self.db.has_unlimited_access(99))
        self.assertEqual(self.db.claim_access(99, "future_user").source, "unlimited")

    def test_solved_tasks_count_only_includes_completed_solutions(self) -> None:
        self.db.log_request(1, "trial", 10, 20, 0.01, "completed")
        self.db.log_request(2, "paid", 10, 20, 0.01, "completed")
        self.db.log_request(3, "free_chat", 10, 20, 0.01, "completed")
        self.db.log_request(4, "trial", 0, 0, 0, "failed")
        self.assertEqual(self.db.solved_tasks_count(), 2)

    def test_credit_referral_rewards_only_first_purchase(self) -> None:
        code = self.db.personal_referral_code(10, "referrer")
        self.db.ensure_user(11, "friend")
        self.assertTrue(self.db.attach_referral(11, code))
        self.assertFalse(self.db.attach_referral(11, code))
        first = self.db.add_payment(11, "friend-charge-1", 25, 1)
        second = self.db.add_payment(11, "friend-charge-2", 100, 5)
        self.assertEqual(first.rewarded_referrer_id, 10)
        self.assertIsNone(second.rewarded_referrer_id)
        self.assertEqual(self.db.balance(10), (True, 1))
        stats = self.db.referral_stats(10)[0]
        self.assertEqual((stats.joins, stats.buyers, stats.payments, stats.stars), (1, 1, 2, 125))

    def test_cash_referral_tracks_without_automatic_reward(self) -> None:
        self.assertTrue(self.db.create_cash_referral("P_ALINA", "Алина, 3 курс"))
        self.db.ensure_user(21, "buyer")
        self.assertTrue(self.db.attach_referral(21, "P_ALINA"))
        result = self.db.add_payment(21, "cash-charge", 100, 5)
        self.assertIsNone(result.rewarded_referrer_id)
        stats = [item for item in self.db.referral_stats() if item.code == "P_ALINA"][0]
        self.assertEqual((stats.joins, stats.buyers, stats.payments, stats.stars), (1, 1, 1, 100))

    def test_self_referral_is_rejected(self) -> None:
        code = self.db.personal_referral_code(30, "self")
        self.assertFalse(self.db.attach_referral(30, code))

    def test_reactivation_bonus_is_granted_once_after_inactivity(self) -> None:
        access = self.db.claim_access(40, "inactive")
        self.db.log_request(40, access.source, 10, 20, 0.01, "completed")
        with self.db._connection() as connection:
            connection.execute(
                "UPDATE requests SET created_at=datetime('now', '-4 days') WHERE telegram_id=40"
            )
        self.assertEqual(self.db.reactivation_candidates(3), [40])
        self.assertTrue(self.db.grant_reactivation_bonus(40, 3))
        self.assertFalse(self.db.grant_reactivation_bonus(40, 3))
        self.assertEqual(self.db.balance(40), (False, 3))
        self.assertEqual(self.db.reactivation_candidates(3), [])

    def test_paying_user_does_not_receive_reactivation_bonus(self) -> None:
        access = self.db.claim_access(41, "buyer")
        self.db.log_request(41, access.source, 10, 20, 0.01, "completed")
        self.db.add_payment(41, "paid-before-reactivation", 25, 1)
        with self.db._connection() as connection:
            connection.execute(
                "UPDATE users SET credits=0 WHERE telegram_id=41"
            )
            connection.execute(
                "UPDATE requests SET created_at=datetime('now', '-4 days') WHERE telegram_id=41"
            )
        self.assertNotIn(41, self.db.reactivation_candidates(3))

    def test_photo_session_is_saved_replaced_and_cleared(self) -> None:
        self.db.save_photo_session(60, "Задача 1", "trial")
        session = self.db.photo_session(60)
        self.assertIsNotNone(session)
        self.assertEqual(session.recognized_tasks, "Задача 1")
        self.assertEqual(session.access_source, "trial")

        self.db.save_photo_session(60, "Задача 2")
        self.assertEqual(self.db.photo_session(60).recognized_tasks, "Задача 2")
        self.db.touch_photo_session(60, "Реши задачу 2")
        self.assertEqual(self.db.photo_session(60).last_request, "Реши задачу 2")
        self.assertTrue(self.db.clear_photo_session(60))
        self.assertIsNone(self.db.photo_session(60))

    def test_expired_photo_session_is_removed(self) -> None:
        self.db.save_photo_session(61, "Старое фото")
        with self.db._connection() as connection:
            connection.execute(
                "UPDATE photo_sessions SET updated_at=datetime('now', '-25 hours') "
                "WHERE telegram_id=61"
            )
        self.assertIsNone(self.db.photo_session(61, max_age_hours=24))

    def test_photo_followups_count_as_completed_solutions(self) -> None:
        self.db.log_request(62, "photo_setup", 10, 20, 0.01, "completed")
        self.db.log_request(62, "photo_followup", 10, 20, 0.01, "completed")
        self.assertEqual(self.db.solved_tasks_count(), 1)

    def test_events_and_funnel_are_aggregated_without_personal_data(self) -> None:
        for telegram_id in (101, 102):
            self.db.log_event(telegram_id, "start")
        self.db.log_event(101, "start")
        self.db.log_event(101, "text_task_submitted")
        self.db.log_event(102, "photo_submitted")
        self.db.log_event(101, "answer_completed")
        self.db.log_event(101, "buy_opened")
        self.db.log_event(101, "invoice_requested", "1")
        self.db.add_payment(101, "funnel-payment-1", 25, 1)
        self.db.add_payment(101, "funnel-payment-2", 100, 5)
        request_id = self.db.log_request(101, "trial", 1, 2, 0.0, "completed")
        self.assertTrue(self.db.record_feedback(101, request_id, positive=True))

        stats = self.db.funnel_stats(7)
        self.assertEqual(
            (stats.starts, stats.task_submitters, stats.answer_users, stats.buy_users),
            (2, 2, 1, 1),
        )
        self.assertEqual(
            (stats.invoice_users, stats.buyers, stats.payments, stats.stars),
            (1, 1, 2, 125),
        )
        self.assertEqual((stats.feedback_positive, stats.feedback_negative), (1, 0))

    def test_empty_funnel_returns_zeros(self) -> None:
        stats = self.db.funnel_stats(1)
        self.assertEqual(sum(stats.__dict__.values()), 0)
        with self.assertRaises(ValueError):
            self.db.funnel_stats(2)

    def test_daily_funnel_includes_zero_days_and_no_personal_data(self) -> None:
        self.db.log_event(101, "start")
        self.db.log_event(101, "text_task_submitted")
        self.db.add_payment(101, "daily-payment", 25, 1)

        rows = self.db.daily_funnel_stats(7)

        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[-1].starts, 1)
        self.assertEqual(rows[-1].task_submitters, 1)
        self.assertEqual(rows[-1].stars, 25)
        self.assertEqual(sum(row.starts for row in rows[:-1]), 0)
        self.assertNotIn("telegram_id", rows[-1].__dict__)
        with self.assertRaises(ValueError):
            self.db.daily_funnel_stats(2)

    def test_feedback_is_counted_once_per_answer_even_if_polarity_changes(self) -> None:
        request_id = self.db.log_request(70, "trial", 1, 2, 0.0, "completed")
        self.assertTrue(self.db.record_feedback(70, request_id, positive=True))
        self.assertFalse(self.db.record_feedback(70, request_id, positive=True))
        self.assertFalse(self.db.record_feedback(70, request_id, positive=False))
        stats = self.db.funnel_stats(7)
        self.assertEqual((stats.feedback_positive, stats.feedback_negative), (1, 0))

    def test_analytics_failure_is_non_fatal(self) -> None:
        original_connect = self.db._connect
        self.db._connect = lambda: (_ for _ in ()).throw(sqlite3.OperationalError("test"))
        try:
            with self.assertLogs("app.database", level="ERROR"):
                self.assertFalse(self.db.log_event(1, "start"))
        finally:
            self.db._connect = original_connect

    def test_admin_overview_and_user_search(self) -> None:
        self.db.ensure_user(101, "Alice")
        self.db.ensure_user(202, "bob")
        self.db.claim_access(101, "Alice")
        self.db.log_request(101, "trial", 100, 50, 0.002, "completed")
        self.db.log_request(202, "paid", 10, 5, 0.001, "failed")
        self.db.add_payment(101, "pay-1", 25, 1)
        self.db.add_payment(101, "pay-2", 100, 5)

        overview = self.db.admin_overview()
        self.assertEqual(overview.total_users, 2)
        self.assertEqual(overview.paying_users, 1)
        self.assertEqual(overview.payments, 2)
        self.assertEqual(overview.stars, 125)
        self.assertEqual(overview.completed_requests, 1)
        self.assertAlmostEqual(overview.estimated_cost_usd, 0.003)

        users, total = self.db.admin_users("ali")
        self.assertEqual(total, 1)
        self.assertEqual(users[0].telegram_id, 101)
        self.assertEqual(users[0].payments, 2)
        self.assertEqual(users[0].stars, 125)
        self.assertAlmostEqual(users[0].estimated_cost_usd, 0.002)
        self.assertEqual(self.db.admin_user(101).username, "Alice")

    def test_admin_credit_unlimited_trial_and_audit_are_atomic(self) -> None:
        self.db.ensure_user(303, "managed")
        self.db.claim_access(303, "managed")

        self.assertEqual(self.db.admin_adjust_credits(999, 303, 5), 5)
        self.assertIsNone(self.db.admin_adjust_credits(999, 303, -6))
        self.assertEqual(self.db.balance(303), (False, 5))
        self.assertTrue(self.db.admin_set_unlimited(999, 303, True))
        self.assertTrue(self.db.has_unlimited_access(303))
        self.assertTrue(self.db.admin_reset_trial(999, 303))
        self.assertEqual(self.db.balance(303), (True, 5))

        actions, total = self.db.admin_actions(limit=10)
        self.assertEqual(total, 3)
        self.assertEqual(actions[0].action, "trial_reset")
        self.assertEqual(actions[-1].details, "delta=5; balance=5")

    def test_admin_payments_are_paginated_newest_first(self) -> None:
        self.db.ensure_user(404, "buyer")
        for index in range(7):
            self.db.add_payment(404, f"charge-{index}", 25, 1)
        with self.db._connection() as connection:
            connection.execute(
                "UPDATE payments SET created_at=datetime('now', '+' || rowid || ' seconds')"
            )

        first, total = self.db.admin_payments(limit=5, offset=0)
        second, _ = self.db.admin_payments(limit=5, offset=5)
        self.assertEqual(total, 7)
        self.assertEqual(len(first), 5)
        self.assertEqual(len(second), 2)
        self.assertEqual(first[0].charge_id, "charge-6")

    def test_legacy_database_migration_preserves_records(self) -> None:
        legacy_path = Path(self.temp.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.executescript(
            """
            CREATE TABLE users (
                telegram_id INTEGER PRIMARY KEY, username TEXT,
                trial_used INTEGER NOT NULL DEFAULT 0,
                credits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE photo_sessions (
                telegram_id INTEGER PRIMARY KEY,
                recognized_tasks TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO users (telegram_id, username, trial_used, credits)
            VALUES (900, 'legacy', 1, 4);
            INSERT INTO photo_sessions (telegram_id, recognized_tasks)
            VALUES (900, 'Старая задача');
            """
        )
        connection.commit()
        connection.close()

        migrated = Database(legacy_path)
        self.assertEqual(migrated.balance(900), (False, 4))
        session = migrated.photo_session(900)
        self.assertEqual(session.recognized_tasks, "Старая задача")
        self.assertEqual(session.last_request, "")
        self.assertEqual(session.access_source, "photo_paid")
        self.assertTrue(migrated.log_event(900, "start"))


if __name__ == "__main__":
    unittest.main()
