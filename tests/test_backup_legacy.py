import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts.backup_legacy import create, verify


class BackupLegacyTest(unittest.TestCase):
    def test_online_backup_includes_ledger_and_outbox_and_verifies_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = root / "student.db"
            outbox = root / "core_payment_outbox.db"
            with closing(sqlite3.connect(ledger)) as database:
                database.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
                database.execute("INSERT INTO users(name) VALUES ('Әлия')")
                database.commit()
            with closing(sqlite3.connect(outbox)) as database:
                database.execute("CREATE TABLE payment_outbox(charge_id TEXT PRIMARY KEY)")
                database.execute("INSERT INTO payment_outbox VALUES ('synthetic')")
                database.commit()
            destination = root / "backup"
            with patch.dict("os.environ", {"DATABASE_PATH": str(ledger)}, clear=False):
                manifest = create(destination)
            self.assertEqual({item["name"] for item in manifest["files"]},
                             {"legacy-ledger.db", "core-payment-outbox.db"})
            self.assertEqual(len(verify(destination)["files"]), 2)
            self.assertEqual(json.loads((destination / "manifest.json").read_text())["files"],
                             manifest["files"])

    def test_tampered_backup_fails_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = root / "student.db"
            with closing(sqlite3.connect(ledger)) as database:
                database.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
                database.commit()
            destination = root / "backup"
            with patch.dict("os.environ", {"DATABASE_PATH": str(ledger)}, clear=False):
                create(destination)
            with (destination / "legacy-ledger.db").open("ab") as target:
                target.write(b"tamper")
            with self.assertRaisesRegex(RuntimeError, "verification failed"):
                verify(destination)


if __name__ == "__main__":
    unittest.main()
