#!/usr/bin/env python3
"""Remove repeated port_history rows left by the old "full snapshot every
5 minutes" collector.

A row is redundant when the previous row of the same switch port has the
same device, speed, link, MAC, ifIndex and ifName. The first row of every
port and every row with a change are kept, so no information is lost and
port_changes keeps pointing to existing rows. Safe to run more than once.

    python3 scripts/compact_port_history.py [--db PATH]

Afterwards the file keeps its size (freed pages are reused); run VACUUM
to shrink it (see README).
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

REDUNDANT_IDS_QUERY = """
    SELECT id
    FROM (
        SELECT
            id,
            LAG(id) OVER w AS previous_id,
            COALESCE(device, '') = COALESCE(LAG(device) OVER w, '')
            AND COALESCE(speed, '') = COALESCE(LAG(speed) OVER w, '')
            AND COALESCE(link, '') = COALESCE(LAG(link) OVER w, '')
            AND COALESCE(mac, '') = COALESCE(LAG(mac) OVER w, '')
            AND COALESCE(if_index, '') = COALESCE(LAG(if_index) OVER w, '')
            AND COALESCE(if_name, '') = COALESCE(LAG(if_name) OVER w, '') AS same
        FROM port_history
        WINDOW w AS (PARTITION BY switch_id, port ORDER BY collected_at, id)
    )
    WHERE previous_id IS NOT NULL AND same
"""

BATCH_SIZE = 20000


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=settings.DB_PATH)
    args = parser.parse_args()

    database = Database(args.db)
    started = time.time()

    # The slow scan only reads; deletes run in short transactions.
    with database.read() as uow:
        total = uow.connection.execute("SELECT COUNT(*) FROM port_history").fetchone()[0]
        redundant = [row[0] for row in uow.connection.execute(REDUNDANT_IDS_QUERY)]

    print(
        f"port_history rows: {total}; redundant: {len(redundant)} "
        f"({time.time() - started:.1f}s)"
    )

    for start in range(0, len(redundant), BATCH_SIZE):
        batch = redundant[start:start + BATCH_SIZE]
        with database.write() as uow:
            uow.connection.executemany(
                "DELETE FROM port_history WHERE id = ?",
                ((row_id,) for row_id in batch),
            )

    print(
        f"Deleted {len(redundant)} rows, {total - len(redundant)} left "
        f"({time.time() - started:.1f}s)."
    )


if __name__ == "__main__":
    main()
