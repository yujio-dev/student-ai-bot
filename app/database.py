from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Access:
    allowed: bool
    source: str | None = None


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    trial_used INTEGER NOT NULL DEFAULT 0,
                    credits INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    access_source TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS payments (
                    telegram_charge_id TEXT PRIMARY KEY,
                    telegram_id INTEGER NOT NULL,
                    stars INTEGER NOT NULL,
                    credits INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def ensure_user(self, telegram_id: int, username: str | None) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO users (telegram_id, username) VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET username=COALESCE(excluded.username, users.username)""",
                (telegram_id, username),
            )

    def balance(self, telegram_id: int) -> tuple[bool, int]:
        self.ensure_user(telegram_id, None)
        with self._connection() as db:
            row = db.execute(
                "SELECT trial_used, credits FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
        return not bool(row["trial_used"]), int(row["credits"])

    def claim_access(self, telegram_id: int, username: str | None) -> Access:
        """Atomically consume the free trial or one paid credit."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO users (telegram_id, username) VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET username=COALESCE(excluded.username, users.username)""",
                (telegram_id, username),
            )
            row = db.execute(
                "SELECT trial_used, credits FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
            if not row["trial_used"]:
                db.execute("UPDATE users SET trial_used=1 WHERE telegram_id=?", (telegram_id,))
                return Access(True, "trial")
            if row["credits"] > 0:
                db.execute("UPDATE users SET credits=credits-1 WHERE telegram_id=?", (telegram_id,))
                return Access(True, "paid")
            return Access(False)

    def restore_access(self, telegram_id: int, source: str) -> None:
        with self._connection() as db:
            if source == "trial":
                db.execute("UPDATE users SET trial_used=0 WHERE telegram_id=?", (telegram_id,))
            elif source == "paid":
                db.execute("UPDATE users SET credits=credits+1 WHERE telegram_id=?", (telegram_id,))

    def add_payment(self, telegram_id: int, charge_id: str, stars: int, credits: int) -> bool:
        """Add credits once even if Telegram delivers the same update again."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM payments WHERE telegram_charge_id=?", (charge_id,)
            ).fetchone():
                return False
            db.execute(
                "INSERT INTO payments (telegram_charge_id, telegram_id, stars, credits) VALUES (?, ?, ?, ?)",
                (charge_id, telegram_id, stars, credits),
            )
            db.execute(
                "INSERT INTO users (telegram_id, credits) VALUES (?, ?) "
                "ON CONFLICT(telegram_id) DO UPDATE SET credits=credits+excluded.credits",
                (telegram_id, credits),
            )
            return True

    def log_request(
        self, telegram_id: int, source: str, input_tokens: int, output_tokens: int,
        estimated_cost_usd: float, status: str,
    ) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO requests
                (telegram_id, access_source, input_tokens, output_tokens, estimated_cost_usd, status)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (telegram_id, source, input_tokens, output_tokens, estimated_cost_usd, status),
            )
