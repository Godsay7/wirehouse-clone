#!/usr/bin/env python3
"""Back up the database (run nightly by switch-inventory-backup.timer).

1. Consistent online copy of the SQLite database, integrity check, zstd.
2. Saved to BACKUP_DIR (local), then copied to BACKUP_REMOTE_DIR (network
   share) when configured.
3. Old backups are rotated in both places (daily/weekly/monthly).

Exit code 1 when anything failed, so systemd marks the run as failed. A local
backup is kept even if the network share is not available.

    python3 scripts/backup_db.py [--db PATH] [--dir DIR] [--remote-dir DIR]

Settings: SWITCH_INVENTORY_BACKUP_* environment variables (see settings.py).
"""

import argparse
import os
import sys
import time

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from Project import settings  # noqa: E402
from Project.ops import backup  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=settings.DB_PATH)
    parser.add_argument("--dir", default=settings.BACKUP_DIR)
    parser.add_argument("--remote-dir", default=settings.BACKUP_REMOTE_DIR)
    args = parser.parse_args()

    policy = backup.RetentionPolicy(
        daily=settings.BACKUP_KEEP_DAILY,
        weekly=settings.BACKUP_KEEP_WEEKLY,
        monthly=settings.BACKUP_KEEP_MONTHLY,
    )
    failed = False
    started = time.time()

    try:
        path = backup.create_backup(args.db, args.dir)
    except Exception as exc:
        print(f"ERROR: backup failed: {exc}")
        return 1

    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"Backup created: {path} ({size_mb:.1f} MB, {time.time() - started:.1f}s)")

    deleted = backup.rotate(args.dir, policy)
    print(f"Local rotation: {len(deleted)} old backup(s) deleted, "
          f"{len(backup.list_backups(args.dir))} kept in {args.dir}")

    if args.remote_dir:
        try:
            remote_path = backup.copy_to(path, args.remote_dir)
            print(f"Copied to {remote_path}")
            deleted = backup.rotate(args.remote_dir, policy)
            print(f"Remote rotation: {len(deleted)} old backup(s) deleted, "
                  f"{len(backup.list_backups(args.remote_dir))} kept in {args.remote_dir}")
        except Exception as exc:
            failed = True
            print(f"ERROR: copy to {args.remote_dir} failed: {exc}")
    else:
        print("Remote copy skipped: SWITCH_INVENTORY_BACKUP_REMOTE_DIR is not set.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
