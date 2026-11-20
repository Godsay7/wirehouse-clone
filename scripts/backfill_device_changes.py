#!/usr/bin/env python3
"""One-time: find device replacements in the existing port history.

From now on the collector records "another device on the port" by itself
(port_device_changes, shown in Cabling Check). This fills the table from the
MAC changes already in port_changes (the last RETENTION_DAYS days), with the
same rule (Project/bll/domain/cabling_check.device_replaced).

    python3 scripts/backfill_device_changes.py --dry-run   # only count
    python3 scripts/backfill_device_changes.py             # fill (if empty)
    python3 scripts/backfill_device_changes.py --force     # clear and fill again
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Project import settings  # noqa: E402
from Project.bll.domain.cabling_check import device_replaced  # noqa: E402
from Project.collector.storage import init_database  # noqa: E402


def replacements(rows):
    """rows: MAC changes (switch_id, port, old, new, if_name, at) ordered by port, then time."""

    found = []
    key, last = None, None
    for switch_id, port, old, new, if_name, at in rows:
        if (switch_id, port) != key:
            key, last = (switch_id, port), None
        if last is None and old not in (None, "", "-"):
            last = old                        # the device before the first change we know of
        if new in (None, "", "-"):
            continue                          # gone or asleep: the last device stays
        replaced = device_replaced(last, new)
        if replaced:
            found.append((switch_id, port, if_name, ", ".join(replaced[0]), ", ".join(replaced[1]), at))
        last = new
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=settings.DB_PATH)
    parser.add_argument("--dry-run", action="store_true", help="only count, change nothing")
    parser.add_argument("--force", action="store_true", help="delete the recorded changes first")
    args = parser.parse_args()

    connection = init_database(args.db)
    existing = connection.execute("SELECT COUNT(*) FROM port_device_changes").fetchone()[0]
    if existing and not args.force and not args.dry_run:
        print(f"port_device_changes already has {existing} rows; use --force to fill it again.")
        return 1

    rows = connection.execute(
        "SELECT switch_id, port, old_value, new_value, if_name, detected_at FROM port_changes "
        "WHERE change_type = 'MAC' ORDER BY switch_id, port, id"
    ).fetchall()
    found = replacements(rows)
    ports = len({(r[0], r[1]) for r in found})
    print(f"{len(rows)} MAC changes read: {len(found)} device replacements on {ports} ports.")
    if args.dry_run:
        return 0

    with connection:
        if args.force:
            connection.execute("DELETE FROM port_device_changes")
        connection.executemany(
            "INSERT INTO port_device_changes (switch_id, port, if_name, old_macs, new_macs, detected_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            found,
        )
    print("Saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
