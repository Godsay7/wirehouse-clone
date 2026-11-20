#!/usr/bin/env python3
"""Convert stored timestamps from local time to UTC (one-time migration).

Before this migration timestamps were local time without an offset
("2026-10-14T17:45:59"). Now they are UTC with an offset
("2026-10-14T14:45:59+00:00"). Only values without an offset are converted,
so the script is safe to run more than once and while the collector runs.

    python3 scripts/migrate_timestamps_to_utc.py [--db PATH]
    python3 scripts/migrate_timestamps_to_utc.py --to-local     # undo

Local time is interpreted in SWITCH_INVENTORY_TIMEZONE (Europe/Kyiv).
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from Project import settings  # noqa: E402
from Project.core.text import display_timezone  # noqa: E402

TIMESTAMP_COLUMNS = {
    "switches": ["last_seen"],
    "ports": ["last_seen"],
    "port_history": ["collected_at"],
    "port_changes": ["detected_at"],
    "arp_entries": ["first_seen", "last_seen"],
    "app_state": ["updated_at"],
    "server_rooms": ["created_at"],
    "racks": ["created_at"],
    "rack_view_order": ["updated_at"],
    "servers": ["created_at"],
    "rack_switch_placeholders": ["created_at"],
    "patch_panels": ["created_at"],
    "cable_organizers": ["created_at"],
    "port_connections": ["created_at", "updated_at"],
    "patch_connections": ["created_at", "updated_at"],
}

LOCAL_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
UTC_SUFFIX = "+00:00"


def local_to_utc(value):
    if value is None or not LOCAL_PATTERN.match(value):
        return value
    local = datetime.fromisoformat(value).replace(tzinfo=display_timezone())
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def utc_to_local(value):
    if value is None or not str(value).endswith(UTC_SUFFIX):
        return value
    local = datetime.fromisoformat(value).astimezone(display_timezone())
    return local.replace(tzinfo=None).isoformat(timespec="seconds")


def existing_columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info([{table}])")}


def migrate(connection, convert, only_where):
    """Convert every timestamp column; returns {table.column: rows changed}."""

    connection.create_function("convert_ts", 1, convert, deterministic=True)
    changed = {}

    for table, columns in TIMESTAMP_COLUMNS.items():
        present = existing_columns(connection, table)

        for column in columns:
            if column not in present:
                continue

            cursor = connection.execute(
                f"UPDATE [{table}] SET [{column}] = convert_ts([{column}]) "
                f"WHERE [{column}] IS NOT NULL AND {only_where.format(column=f'[{column}]')}"
            )
            changed[f"{table}.{column}"] = cursor.rowcount

        # One table per transaction: short write locks for the collector/web.
        connection.commit()

    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=settings.DB_PATH)
    parser.add_argument("--to-local", action="store_true", help="undo: UTC back to local time")
    args = parser.parse_args()

    connection = sqlite3.connect(args.db, timeout=60)

    try:
        if args.to_local:
            changed = migrate(connection, utc_to_local, f"{{column}} LIKE '%{UTC_SUFFIX}'")
        else:
            changed = migrate(connection, local_to_utc, f"{{column}} NOT LIKE '%+%' AND {{column}} NOT LIKE '%Z'")
    finally:
        connection.close()

    direction = "local time" if args.to_local else "UTC"
    for name, count in changed.items():
        if count:
            print(f"{name}: {count} value(s) converted to {direction}")
    print(f"Done: {sum(changed.values())} value(s) in {len(changed)} column(s); timezone {settings.TIMEZONE}.")


if __name__ == "__main__":
    main()
