#!/usr/bin/env python3

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Project.core.text import format_datetime  # noqa: E402


# ============================================================
# Configuration
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DB = os.path.join(
    SCRIPT_DIR,
    "switch_inventory.db"
)


# ============================================================
# Database
# ============================================================

def connect_db(db_path):
    if not os.path.exists(db_path):
        print(f"ERROR: SQLite database не найдена: {db_path}")
        sys.exit(1)

    try:
        conn = sqlite3.connect(db_path)
        conn.create_function("local_time", 1, format_datetime)
        conn.row_factory = sqlite3.Row
        return conn

    except sqlite3.Error as exc:
        print(f"ERROR: Не удалось открыть SQLite: {exc}")
        sys.exit(1)


# ============================================================
# Table formatting
# ============================================================

def print_table(headers, rows):

    if not rows:
        print("Нет данных.")
        return

    # Convert everything to strings
    rows = [
        ["" if value is None else str(value) for value in row]
        for row in rows
    ]

    headers = [
        str(header)
        for header in headers
    ]

    widths = []

    for index, header in enumerate(headers):

        width = len(header)

        for row in rows:
            width = max(
                width,
                len(row[index])
            )

        widths.append(width)

    separator = (
        "+"
        + "+".join(
            "-" * (width + 2)
            for width in widths
        )
        + "+"
    )

    print(separator)

    print(
        "| "
        + " | ".join(
            headers[index].ljust(widths[index])
            for index in range(len(headers))
        )
        + " |"
    )

    print(separator)

    for row in rows:

        print(
            "| "
            + " | ".join(
                row[index].ljust(widths[index])
                for index in range(len(headers))
            )
            + " |"
        )

    print(separator)


# ============================================================
# Arguments
# ============================================================

def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "View current switch inventory from SQLite."
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
        help="Show only specified switch host"
    )

    parser.add_argument(
        "--down",
        action="store_true",
        help="Show only DOWN ports"
    )

    parser.add_argument(
        "--up",
        action="store_true",
        help="Show only UP ports"
    )

    parser.add_argument(
        "--mac",
        help="Search by MAC address"
    )

    parser.add_argument(
        "--device",
        help="Search by Device / Description"
    )

    return parser.parse_args()


# ============================================================
# Main
# ============================================================

def main():

    args = parse_arguments()

    if args.up and args.down:
        print(
            "ERROR: Нельзя одновременно использовать "
            "--up и --down."
        )
        sys.exit(1)

    conn = connect_db(
        args.db
    )

    cursor = conn.cursor()

    # ========================================================
    # Build query
    # ========================================================

    query = """
        SELECT
            switches.host,
            ports.port,
            ports.device,
            ports.speed,
            ports.link,
            ports.mac,
            local_time(ports.last_seen) AS last_seen
        FROM ports
        INNER JOIN switches
            ON switches.id = ports.switch_id
        WHERE 1=1
    """

    parameters = []

    # --------------------------------------------------------
    # Switch
    # --------------------------------------------------------

    if args.switch:

        query += """
            AND switches.host = ?
        """

        parameters.append(
            args.switch
        )

    # --------------------------------------------------------
    # Link
    # --------------------------------------------------------

    if args.down:

        query += """
            AND ports.link = 'DOWN'
        """

    if args.up:

        query += """
            AND ports.link = 'UP'
        """

    # --------------------------------------------------------
    # MAC
    # --------------------------------------------------------

    if args.mac:

        query += """
            AND LOWER(ports.mac) = LOWER(?)
        """

        parameters.append(
            args.mac.strip()
        )

    # --------------------------------------------------------
    # Device
    # --------------------------------------------------------

    if args.device:

        query += """
            AND LOWER(ports.device) LIKE LOWER(?)
        """

        parameters.append(
            f"%{args.device.strip()}%"
        )

    # --------------------------------------------------------
    # Order
    # --------------------------------------------------------

    query += """
        ORDER BY
            switches.host,
            ports.port
    """

    try:

        cursor.execute(
            query,
            parameters
        )

        records = cursor.fetchall()

    except sqlite3.Error as exc:

        print(
            f"ERROR: SQLite query error: {exc}"
        )

        conn.close()
        sys.exit(1)

    # ========================================================
    # Nothing found
    # ========================================================

    if not records:

        print()
        print(
            "Нет данных по заданному условию."
        )

        conn.close()
        return

    # ========================================================
    # Display
    # ========================================================

    current_switch = None

    total_ports = 0

    for record in records:

        host = record["host"]

        if host != current_switch:

            current_switch = host

            print()
            print("=" * 75)
            print(
                f"Switch: {host}"
            )
            print("=" * 75)

            print_table(
                [
                    "Port",
                    "Device",
                    "Speed",
                    "Link",
                    "MAC",
                ],
                [
                    [
                        r["port"],
                        r["device"] or "-",
                        r["speed"] or "-",
                        r["link"] or "-",
                        r["mac"] or "-",
                    ]
                    for r in records
                    if r["host"] == host
                ]
            )

        total_ports += 1

    # ========================================================
    # Summary
    # ========================================================

    print()
    print(
        f"Total ports: {total_ports}"
    )

    # --------------------------------------------------------
    # Number of switches
    # --------------------------------------------------------

    switches = len(
        set(
            record["host"]
            for record in records
        )
    )

    print(
        f"Total switches: {switches}"
    )

    conn.close()


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()
