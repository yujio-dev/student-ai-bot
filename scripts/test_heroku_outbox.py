"""Managed URL in memory only; tests own disposable schemas, never public data."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    result = subprocess.run([r"C:\Program Files\heroku\bin\heroku.cmd", "config:get",
        "DATABASE_URL", "--app", "student-os-ernar-beta"], capture_output=True, text=True, timeout=30)
    if result.returncode or not result.stdout.strip().startswith(("postgres://", "postgresql://")):
        print("Managed PostgreSQL unavailable; values suppressed")
        return 1
    environment = os.environ.copy()
    environment["BOT_OUTBOX_TEST_URL"] = result.stdout.strip()
    result = None
    return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
        "-p", "test_outbox_persistence.py", "-v"], cwd=Path(__file__).resolve().parents[1], env=environment).returncode


if __name__ == "__main__":
    raise SystemExit(main())
