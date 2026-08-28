from __future__ import annotations

import logging
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
    access_source: str


@dataclass(frozen=True)
class FunnelStats:
    starts: int
    task_submitters: int
    answer_users: int
    buy_users: int
    invoice_users: int
    buyers: int
    payments: int
    stars: int
    feedback_positive: int
    feedback_negative: int


@dataclass(frozen=True)
class DailyFunnelStats:
    date_utc: str
    starts: int
    task_submitters: int
    answer_users: int
    buy_users: int
    invoice_users: int
    buyers: int
    payments: int
    stars: int
    feedback_positive: int
    feedback_negative: int


@dataclass(frozen=True)
class AdminOverview:
    total_users: int
    trial_users: int
    paying_users: int
    unlimited_users: int
    completed_requests: int
    failed_requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    payments: int
    stars: int


@dataclass(frozen=True)
class AdminUser:
    telegram_id: int
    username: str | None
    trial_available: bool
    credits: int
    unlimited: bool
    completed_requests: int
    failed_requests: int
    payments: int
    stars: int
    estimated_cost_usd: float
    created_at: str


@dataclass(frozen=True)
class AdminPayment:
    charge_id: str
    telegram_id: int
    username: str | None
    stars: int
    credits: int
    created_at: str


@dataclass(frozen=True)
class AdminAction:
    admin_telegram_id: int
    action: str
    target_telegram_id: int | None
    details: str
    created_at: str


logger = logging.getLogger(__name__)


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
                    access_source TEXT NOT NULL DEFAULT 'photo_paid',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    event_name TEXT NOT NULL,
                    source TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS admin_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_telegram_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_telegram_id INTEGER,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_events_name_created
                    ON events(event_name, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_user_created
                    ON events(telegram_id, created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_events_one_feedback_per_answer
                    ON events(telegram_id, source)
                    WHERE event_name IN ('feedback_positive', 'feedback_negative');
                CREATE INDEX IF NOT EXISTS idx_admin_actions_created
                    ON admin_actions(created_at DESC);
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
            if "access_source" not in photo_columns:
                db.execute(
                    "ALTER TABLE photo_sessions ADD COLUMN access_source TEXT NOT NULL "
                    "DEFAULT 'photo_paid'"
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

    @staticmethod
    def _admin_user_from_row(row: sqlite3.Row) -> AdminUser:
        return AdminUser(
            telegram_id=int(row["telegram_id"]),
            username=str(row["username"]) if row["username"] else None,
            trial_available=not bool(row["trial_used"]),
            credits=int(row["credits"]),
            unlimited=bool(row["unlimited"]),
            completed_requests=int(row["completed_requests"]),
            failed_requests=int(row["failed_requests"]),
            payments=int(row["payments"]),
            stars=int(row["stars"]),
            estimated_cost_usd=float(row["estimated_cost_usd"]),
            created_at=str(row["created_at"]),
        )

    def admin_overview(self) -> AdminOverview:
        with self._connection() as db:
            users = db.execute(
                """SELECT COUNT(*) AS total_users,
                SUM(CASE WHEN trial_used=1 THEN 1 ELSE 0 END) AS trial_users,
                SUM(CASE WHEN unlimited=1 THEN 1 ELSE 0 END) AS unlimited_users
                FROM users"""
            ).fetchone()
            requests = db.execute(
                """SELECT
                SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_requests,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_requests,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                FROM requests"""
            ).fetchone()
            payments = db.execute(
                """SELECT COUNT(*) AS payments, COUNT(DISTINCT telegram_id) AS paying_users,
                COALESCE(SUM(stars), 0) AS stars FROM payments"""
            ).fetchone()
        return AdminOverview(
            total_users=int(users["total_users"] or 0),
            trial_users=int(users["trial_users"] or 0),
            paying_users=int(payments["paying_users"] or 0),
            unlimited_users=int(users["unlimited_users"] or 0),
            completed_requests=int(requests["completed_requests"] or 0),
            failed_requests=int(requests["failed_requests"] or 0),
            input_tokens=int(requests["input_tokens"] or 0),
            output_tokens=int(requests["output_tokens"] or 0),
            estimated_cost_usd=float(requests["estimated_cost_usd"] or 0),
            payments=int(payments["payments"] or 0),
            stars=int(payments["stars"] or 0),
        )

    def admin_users(self, query: str = "", limit: int = 5, offset: int = 0) -> tuple[list[AdminUser], int]:
        if limit <= 0 or offset < 0:
            raise ValueError("invalid pagination")
        normalized = query.strip().lstrip("@").casefold()
        where = ""
        params: list[object] = []
        if normalized:
            if normalized.isdigit():
                where = "WHERE u.telegram_id=? OR lower(COALESCE(u.username, '')) LIKE ?"
                params.extend((int(normalized), f"%{normalized}%"))
            else:
                where = "WHERE lower(COALESCE(u.username, '')) LIKE ?"
                params.append(f"%{normalized}%")
        with self._connection() as db:
            total = int(db.execute(
                f"SELECT COUNT(*) FROM users u {where}", params
            ).fetchone()[0])
            rows = db.execute(
                f"""SELECT u.telegram_id, u.username, u.trial_used, u.credits, u.unlimited,
                u.created_at,
                COALESCE(r.completed_requests, 0) AS completed_requests,
                COALESCE(r.failed_requests, 0) AS failed_requests,
                COALESCE(p.payments, 0) AS payments,
                COALESCE(p.stars, 0) AS stars,
                COALESCE(r.estimated_cost_usd, 0) AS estimated_cost_usd
                FROM users u
                LEFT JOIN (
                    SELECT telegram_id,
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_requests,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_requests,
                    SUM(estimated_cost_usd) AS estimated_cost_usd
                    FROM requests GROUP BY telegram_id
                ) r ON r.telegram_id=u.telegram_id
                LEFT JOIN (
                    SELECT telegram_id, COUNT(*) AS payments, SUM(stars) AS stars
                    FROM payments GROUP BY telegram_id
                ) p ON p.telegram_id=u.telegram_id
                {where}
                ORDER BY u.created_at DESC, u.telegram_id DESC
                LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
        return [self._admin_user_from_row(row) for row in rows], total

    def admin_user(self, telegram_id: int) -> AdminUser | None:
        with self._connection() as db:
            row = db.execute(
                """SELECT u.telegram_id, u.username, u.trial_used, u.credits, u.unlimited,
                u.created_at,
                COALESCE(r.completed_requests, 0) AS completed_requests,
                COALESCE(r.failed_requests, 0) AS failed_requests,
                COALESCE(r.estimated_cost_usd, 0) AS estimated_cost_usd,
                COALESCE(p.payments, 0) AS payments,
                COALESCE(p.stars, 0) AS stars
                FROM users u
                LEFT JOIN (
                    SELECT telegram_id,
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_requests,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_requests,
                    SUM(estimated_cost_usd) AS estimated_cost_usd
                    FROM requests GROUP BY telegram_id
                ) r ON r.telegram_id=u.telegram_id
                LEFT JOIN (
                    SELECT telegram_id, COUNT(*) AS payments, SUM(stars) AS stars
                    FROM payments GROUP BY telegram_id
                ) p ON p.telegram_id=u.telegram_id
                WHERE u.telegram_id=?""",
                (telegram_id,),
            ).fetchone()
        return self._admin_user_from_row(row) if row else None

    def admin_adjust_credits(self, admin_id: int, telegram_id: int, delta: int) -> int | None:
        if delta == 0:
            raise ValueError("delta must not be zero")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT credits FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
            if not row or int(row["credits"]) + delta < 0:
                return None
            new_balance = int(row["credits"]) + delta
            db.execute("UPDATE users SET credits=? WHERE telegram_id=?", (new_balance, telegram_id))
            db.execute(
                """INSERT INTO admin_actions
                (admin_telegram_id, action, target_telegram_id, details)
                VALUES (?, 'credits_adjusted', ?, ?)""",
                (admin_id, telegram_id, f"delta={delta}; balance={new_balance}"),
            )
            return new_balance

    def admin_set_unlimited(self, admin_id: int, telegram_id: int, enabled: bool) -> bool:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT username FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
            if not row:
                return False
            db.execute(
                "UPDATE users SET unlimited=? WHERE telegram_id=?", (int(enabled), telegram_id)
            )
            if row["username"]:
                if enabled:
                    db.execute(
                        "INSERT OR IGNORE INTO unlimited_usernames (username) VALUES (?)",
                        (row["username"],),
                    )
                else:
                    db.execute(
                        "DELETE FROM unlimited_usernames WHERE username=? COLLATE NOCASE",
                        (row["username"],),
                    )
            db.execute(
                """INSERT INTO admin_actions
                (admin_telegram_id, action, target_telegram_id, details)
                VALUES (?, 'unlimited_changed', ?, ?)""",
                (admin_id, telegram_id, f"enabled={int(enabled)}"),
            )
            return True

    def admin_reset_trial(self, admin_id: int, telegram_id: int) -> bool:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE users SET trial_used=0 WHERE telegram_id=?", (telegram_id,)
            )
            if not cursor.rowcount:
                return False
            db.execute(
                """INSERT INTO admin_actions
                (admin_telegram_id, action, target_telegram_id, details)
                VALUES (?, 'trial_reset', ?, '')""",
                (admin_id, telegram_id),
            )
            return True

    def admin_payments(self, limit: int = 5, offset: int = 0) -> tuple[list[AdminPayment], int]:
        if limit <= 0 or offset < 0:
            raise ValueError("invalid pagination")
        with self._connection() as db:
            total = int(db.execute("SELECT COUNT(*) FROM payments").fetchone()[0])
            rows = db.execute(
                """SELECT p.telegram_charge_id, p.telegram_id, u.username,
                p.stars, p.credits, p.created_at
                FROM payments p LEFT JOIN users u ON u.telegram_id=p.telegram_id
                ORDER BY p.created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [
            AdminPayment(
                str(row["telegram_charge_id"]), int(row["telegram_id"]),
                str(row["username"]) if row["username"] else None,
                int(row["stars"]), int(row["credits"]), str(row["created_at"]),
            ) for row in rows
        ], total

    def admin_actions(self, limit: int = 5, offset: int = 0) -> tuple[list[AdminAction], int]:
        if limit <= 0 or offset < 0:
            raise ValueError("invalid pagination")
        with self._connection() as db:
            total = int(db.execute("SELECT COUNT(*) FROM admin_actions").fetchone()[0])
            rows = db.execute(
                """SELECT admin_telegram_id, action, target_telegram_id, details, created_at
                FROM admin_actions ORDER BY id DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [
            AdminAction(
                int(row["admin_telegram_id"]), str(row["action"]),
                int(row["target_telegram_id"]) if row["target_telegram_id"] is not None else None,
                str(row["details"]), str(row["created_at"]),
            ) for row in rows
        ], total

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

    def claim_trial_access(self, telegram_id: int, username: str | None) -> Access:
        """Atomically consume only the shared trial, never falling back to paid credits."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO users (telegram_id, username) VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET username=COALESCE(excluded.username, users.username)""",
                (telegram_id, username),
            )
            row = db.execute(
                "SELECT trial_used, unlimited FROM users WHERE telegram_id=?", (telegram_id,)
            ).fetchone()
            if row["unlimited"]:
                return Access(True, "unlimited")
            if not row["trial_used"]:
                db.execute("UPDATE users SET trial_used=1 WHERE telegram_id=?", (telegram_id,))
                return Access(True, "trial")
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
    ) -> int:
        with self._connection() as db:
            cursor = db.execute(
                """INSERT INTO requests
                (telegram_id, access_source, input_tokens, output_tokens, estimated_cost_usd, status)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (telegram_id, source, input_tokens, output_tokens, estimated_cost_usd, status),
            )
            return int(cursor.lastrowid)

    def log_event(
        self, telegram_id: int, event_name: str, source: str | None = None,
    ) -> bool:
        """Best-effort analytics that must never break the user-facing flow."""
        try:
            with self._connection() as db:
                db.execute(
                    "INSERT INTO events (telegram_id, event_name, source) VALUES (?, ?, ?)",
                    (telegram_id, event_name, source),
                )
            return True
        except Exception:
            logger.exception("Could not log analytics event %s", event_name)
            return False

    def record_feedback(self, telegram_id: int, request_id: int, positive: bool) -> bool:
        """Record at most one positive or negative vote for a completed answer."""
        event_name = "feedback_positive" if positive else "feedback_negative"
        try:
            with self._connection() as db:
                owned_request = db.execute(
                    "SELECT 1 FROM requests WHERE id=? AND telegram_id=? AND status='completed'",
                    (request_id, telegram_id),
                ).fetchone()
                if not owned_request:
                    return False
                cursor = db.execute(
                    "INSERT OR IGNORE INTO events (telegram_id, event_name, source) "
                    "VALUES (?, ?, ?)",
                    (telegram_id, event_name, str(request_id)),
                )
                return cursor.rowcount == 1
        except Exception:
            logger.exception("Could not record feedback for request %s", request_id)
            return False

    def funnel_stats(self, days: int = 7) -> FunnelStats:
        if days not in (1, 7, 30):
            raise ValueError("days must be 1, 7, or 30")
        threshold = f"-{days} days"
        with self._connection() as db:
            event_rows = db.execute(
                """SELECT event_name, COUNT(*) AS events,
                COUNT(DISTINCT telegram_id) AS users
                FROM events WHERE created_at >= datetime('now', ?)
                GROUP BY event_name""",
                (threshold,),
            ).fetchall()
            events = {
                str(row["event_name"]): (int(row["events"]), int(row["users"]))
                for row in event_rows
            }
            task_submitters = db.execute(
                """SELECT COUNT(DISTINCT telegram_id) AS count FROM events
                WHERE event_name IN ('text_task_submitted', 'photo_submitted')
                  AND created_at >= datetime('now', ?)""",
                (threshold,),
            ).fetchone()
            payment = db.execute(
                """SELECT COUNT(DISTINCT telegram_id) AS buyers,
                COUNT(*) AS payments, COALESCE(SUM(stars), 0) AS stars
                FROM payments WHERE created_at >= datetime('now', ?)""",
                (threshold,),
            ).fetchone()
        return FunnelStats(
            starts=events.get("start", (0, 0))[1],
            task_submitters=int(task_submitters["count"]),
            answer_users=events.get("answer_completed", (0, 0))[1],
            buy_users=events.get("buy_opened", (0, 0))[1],
            invoice_users=events.get("invoice_requested", (0, 0))[1],
            buyers=int(payment["buyers"]),
            payments=int(payment["payments"]),
            stars=int(payment["stars"]),
            feedback_positive=events.get("feedback_positive", (0, 0))[0],
            feedback_negative=events.get("feedback_negative", (0, 0))[0],
        )

    def daily_funnel_stats(self, days: int = 30) -> list[DailyFunnelStats]:
        """Return privacy-safe daily aggregates, including dates with no activity."""
        if days not in (1, 7, 30):
            raise ValueError("days must be 1, 7, or 30")
        start_offset = f"-{days - 1} days"
        with self._connection() as db:
            rows = db.execute(
                """WITH RECURSIVE dates(day) AS (
                    SELECT date('now', ?)
                    UNION ALL
                    SELECT date(day, '+1 day') FROM dates WHERE day < date('now')
                ), event_daily AS (
                    SELECT date(created_at) AS day,
                    COUNT(DISTINCT CASE WHEN event_name='start' THEN telegram_id END) AS starts,
                    COUNT(DISTINCT CASE WHEN event_name IN
                        ('text_task_submitted', 'photo_submitted') THEN telegram_id END)
                        AS task_submitters,
                    COUNT(DISTINCT CASE WHEN event_name='answer_completed'
                        THEN telegram_id END) AS answer_users,
                    COUNT(DISTINCT CASE WHEN event_name='buy_opened'
                        THEN telegram_id END) AS buy_users,
                    COUNT(DISTINCT CASE WHEN event_name='invoice_requested'
                        THEN telegram_id END) AS invoice_users,
                    SUM(CASE WHEN event_name='feedback_positive' THEN 1 ELSE 0 END)
                        AS feedback_positive,
                    SUM(CASE WHEN event_name='feedback_negative' THEN 1 ELSE 0 END)
                        AS feedback_negative
                    FROM events
                    WHERE created_at >= date('now', ?)
                    GROUP BY date(created_at)
                ), payment_daily AS (
                    SELECT date(created_at) AS day,
                    COUNT(DISTINCT telegram_id) AS buyers,
                    COUNT(*) AS payments,
                    COALESCE(SUM(stars), 0) AS stars
                    FROM payments
                    WHERE created_at >= date('now', ?)
                    GROUP BY date(created_at)
                )
                SELECT dates.day,
                    COALESCE(e.starts, 0) AS starts,
                    COALESCE(e.task_submitters, 0) AS task_submitters,
                    COALESCE(e.answer_users, 0) AS answer_users,
                    COALESCE(e.buy_users, 0) AS buy_users,
                    COALESCE(e.invoice_users, 0) AS invoice_users,
                    COALESCE(p.buyers, 0) AS buyers,
                    COALESCE(p.payments, 0) AS payments,
                    COALESCE(p.stars, 0) AS stars,
                    COALESCE(e.feedback_positive, 0) AS feedback_positive,
                    COALESCE(e.feedback_negative, 0) AS feedback_negative
                FROM dates
                LEFT JOIN event_daily e ON e.day=dates.day
                LEFT JOIN payment_daily p ON p.day=dates.day
                ORDER BY dates.day""",
                (start_offset, start_offset, start_offset),
            ).fetchall()
        return [
            DailyFunnelStats(
                date_utc=str(row["day"]),
                starts=int(row["starts"]),
                task_submitters=int(row["task_submitters"]),
                answer_users=int(row["answer_users"]),
                buy_users=int(row["buy_users"]),
                invoice_users=int(row["invoice_users"]),
                buyers=int(row["buyers"]),
                payments=int(row["payments"]),
                stars=int(row["stars"]),
                feedback_positive=int(row["feedback_positive"]),
                feedback_negative=int(row["feedback_negative"]),
            )
            for row in rows
        ]

    def save_photo_session(
        self, telegram_id: int, recognized_tasks: str, access_source: str = "photo_paid",
    ) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO photo_sessions (telegram_id, recognized_tasks, access_source)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    recognized_tasks=excluded.recognized_tasks,
                    last_request='',
                    access_source=excluded.access_source,
                    created_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP""",
                (telegram_id, recognized_tasks, access_source),
            )

    def photo_session(self, telegram_id: int, max_age_hours: int = 24) -> PhotoSession | None:
        threshold = f"-{max_age_hours} hours"
        with self._connection() as db:
            row = db.execute(
                """SELECT telegram_id, recognized_tasks, last_request, created_at, updated_at,
                access_source
                FROM photo_sessions
                WHERE telegram_id=? AND updated_at >= datetime('now', ?)""",
                (telegram_id, threshold),
            ).fetchone()
            if row is None:
                db.execute("DELETE FROM photo_sessions WHERE telegram_id=?", (telegram_id,))
                return None
        return PhotoSession(
            int(row["telegram_id"]), str(row["recognized_tasks"]), str(row["last_request"]),
            str(row["created_at"]), str(row["updated_at"]), str(row["access_source"]),
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
