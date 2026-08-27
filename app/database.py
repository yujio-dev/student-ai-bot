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
    credits_charged: int = 0


@dataclass(frozen=True)
class PaymentResult:
    added: bool
    rewarded_referrer_id: int | None = None


@dataclass(frozen=True)
class ReferralStats:
    code: str
    kind: str
    label: str
    joins: int
    buyers: int
    payments: int
    stars: int


@dataclass(frozen=True)
class PhotoSession:
    telegram_id: int
    recognized_tasks: str
    last_request: str
    created_at: str
    updated_at: str


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
                    unlimited INTEGER NOT NULL DEFAULT 0,
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
                CREATE TABLE IF NOT EXISTS referral_codes (
                    code TEXT PRIMARY KEY,
                    owner_telegram_id INTEGER,
                    kind TEXT NOT NULL CHECK(kind IN ('credit', 'cash')),
                    label TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS referrals (
                    referred_telegram_id INTEGER PRIMARY KEY,
                    code TEXT NOT NULL,
                    referrer_telegram_id INTEGER,
                    reward_granted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(code) REFERENCES referral_codes(code)
                );
                CREATE TABLE IF NOT EXISTS unlimited_usernames (
                    username TEXT PRIMARY KEY COLLATE NOCASE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS photo_sessions (
                    telegram_id INTEGER PRIMARY KEY,
                    recognized_tasks TEXT NOT NULL,
                    last_request TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
            if "unlimited" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN unlimited INTEGER NOT NULL DEFAULT 0")
            if "reactivation_granted_at" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN reactivation_granted_at TEXT")
            photo_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(photo_sessions)")
            }
            if "last_request" not in photo_columns:
                db.execute(
                    "ALTER TABLE photo_sessions ADD COLUMN last_request TEXT NOT NULL DEFAULT ''"
                )

    def ensure_user(self, telegram_id: int, username: str | None) -> bool:
        """Create or refresh a user and return True only for a new account."""
        with self._connection() as db:
            is_new = db.execute(
                "SELECT 1 FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone() is None
            db.execute(
                """INSERT INTO users (telegram_id, username) VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET username=COALESCE(excluded.username, users.username)""",
                (telegram_id, username),
            )
            if username and db.execute(
                "SELECT 1 FROM unlimited_usernames WHERE username=? COLLATE NOCASE",
                (username.lstrip("@"),),
            ).fetchone():
                db.execute(
                    "UPDATE users SET unlimited=1 WHERE telegram_id=?", (telegram_id,)
                )
            return is_new

    def balance(self, telegram_id: int) -> tuple[bool, int]:
        self.ensure_user(telegram_id, None)
        with self._connection() as db:
            row = db.execute(
                "SELECT trial_used, credits FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
        return not bool(row["trial_used"]), int(row["credits"])

    def has_unlimited_access(self, telegram_id: int) -> bool:
        self.ensure_user(telegram_id, None)
        with self._connection() as db:
            row = db.execute(
                "SELECT unlimited FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
        return bool(row["unlimited"])

    def set_unlimited_by_username(self, username: str, enabled: bool = True) -> int:
        normalized = username.lstrip("@")
        with self._connection() as db:
            if enabled:
                db.execute(
                    "INSERT OR IGNORE INTO unlimited_usernames (username) VALUES (?)",
                    (normalized,),
                )
            else:
                db.execute(
                    "DELETE FROM unlimited_usernames WHERE username=? COLLATE NOCASE",
                    (normalized,),
                )
            cursor = db.execute(
                "UPDATE users SET unlimited=? WHERE lower(username)=lower(?)",
                (int(enabled), normalized),
            )
            return cursor.rowcount

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
                "SELECT trial_used, credits, unlimited FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
            if row["unlimited"]:
                return Access(True, "unlimited")
            if not row["trial_used"]:
                db.execute("UPDATE users SET trial_used=1 WHERE telegram_id=?", (telegram_id,))
                return Access(True, "trial")
            if row["credits"] > 0:
                db.execute("UPDATE users SET credits=credits-1 WHERE telegram_id=?", (telegram_id,))
                return Access(True, "paid", 1)
            return Access(False)

    def claim_paid_credits(
        self, telegram_id: int, username: str | None, credits: int, source: str
    ) -> Access:
        """Atomically consume several paid credits without using the free trial."""
        if credits <= 0:
            raise ValueError("credits must be greater than zero")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO users (telegram_id, username) VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET username=COALESCE(excluded.username, users.username)""",
                (telegram_id, username),
            )
            row = db.execute(
                "SELECT credits, unlimited FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
            if row["unlimited"]:
                return Access(True, "unlimited")
            if row["credits"] >= credits:
                db.execute(
                    "UPDATE users SET credits=credits-? WHERE telegram_id=?",
                    (credits, telegram_id),
                )
                return Access(True, source, credits)
            return Access(False)

    def restore_access(self, telegram_id: int, source: str, credits_charged: int = 0) -> None:
        with self._connection() as db:
            if source == "trial":
                db.execute("UPDATE users SET trial_used=0 WHERE telegram_id=?", (telegram_id,))
            else:
                refund_credits = credits_charged or (1 if source == "paid" else 0)
                if refund_credits <= 0:
                    return
                db.execute(
                    "UPDATE users SET credits=credits+? WHERE telegram_id=?",
                    (refund_credits, telegram_id),
                )

    def personal_referral_code(self, telegram_id: int, username: str | None) -> str:
        self.ensure_user(telegram_id, username)
        with self._connection() as db:
            existing = db.execute(
                "SELECT code FROM referral_codes WHERE owner_telegram_id=? AND kind='credit'",
                (telegram_id,),
            ).fetchone()
            if existing:
                return str(existing["code"])
            code = f"U{telegram_id:X}"
            db.execute(
                "INSERT INTO referral_codes (code, owner_telegram_id, kind, label) VALUES (?, ?, 'credit', ?)",
                (code, telegram_id, username or str(telegram_id)),
            )
            return code

    def create_cash_referral(self, code: str, label: str) -> bool:
        with self._connection() as db:
            existing = db.execute(
                "SELECT kind FROM referral_codes WHERE code=?", (code,)
            ).fetchone()
            if existing:
                return existing["kind"] == "cash"
            db.execute(
                "INSERT INTO referral_codes (code, kind, label) VALUES (?, 'cash', ?)",
                (code, label),
            )
            return True

    def attach_referral(self, telegram_id: int, code: str) -> bool:
        """Apply first-touch attribution once and reject self-referrals."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            referral = db.execute(
                "SELECT owner_telegram_id FROM referral_codes WHERE code=? AND active=1",
                (code,),
            ).fetchone()
            if not referral or referral["owner_telegram_id"] == telegram_id:
                return False
            cursor = db.execute(
                """INSERT OR IGNORE INTO referrals
                (referred_telegram_id, code, referrer_telegram_id) VALUES (?, ?, ?)""",
                (telegram_id, code, referral["owner_telegram_id"]),
            )
            return cursor.rowcount == 1

    def referral_stats(self, owner_telegram_id: int | None = None) -> list[ReferralStats]:
        where = "WHERE rc.owner_telegram_id=?" if owner_telegram_id is not None else ""
        params = (owner_telegram_id,) if owner_telegram_id is not None else ()
        with self._connection() as db:
            rows = db.execute(
                f"""SELECT rc.code, rc.kind, rc.label,
                COUNT(DISTINCT r.referred_telegram_id) AS joins,
                COUNT(DISTINCT CASE WHEN p.telegram_id IS NOT NULL THEN r.referred_telegram_id END) AS buyers,
                COUNT(p.telegram_charge_id) AS payments,
                COALESCE(SUM(p.stars), 0) AS stars
                FROM referral_codes rc
                LEFT JOIN referrals r ON r.code=rc.code
                LEFT JOIN payments p ON p.telegram_id=r.referred_telegram_id
                {where}
                GROUP BY rc.code, rc.kind, rc.label
                ORDER BY rc.created_at""",
                params,
            ).fetchall()
        return [
            ReferralStats(
                str(row["code"]), str(row["kind"]), str(row["label"]),
                int(row["joins"]), int(row["buyers"]), int(row["payments"]), int(row["stars"]),
            )
            for row in rows
        ]

    def reactivation_candidates(self, inactive_days: int) -> list[int]:
        """Users who completed only their trial, never paid, and then went inactive."""
        threshold = f"-{inactive_days} days"
        with self._connection() as db:
            rows = db.execute(
                """SELECT u.telegram_id
                FROM users u
                WHERE u.trial_used=1
                  AND u.credits=0
                  AND u.unlimited=0
                  AND u.reactivation_granted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM payments p WHERE p.telegram_id=u.telegram_id
                  )
                  AND 1 = (
                      SELECT COUNT(*) FROM requests r
                      WHERE r.telegram_id=u.telegram_id
                        AND r.status='completed' AND r.access_source='trial'
                  )
                  AND (
                      SELECT MAX(r.created_at) FROM requests r
                      WHERE r.telegram_id=u.telegram_id
                        AND r.status='completed' AND r.access_source='trial'
                  ) <= datetime('now', ?)""",
                (threshold,),
            ).fetchall()
        return [int(row["telegram_id"]) for row in rows]

    def grant_reactivation_bonus(self, telegram_id: int, credits: int) -> bool:
        with self._connection() as db:
            cursor = db.execute(
                """UPDATE users
                SET credits=credits+?, reactivation_granted_at=CURRENT_TIMESTAMP
                WHERE telegram_id=? AND reactivation_granted_at IS NULL
                  AND unlimited=0""",
                (credits, telegram_id),
            )
            return cursor.rowcount == 1

    def add_payment(
        self, telegram_id: int, charge_id: str, stars: int, credits: int,
        referral_reward_credits: int = 1,
    ) -> PaymentResult:
        """Add credits once even if Telegram delivers the same update again."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM payments WHERE telegram_charge_id=?", (charge_id,)
            ).fetchone():
                return PaymentResult(False)
            db.execute(
                "INSERT INTO payments (telegram_charge_id, telegram_id, stars, credits) VALUES (?, ?, ?, ?)",
                (charge_id, telegram_id, stars, credits),
            )
            db.execute(
                "INSERT INTO users (telegram_id, credits) VALUES (?, ?) "
                "ON CONFLICT(telegram_id) DO UPDATE SET credits=credits+excluded.credits",
                (telegram_id, credits),
            )
            referral = db.execute(
                """SELECT r.referrer_telegram_id, r.reward_granted, rc.kind
                FROM referrals r JOIN referral_codes rc ON rc.code=r.code
                WHERE r.referred_telegram_id=?""",
                (telegram_id,),
            ).fetchone()
            rewarded_referrer_id = None
            if (referral and referral["kind"] == "credit" and not referral["reward_granted"]
                    and referral["referrer_telegram_id"] is not None):
                rewarded_referrer_id = int(referral["referrer_telegram_id"])
                db.execute(
                    "UPDATE users SET credits=credits+? WHERE telegram_id=?",
                    (referral_reward_credits, rewarded_referrer_id),
                )
                db.execute(
                    "UPDATE referrals SET reward_granted=1 WHERE referred_telegram_id=?",
                    (telegram_id,),
                )
            return PaymentResult(True, rewarded_referrer_id)

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

    def save_photo_session(self, telegram_id: int, recognized_tasks: str) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO photo_sessions (telegram_id, recognized_tasks)
                VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    recognized_tasks=excluded.recognized_tasks,
                    last_request='',
                    created_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP""",
                (telegram_id, recognized_tasks),
            )

    def photo_session(self, telegram_id: int, max_age_hours: int = 24) -> PhotoSession | None:
        threshold = f"-{max_age_hours} hours"
        with self._connection() as db:
            row = db.execute(
                """SELECT telegram_id, recognized_tasks, last_request, created_at, updated_at
                FROM photo_sessions
                WHERE telegram_id=? AND updated_at >= datetime('now', ?)""",
                (telegram_id, threshold),
            ).fetchone()
            if row is None:
                db.execute("DELETE FROM photo_sessions WHERE telegram_id=?", (telegram_id,))
                return None
        return PhotoSession(
            int(row["telegram_id"]), str(row["recognized_tasks"]), str(row["last_request"]),
            str(row["created_at"]), str(row["updated_at"]),
        )

    def touch_photo_session(self, telegram_id: int, last_request: str = "") -> None:
        with self._connection() as db:
            db.execute(
                """UPDATE photo_sessions
                SET last_request=?, updated_at=CURRENT_TIMESTAMP WHERE telegram_id=?""",
                (last_request, telegram_id),
            )

    def clear_photo_session(self, telegram_id: int) -> bool:
        with self._connection() as db:
            cursor = db.execute("DELETE FROM photo_sessions WHERE telegram_id=?", (telegram_id,))
            return cursor.rowcount == 1

    def solved_tasks_count(self) -> int:
        """Return the number of successfully completed task solutions."""
        with self._connection() as db:
            row = db.execute(
                """SELECT COUNT(*) AS count FROM requests
                WHERE status='completed'
                  AND access_source IN (
                      'trial', 'paid', 'photo_paid', 'photo_followup', 'unlimited'
                  )"""
            ).fetchone()
        return int(row["count"])
