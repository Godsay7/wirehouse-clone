#!/usr/bin/env python3
"""Fill port_changes with changes that happened before it existed.

The collector records new changes in port_changes on every poll. This script
derives the older ones from port_history (a slow query over the whole table)
and inserts only changes older than the first recorded one, so it is safe to
run more than once.

    python3 scripts/backfill_port_changes.py [--db PATH]
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
from Project.dal import Database  # noqa: E402
from Project.dal.schema import ensure_inventory_schema  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=settings.DB_PATH)
    args = parser.parse_args()

    database = Database(args.db)

    connection = database.connect()
    try:
        ensure_inventory_schema(connection)
    finally:
        connection.close()

    started = time.time()

    # Read first (no write lock is held while the slow query runs).
    with database.read() as uow:
        before = uow.history.earliest_recorded_change()
        rows = uow.history.changes_from_history(before=before)

    print(
        f"Changes found in port_history"
        f"{' before ' + before if before else ''}: {len(rows)} "
        f"({time.time() - started:.1f}s)"
    )

    if not rows:
        return

    with database.write() as uow:
        # Another run may have filled the table meanwhile.
        if uow.history.earliest_recorded_change() != before:
            print("port_changes changed during the scan; run the script again.")
            return

        uow.history.insert_backfilled_changes(rows)

    print(f"Inserted {len(rows)} changes into port_changes.")


if __name__ == "__main__":
    main()
