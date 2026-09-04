"""Owner-authorized synthetic acceptance against the two fixed beta apps.

Never starts polling, contacts Telegram, changes DNS/config, or prints credentials.
Retains its uniquely labelled synthetic identity/payment as persistence evidence.
Only --exercise writes synthetic records and restarts the Core web process.
"""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.bridge_client import StudentOSBridgeClient
from app.postgres_outbox import PostgresPaymentOutbox
import psycopg

HEROKU = r"C:\Program Files\heroku\bin\heroku.cmd"
CORE = "student-os-ernar-beta"
BOT = "student-ai-bot-ernar-beta"
ORIGIN = "https://student-os-ernar-beta-5b340330d3f4.herokuapp.com"


def command(*args):
    result = subprocess.run([HEROKU, *args], capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError("Heroku command failed")
    return result.stdout


def request_status(secret, *, mode):
    path = "/api/internal/v1/products"
    body = b"{}" if mode != "oversized" else b"x" * 70000
    timestamp = str(int(time.time()) - (600 if mode == "stale" else 0))
    nonce = secrets.token_urlsafe(24)
    signed_path = path if mode != "endpoint" else "/api/internal/v1/entitlement"
    message = b"v2.POST." + signed_path.encode() + b"." + timestamp.encode() + b"." + nonce.encode() + b"." + body
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    if mode == "malformed":
        signature = "invalid"
    headers = {"Content-Type":"application/json", "X-Bridge-Timestamp":timestamp,
               "X-Bridge-Nonce":nonce, "X-Bridge-Signature":signature}
    if mode == "missing":
        headers = {"Content-Type":"application/json"}
    req = urllib.request.Request(ORIGIN + path, data=body, headers=headers)
    def send():
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
    if mode == "replay":
        assert send() == 200
    return send()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exercise", action="store_true")
    args = parser.parse_args()
    stage = "config"
    try:
        core = json.loads(command("config", "--json", "--app", CORE))
        bot = json.loads(command("config", "--json", "--app", BOT))
        assert core["APP_ENV"] == "production"
        assert core["DEV_LOGIN_ENABLED"] == core["DEV_ADMIN_ENABLED"] == "false"
        assert bot["CLOUD_POLLING_ENABLED"] == "false"
        assert bot["STUDENT_OS_API_URL"].rstrip("/") == ORIGIN
        assert core["BOT_BRIDGE_SECRET"] == bot["STUDENT_OS_BRIDGE_SECRET"]
        assert core["DATABASE_URL"] == bot["DATABASE_URL"]
        assert core.get("SENTRY_DSN") and bot.get("SENTRY_DSN")
        print("CONFIG_BOUNDARIES_PASS", flush=True)
        client = StudentOSBridgeClient(ORIGIN, bot["STUDENT_OS_BRIDGE_SECRET"])
        stage = "signed_health_catalog"
        assert client.health()["status"] == "ready"
        assert client.get_products()["products"]
        print("SIGNED_HEALTH_CATALOG_PASS", flush=True)
        for mode in ("missing", "stale", "endpoint", "malformed", "replay", "oversized"):
            stage = "auth_" + mode
            status = request_status(bot["STUDENT_OS_BRIDGE_SECRET"], mode=mode)
            assert status == (413 if mode == "oversized" else 401), status
            print(stage.upper() + "_PASS", flush=True)
        if not args.exercise:
            return 0
        stage = "synthetic_identity"
        run_id = uuid.uuid4().hex
        telegram = {"telegram_user_id": 8000000000000000 + secrets.randbelow(100000000000000),
                    "display_name":"SYNTHETIC cloud acceptance " + run_id}
        identity = client.resolve_user(telegram)
        user_id = identity["user"]["id"]
        def snapshot():
            with psycopg.connect(core["DATABASE_URL"], sslmode="require", connect_timeout=15) as db:
                migrations = db.execute("SELECT version,checksum,applied_at FROM schema_migrations ORDER BY version").fetchall()
                stored = db.execute("SELECT id FROM users WHERE id=%s", (user_id,)).fetchone()
                return migrations, stored
        before = snapshot()
        assert before[0] and before[1] == (user_id,)
        stage = "payment_lost_response"
        payload = {"telegram":telegram, "charge_id":"synthetic-cloud-" + run_id,
                   "product_id":"task_help_1_v1", "stars_paid":25}
        box = PostgresPaymentOutbox(bot["DATABASE_URL"])
        box.enqueue(payload)
        class LostResponse:
            def record_payment(self, request):
                client.record_payment(request)
                raise ConnectionResetError("Synthetic lost response")
        assert not box.deliver(LostResponse(), box.get(payload["charge_id"]))
        assert box.get(payload["charge_id"])["delivery_state"] == "pending"
        box = PostgresPaymentOutbox(bot["DATABASE_URL"])
        assert box.deliver(client, box.get(payload["charge_id"]))
        assert box.get(payload["charge_id"])["delivery_state"] == "delivered"
        def credit_proof():
            with psycopg.connect(core["DATABASE_URL"], sslmode="require", connect_timeout=15) as db:
                assert db.execute("SELECT COUNT(*) FROM telegram_star_payments WHERE telegram_payment_charge_id=%s", (payload["charge_id"],)).fetchone()[0] == 1
                assert db.execute("SELECT balance FROM ai_entitlements WHERE user_id=%s", (user_id,)).fetchone()[0] == 1
        credit_proof()
        print("LOST_RESPONSE_DURABLE_RETRY_EXACTLY_ONCE_PASS", flush=True)
        print("SYNTHETIC_EVIDENCE " + run_id, flush=True)
        stage = "core_restart_persistence"
        command("ps:restart", "web", "--app", CORE)
        ready = False
        for attempt in range(8):
            try:
                assert client.health()["status"] == "ready"
                ready = True
                break
            except Exception:
                time.sleep(min(attempt + 1, 5))
        assert ready
        assert client.resolve_user(telegram)["user"]["id"] == user_id
        assert client.get_entitlement(telegram)["entitlement"]["balance"] == 1
        assert client.get_products()["products"]
        assert client.record_payment(payload)["entitlement"]["balance"] == 1
        assert snapshot() == before
        credit_proof()
        print("PROCESS_RESTART_PERSISTENCE_MIGRATION_IDEMPOTENCY_PASS", flush=True)
        print("POST_RESTART_CATALOG_ENTITLEMENT_DUPLICATE_PAYMENT_PASS", flush=True)
        return 0
    except Exception:
        print("ACCEPTANCE_FAILED stage=" + stage, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
