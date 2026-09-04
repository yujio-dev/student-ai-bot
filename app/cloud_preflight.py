"""Read-only environment preflight: no dotenv, storage, network or secret output."""
import os
import argparse

SERVICE = "bot"
from urllib.parse import urlsplit


def issues(env, service):
    failures = []
    required = ("DATABASE_URL", "TELEGRAM_BOT_TOKEN")
    required += (("OPENAI_API_KEY", "BOT_BRIDGE_SECRET", "TELEGRAM_CLIENT_ID",
                  "TELEGRAM_CLIENT_SECRET", "TELEGRAM_REDIRECT_URI") if service == "core"
                 else ("STUDENT_OS_BRIDGE_SECRET", "STUDENT_OS_API_URL"))
    failures.extend("missing:" + name for name in required if not env.get(name, "").strip())
    if env.get("DATABASE_URL") and not env["DATABASE_URL"].startswith(("postgres://", "postgresql://")):
        failures.append("invalid:DATABASE_URL")
    secret = "BOT_BRIDGE_SECRET" if service == "core" else "STUDENT_OS_BRIDGE_SECRET"
    if env.get(secret) and len(env[secret].strip()) < 32:
        failures.append("invalid:" + secret)
    url_name = "TELEGRAM_REDIRECT_URI" if service == "core" else "STUDENT_OS_API_URL"
    if env.get(url_name):
        try:
            url = urlsplit(env[url_name])
            valid = url.scheme == "https" and bool(url.hostname) and not url.username and not url.password
            valid = valid and not url.query and not url.fragment
            if service == "core":
                valid = valid and url.path == "/api/auth/telegram/callback"
            else:
                valid = valid and url.path in {"", "/"}
            if not valid:
                failures.append("invalid:" + url_name)
        except ValueError:
            failures.append("invalid:" + url_name)
    if service == "core":
        if env.get("APP_ENV") not in {"staging", "production"}:
            failures.append("invalid:APP_ENV")
        for name in ("DEV_LOGIN_ENABLED", "DEV_ADMIN_ENABLED"):
            if env.get(name, "false").lower() != "false":
                failures.append("invalid:" + name)
        if env.get("ENTITLEMENT_SOURCE", "core") != "core":
            failures.append("invalid:ENTITLEMENT_SOURCE")
    else:
        if env.get("STUDENT_OS_BRIDGE_ENABLED", "").lower() != "true":
            failures.append("invalid:STUDENT_OS_BRIDGE_ENABLED")
        if env.get("CLOUD_POLLING_ENABLED", "false").lower() != "false":
            failures.append("unsafe:CLOUD_POLLING_ENABLED")
    return failures


def storage_probe(env):
    if env.get("CLOUD_POLLING_ENABLED", "false").lower() != "false":
        raise RuntimeError("Polling latch must remain disabled")
    # Import the deployed entrypoint without calling build/main or Telegram APIs.
    from app import cloud_worker
    from app.postgres_outbox import PostgresPaymentOutbox
    box = PostgresPaymentOutbox(env["DATABASE_URL"])
    box.pending(1)  # Discard rows; never log payment envelopes.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage", action="store_true", help="Check cloud imports and initialize/read bot outbox; never poll")
    args = parser.parse_args()
    failures = issues(os.environ, SERVICE)
    for item in failures:
        print(item)
    if not failures and args.storage:
        try:
            storage_probe(os.environ)
        except Exception:
            print("STORAGE_PREFLIGHT_FAILED_DETAILS_SUPPRESSED")
            return 1
        print("CLOUD_IMPORTS_AND_POSTGRES_OUTBOX_OK_NO_POLLING")
    else:
        print("BLOCKED_BY_DOPPLER_LOGIN_OR_CONFIG" if failures else "CONFIG_READY_NOT_RUNTIME_VERIFIED")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
