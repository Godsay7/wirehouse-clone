"""Collector command line: poll every switch from the YAML config into SQLite.

Run through scripts/collector.py (switch-inventory.service, every 5 minutes).
"""

import argparse
import json
import sqlite3
import sys

from .. import settings
from ..core.text import now_iso
from ..dal.repositories.state import StateRepository
from .arp import save_core_arp_snapshot
from .config import load_config
from .identity import collect_switch_identity
from .neighbors import collect_neighbors
from .ports import collect_switch
from .report import build_json_result, print_table, write_csv
from .retention import prune_old_records
from .storage import init_database, save_neighbors_to_database, save_switch_to_database

DEFAULT_CONFIG = settings.CONFIG_PATH
DEFAULT_DATABASE = settings.DB_PATH


def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "Universal SNMP switch inventory "
            "collector for Dell OS10, Cisco "
            "and MikroTik."
        )
    )

    parser.add_argument(
        "--yaml",
        "--config",
        dest="config",
        default=DEFAULT_CONFIG,
        help=(
            "Path to YAML config "
            f"(default: {DEFAULT_CONFIG})"
        )
    )

    parser.add_argument(
        "--db",
        default=DEFAULT_DATABASE,
        help=(
            "SQLite database file "
            f"(default: {DEFAULT_DATABASE})"
        )
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON"
    )

    parser.add_argument(
        "--csv",
        nargs="?",
        const="switch_inventory.csv",
        metavar="FILE",
        help=(
            "Save result as CSV. "
            "Default: switch_inventory.csv"
        )
    )

    return parser.parse_args()

def main():

    args = parse_arguments()

    # --------------------------------------------------------
    # Load YAML
    # --------------------------------------------------------

    try:

        community, switches, arp_sources = load_config(
            args.config
        )

    except RuntimeError as exc:

        print(
            f"ERROR: {exc}"
        )

        sys.exit(1)

    # --------------------------------------------------------
    # SQLite
    # --------------------------------------------------------

    try:

        connection = init_database(
            args.db
        )

    except sqlite3.Error as exc:

        print(
            f"ERROR: SQLite: {exc}"
        )

        sys.exit(1)

    print(
        f"SQLite database: {args.db}"
    )

    all_results = {}

    # One physical host can be represented by several logical
    # switch entries. Do not query identity repeatedly.
    device_info_cache = {}
    neighbor_cache = {}

    # --------------------------------------------------------
    # Collect switches
    # --------------------------------------------------------

    for switch_config in switches:

        host = switch_config["host"]
        name = switch_config["name"]
        interface_prefix = switch_config["interface_prefix"]

        print()
        print("=" * 70)

        print(
            f"Switch: {name} ({host})"
        )

        print("=" * 70)

        try:

            if host not in device_info_cache:
                device_info_cache[host] = collect_switch_identity(
                    host,
                    community
                )

            sys_name, model = device_info_cache[host]

            ports = collect_switch(
                host,
                community,
                interface_prefix=interface_prefix
            )

            all_results[name] = ports

            # ------------------------------------------------
            # Save to SQLite
            #
            # ВАЖНО: используем name, а не host, как
            # уникальный ключ - иначе логические свичи
            # с одинаковым реальным IP (например, SW106
            # и SW107) будут конфликтовать в таблице
            # switches (там UNIQUE по host).
            # ------------------------------------------------

            save_switch_to_database(
                connection,
                name,
                ports,
                sys_name=sys_name,
                model=model
            )

            print(
                f"Saved to SQLite: "
                f"{len(ports)} ports"
            )

            # LLDP / CDP neighbours; a failure here never loses the port data.
            try:
                if host not in neighbor_cache:
                    neighbor_cache[host] = collect_neighbors(host, community)
                count = save_neighbors_to_database(connection, name, ports, neighbor_cache[host])
                print(f"Neighbours (LLDP/CDP): {count}")
            except Exception as exc:
                connection.rollback()
                print(f"WARNING: neighbours not collected from {host} ({name}): {exc}")

        except Exception as exc:

            print(
                f"ERROR: Не удалось получить "
                f"данные с {host} ({name}): {exc}"
            )

            continue

    # --------------------------------------------------------
    # Refresh current MAC -> IP mapping from the L3 core.
    # This runs after switch FDB collection. MAC/IP come from Core; hostname comes from reverse DNS.
    # --------------------------------------------------------

    try:
        save_core_arp_snapshot(connection, arp_sources)
    except Exception as exc:
        print(f"WARNING: Core ARP snapshot was not updated: {exc}")

    # Tell open web pages that inventory data changed.
    try:
        StateRepository(connection).bump("inventory", now_iso())
        connection.commit()
    except Exception as exc:
        print(f"WARNING: data version was not updated: {exc}")

    # Keep only the last RETENTION_DAYS of history (Change History included).
    try:
        prune_old_records(connection, settings.RETENTION_DAYS)
    except Exception as exc:
        connection.rollback()
        print(f"WARNING: old history was not cleaned up: {exc}")

    connection.close()

    # --------------------------------------------------------
    # Nothing collected
    # --------------------------------------------------------

    if not all_results:

        print()

        print(
            "ERROR: Не удалось собрать данные "
            "ни с одного свича."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    if args.json:

        result = build_json_result(
            all_results
        )

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False
            )
        )

        return

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    if args.csv:

        try:

            write_csv(
                all_results,
                args.csv
            )

            print()

            print(
                f"CSV saved to: {args.csv}"
            )

        except OSError as exc:

            print(
                f"ERROR: Не удалось "
                f"записать CSV: {exc}"
            )

            sys.exit(1)

        return

    # --------------------------------------------------------
    # Normal output
    # --------------------------------------------------------

    total_ports = 0

    for host, ports in all_results.items():

        print()

        print(
            f"Switch: {host}"
        )

        print_table(
            host,
            ports
        )

        print(
            f"Total physical ports: "
            f"{len(ports)}"
        )

        total_ports += len(ports)

    print()

    print(
        "Total physical ports on all switches: "
        f"{total_ports}"
    )

    print()

    print(
        f"SQLite updated: {args.db}"
    )
