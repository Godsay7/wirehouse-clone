#!/usr/bin/env python3
"""Restore the database from a backup made by scripts/backup_db.py.

    python3 scripts/restore_db.py --list
    python3 scripts/restore_db.py BACKUP_FILE [--db PATH] [--yes]

Before restoring, the current database is backed up into the same backup
directory (so a wrong restore can be undone). The web app and the collector
can keep running: they see the restored data on their next query. Data
version counters are moved forward so open pages refresh themselves.
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from Project import settings  # noqa: E402
from Project.core.text import now_iso  # noqa: E402
from Project.ops import backup  # noqa: E402


def read_versions(database_path):
    connection = sqlite3.connect(database_path, timeout=60)
    try:
        return dict(connection.execute("SELECT key, value FROM app_state").fetchall())
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def move_versions_forward(database_path, before):
    connection = sqlite3.connect(database_path, timeout=60)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0, updated_at TEXT)"
        )
        restored = dict(connection.execute("SELECT key, value FROM app_state").fetchall())
        for key in {"inventory", "rack"} | set(before) | set(restored):
            value = max(int(before.get(key) or 0), int(restored.get(key) or 0)) + 1
            connection.execute(
                """
                INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now_iso()),
            )
        connection.commit()
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("backup_file", nargs="?")
    parser.add_argument("--db", default=settings.DB_PATH)
    parser.add_argument("--dir", default=settings.BACKUP_DIR, help="where --list looks and the safety copy goes")
    parser.add_argument("--list", action="store_true", help="list available backups")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    if args.list or not args.backup_file:
        for timestamp, path in backup.list_backups(args.dir):
            print(f"{timestamp:%Y-%m-%d %H:%M:%S}  {os.path.getsize(path) / 1024 / 1024:6.1f} MB  {path}")
        return 0

    if not os.path.exists(args.backup_file):
        print(f"ERROR: {args.backup_file} not found")
        return 1

    if not args.yes:
        answer = input(f"Replace ALL data in {args.db} with {args.backup_file}? [yes/NO] ")
        if answer.strip().lower() != "yes":
            print("Cancelled.")
            return 1

    if os.path.exists(args.db):
        safety_copy = backup.create_backup(args.db, args.dir)
        print(f"Current database saved first: {safety_copy}")

    before = read_versions(args.db)
    backup.restore_backup(args.backup_file, args.db)
    move_versions_forward(args.db, before)

    print(f"Restored {args.db} from {args.backup_file}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
