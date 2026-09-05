"""Consistent, verifiable cutover backup for local SQLite ledger and outbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity(path: Path) -> bool:
    with closing(sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro", uri=True)) as database:
        return database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(
            f"file:{source.as_posix()}?mode=ro", uri=True)) as src, \
         closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
    if not integrity(destination):
        raise RuntimeError("Backup integrity verification failed")


def create(output: Path) -> dict:
    load_dotenv(ROOT / ".env", override=False)
    configured = Path(os.getenv("DATABASE_PATH", "data/student_ai_bot.db"))
    ledger = configured if configured.is_absolute() else ROOT / configured
    sources = [("legacy-ledger.db", ledger),
               ("core-payment-outbox.db", ledger.with_name("core_payment_outbox.db"))]
    if not ledger.is_file():
        raise RuntimeError("Legacy database was not found")
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for name, source in sources:
        if not source.is_file():
            continue
        destination = output / name
        snapshot(source.resolve(), destination)
        files.append({"name": name, "bytes": destination.stat().st_size,
                      "sha256": sha256(destination), "integrity": "ok"})
    manifest = {"created_at": datetime.now(UTC).isoformat(), "files": files}
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def verify(output: Path) -> dict:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest.get("files", []):
        path = output / item["name"]
        if (not path.is_file() or sha256(path) != item["sha256"]
                or not integrity(path)):
            raise RuntimeError("Backup verification failed")
    if not manifest.get("files"):
        raise RuntimeError("Backup contains no database files")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify:
        result = verify(args.verify.resolve())
        print(f"BACKUP_VERIFIED files={len(result['files'])}")
        return 0
    output = args.output or ROOT / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result = create(output.resolve())
    print(f"BACKUP_CREATED files={len(result['files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
