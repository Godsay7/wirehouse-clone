#!/usr/bin/env python3

import argparse
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Project.core.text import format_datetime  # noqa: E402


# ============================================================
# Configuration
# ============================================================

SCRIPT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DEFAULT_DB = os.path.join(
    SCRIPT_DIR,
    "switch_inventory.db"
)


# ============================================================
# Database
# ============================================================

def connect_db(db_path):

    if not os.path.exists(db_path):

        print(
            f"ERROR: SQLite database не найдена: {db_path}"
        )

        sys.exit(1)

    try:

        conn = sqlite3.connect(
            db_path
        )

        conn.row_factory = sqlite3.Row

        return conn

    except sqlite3.Error as exc:

        print(
            f"ERROR: Не удалось открыть SQLite: {exc}"
        )

        sys.exit(1)


# ============================================================
# Arguments
# ============================================================

def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "Compare two latest switch inventory "
            "snapshots from SQLite."
        )
    )

    parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=(
            f"SQLite database "
            f"(default: {DEFAULT_DB})"
        )
    )

    parser.add_argument(
        "--switch",
        help="Show changes only for specified switch"
    )

    return parser.parse_args()


# ============================================================
# Get collection timestamps
# ============================================================

def get_collection_times(
    conn,
    switch_id=None
):

    cursor = conn.cursor()

    if switch_id is None:

        cursor.execute(
            """
            SELECT DISTINCT collected_at
            FROM port_history
            ORDER BY collected_at DESC
            LIMIT 2
            """
        )

    else:

        cursor.execute(
            """
            SELECT DISTINCT collected_at
            FROM port_history
            WHERE switch_id = ?
            ORDER BY collected_at DESC
            LIMIT 2
            """,
            (
                switch_id,
            )
        )

    return [
        row[0]
        for row in cursor.fetchall()
    ]


# ============================================================
# Load snapshot
# ============================================================

def load_snapshot(
    conn,
    collected_at,
    switch_id=None
):

    cursor = conn.cursor()

    # port_history stores a row only when a port changes, so the state at
    # ``collected_at`` is the latest row of every port up to that moment.
    switch_filter = ""

    parameters = [
        collected_at
    ]

    if switch_id is not None:

        switch_filter = """
            AND switch_id = ?
        """

        parameters.append(
            switch_id
        )

    query = f"""
        SELECT
            h.switch_id,
            h.port,
            h.device,
            h.speed,
            h.link,
            h.mac,
            h.if_index,
            h.if_name,
            h.collected_at
        FROM port_history h
        JOIN (
            SELECT MAX(id) AS id
            FROM port_history
            WHERE collected_at <= ?
            {switch_filter}
            GROUP BY switch_id, port
        ) latest
            ON latest.id = h.id
    """

    cursor.execute(
        query,
        parameters
    )

    records = cursor.fetchall()

    result = {}

    for record in records:

        key = (
            record["switch_id"],
            record["port"]
        )

        result[key] = dict(record)

    return result


# ============================================================
# Switch hosts
# ============================================================

def get_switch_hosts(conn):

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            host
        FROM switches
        ORDER BY host
        """
    )

    return {
        row["id"]: row["host"]
        for row in cursor.fetchall()
    }


# ============================================================
# Value helper
# ============================================================

def normalize(value):

    if value is None:
        return "-"

    value = str(value).strip()

    if not value:
        return "-"

    return value


# ============================================================
# Compare
# ============================================================

def compare_snapshots(
    old_snapshot,
    new_snapshot
):

    changes = []

    all_keys = set(
        old_snapshot.keys()
    ) | set(
        new_snapshot.keys()
    )

    for key in sorted(
        all_keys,
        key=lambda item: (
            item[0],
            item[1]
        )
    ):

        old = old_snapshot.get(
            key
        )

        new = new_snapshot.get(
            key
        )

        # ----------------------------------------------------
        # New port
        # ----------------------------------------------------

        if old is None:

            changes.append(
                {
                    "type": "NEW_PORT",
                    "switch_id": key[0],
                    "port": key[1],
                    "old": None,
                    "new": new,
                }
            )

            continue

        # ----------------------------------------------------
        # Removed port
        # ----------------------------------------------------

        if new is None:

            changes.append(
                {
                    "type": "REMOVED_PORT",
                    "switch_id": key[0],
                    "port": key[1],
                    "old": old,
                    "new": None,
                }
            )

            continue

        # ----------------------------------------------------
        # Device
        # ----------------------------------------------------

        old_device = normalize(
            old["device"]
        )

        new_device = normalize(
            new["device"]
        )

        if old_device != new_device:

            changes.append(
                {
                    "type": "DEVICE",
                    "switch_id": key[0],
                    "port": key[1],
                    "old_value": old_device,
                    "new_value": new_device,
                    "old": old,
                    "new": new,
                }
            )

        # ----------------------------------------------------
        # Speed
        # ----------------------------------------------------

        old_speed = normalize(
            old["speed"]
        )

        new_speed = normalize(
            new["speed"]
        )

        if old_speed != new_speed:

            changes.append(
                {
                    "type": "SPEED",
                    "switch_id": key[0],
                    "port": key[1],
                    "old_value": old_speed,
                    "new_value": new_speed,
                    "old": old,
                    "new": new,
                }
            )

        # ----------------------------------------------------
        # Link
        # ----------------------------------------------------

        old_link = normalize(
            old["link"]
        )

        new_link = normalize(
            new["link"]
        )

        if old_link != new_link:

            changes.append(
                {
                    "type": "LINK",
                    "switch_id": key[0],
                    "port": key[1],
                    "old_value": old_link,
                    "new_value": new_link,
                    "old": old,
                    "new": new,
                }
            )

        # ----------------------------------------------------
        # MAC
        # ----------------------------------------------------

        old_mac = normalize(
            old["mac"]
        )

        new_mac = normalize(
            new["mac"]
        )

        if old_mac != new_mac:

            changes.append(
                {
                    "type": "MAC",
                    "switch_id": key[0],
                    "port": key[1],
                    "old_value": old_mac,
                    "new_value": new_mac,
                    "old": old,
                    "new": new,
                }
            )

    return changes


# ============================================================
# Print changes
# ============================================================

def print_changes(
    changes,
    hosts
):

    if not changes:

        print()
        print(
            "No changes detected."
        )

        return

    # ========================================================
    # Group by switch
    # ========================================================

    grouped = defaultdict(
        list
    )

    for change in changes:

        grouped[
            change["switch_id"]
        ].append(
            change
        )

    # ========================================================
    # Display
    # ========================================================

    for switch_id in sorted(
        grouped.keys()
    ):

        host = hosts.get(
            switch_id,
            f"switch_id={switch_id}"
        )

        print()
        print(
            "=" * 75
        )

        print(
            f"Switch: {host}"
        )

        print(
            "=" * 75
        )

        for change in grouped[
            switch_id
        ]:

            port = change["port"]

            change_type = change["type"]

            # ------------------------------------------------
            # New port
            # ------------------------------------------------

            if change_type == "NEW_PORT":

                new = change["new"]

                print(
                    f"[NEW PORT] Port {port}"
                )

                print(
                    f"  Device: {normalize(new['device'])}"
                )

                print(
                    f"  Speed:  {normalize(new['speed'])}"
                )

                print(
                    f"  Link:   {normalize(new['link'])}"
                )

                print(
                    f"  MAC:    {normalize(new['mac'])}"
                )

                print()

                continue

            # ------------------------------------------------
            # Removed port
            # ------------------------------------------------

            if change_type == "REMOVED_PORT":

                old = change["old"]

                print(
                    f"[REMOVED PORT] Port {port}"
                )

                print(
                    f"  Device: {normalize(old['device'])}"
                )

                print(
                    f"  Speed:  {normalize(old['speed'])}"
                )

                print(
                    f"  Link:   {normalize(old['link'])}"
                )

                print(
                    f"  MAC:    {normalize(old['mac'])}"
                )

                print()

                continue

            # ------------------------------------------------
            # Normal change
            # ------------------------------------------------

            labels = {
                "DEVICE": "Device",
                "SPEED": "Speed",
                "LINK": "Link",
                "MAC": "MAC",
            }

            label = labels.get(
                change_type,
                change_type
            )

            print(
                f"[CHANGE] Port {port} - {label}"
            )

            print(
                f"  {change['old_value']} "
                f"-> "
                f"{change['new_value']}"
            )

            print()

    print()
    print(
        f"Total changes: {len(changes)}"
    )


# ============================================================
# Main
# ============================================================

def main():

    args = parse_arguments()

    conn = connect_db(
        args.db
    )

    hosts = get_switch_hosts(
        conn
    )

    # ========================================================
    # Determine switch
    # ========================================================

    switch_id = None

    if args.switch:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id
            FROM switches
            WHERE host = ?
            """,
            (
                args.switch,
            )
        )

        row = cursor.fetchone()

        if row is None:

            print(
                f"ERROR: Switch не найден в БД: "
                f"{args.switch}"
            )

            conn.close()

            sys.exit(1)

        switch_id = row["id"]

    # ========================================================
    # Get snapshots
    # ========================================================

    times = get_collection_times(
        conn,
        switch_id
    )

    if len(times) < 2:

        print()
        print(
            "Недостаточно данных для сравнения."
        )

        print(
            "Необходимо минимум два запуска collector.py."
        )

        conn.close()

        return

    newest = times[0]
    previous = times[1]

    print()
    print(
        "=" * 75
    )

    print(
        "SWITCH INVENTORY CHANGES"
    )

    print(
        "=" * 75
    )

    print(
        f"Previous: {format_datetime(previous)}"
    )

    print(
        f"Current:  {format_datetime(newest)}"
    )

    print(
        "=" * 75
    )

    # ========================================================
    # Load snapshots
    # ========================================================

    old_snapshot = load_snapshot(
        conn,
        previous,
        switch_id
    )

    new_snapshot = load_snapshot(
        conn,
        newest,
        switch_id
    )

    # ========================================================
    # Compare
    # ========================================================

    changes = compare_snapshots(
        old_snapshot,
        new_snapshot
    )

    # ========================================================
    # Print
    # ========================================================

    print_changes(
        changes,
        hosts
    )

    conn.close()


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()
