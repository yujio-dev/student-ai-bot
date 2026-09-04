"""Bot-owned persistence only. No Core business tables or ledger writes.

Delivery is at-least-once: concurrent requests may reach Core, whose charge-id
uniqueness is the authoritative exactly-once business boundary. Transactions never
span HTTP calls; a crash before marking delivered leaves a retryable record.
"""
from contextlib import contextmanager
import re
import threading
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.payment_outbox import PaymentOutbox


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, statement, parameters=()):
        if statement == "BEGIN IMMEDIATE":
            statement = "SELECT 1"
        # Only the fixed outbox SQL contract uses this adapter; payloads stay bound.
        return self.raw.execute(statement.replace("?", "%s"), parameters)


class PostgresPaymentOutbox(PaymentOutbox):
    def __init__(self, url, *, schema="bot_outbox"):
        if not url.startswith(("postgres://", "postgresql://")):
            raise ValueError("PostgreSQL outbox URL required")
        if schema != "bot_outbox" and not re.fullmatch(r"test_[a-f0-9]{32}", schema):
            raise ValueError("Invalid outbox schema")
        self._url, self.schema = url, schema
        self._slots = threading.BoundedSemaphore(2)
        with self._connect(initialize=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS payment_outbox (
                charge_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                created_at BIGINT NOT NULL, delivery_state TEXT NOT NULL DEFAULT 'pending'
                    CHECK(delivery_state IN ('pending','delivered')),
                attempts INTEGER NOT NULL DEFAULT 0, last_attempt_at BIGINT,
                last_error TEXT, delivered_at BIGINT)""")
            db.execute("CREATE INDEX IF NOT EXISTS outbox_pending ON payment_outbox(delivery_state,last_attempt_at)")

    @contextmanager
    def _connect(self, initialize=False):
        if not self._slots.acquire(timeout=10):
            raise RuntimeError("Outbox busy; delivery not acknowledged")
        try:
            with psycopg.connect(self._url, connect_timeout=10, autocommit=True,
                    sslmode="disable" if urlsplit(self._url).hostname in {"localhost","127.0.0.1","::1"} else "require",
                    row_factory=dict_row) as connection:
                with connection.transaction():
                    connection.execute("SET LOCAL statement_timeout='15s'; SET LOCAL lock_timeout='10s'; SELECT pg_advisory_xact_lock(734923402)", prepare=False)
                    if initialize:
                        connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                    connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.schema)))
                    yield Connection(connection)
        except psycopg.Error:
            # Driver diagnostics can contain connection details or payment payloads.
            raise RuntimeError("Outbox storage unavailable; delivery not acknowledged") from None
        finally:
            self._slots.release()
