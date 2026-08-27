import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
