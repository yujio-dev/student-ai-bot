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
        self.assertTrue(self.db.add_payment(1, "charge-1", 100, 5))
        self.assertFalse(self.db.add_payment(1, "charge-1", 100, 5))
        self.assertEqual(self.db.balance(1), (False, 5))
        self.assertEqual(self.db.claim_access(1, "student").source, "paid")
        self.assertEqual(self.db.balance(1), (False, 4))

    def test_failed_request_restores_trial(self) -> None:
        access = self.db.claim_access(2, None)
        self.db.restore_access(2, access.source)
        self.assertEqual(self.db.balance(2), (True, 0))

    def test_solved_tasks_count_only_includes_completed_solutions(self) -> None:
        self.db.log_request(1, "trial", 10, 20, 0.01, "completed")
        self.db.log_request(2, "paid", 10, 20, 0.01, "completed")
        self.db.log_request(3, "free_chat", 10, 20, 0.01, "completed")
        self.db.log_request(4, "trial", 0, 0, 0, "failed")
        self.assertEqual(self.db.solved_tasks_count(), 2)


if __name__ == "__main__":
    unittest.main()
