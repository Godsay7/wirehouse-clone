"""Saving collected switches through the data access layer."""

import sqlite3
from typing import Dict, List

from ..bll.domain.cabling_check import device_replaced
from ..core.text import now_iso
from ..core.vlan import format_vlans, vlan_summary
from .port_errors import counter_growth
from ..dal.repositories.history import HistoryRepository
from ..dal.repositories.switches import SwitchRepository
from ..dal.database import BUSY_TIMEOUT_SECONDS, configure_connection
from ..dal.schema import ensure_inventory_schema

# Fields compared between two polls, in the order Change History lists them.
TRACKED_FIELDS = (
    ("Device", "Device"),
    ("Speed", "Speed"),
    ("Link", "Link"),
    ("MAC", "MAC"),
)


def init_database(
    database_file: str
):
    """Open (and create/migrate) the SQLite database."""

    connection = sqlite3.connect(
        database_file,
        timeout=BUSY_TIMEOUT_SECONDS,
    )

    configure_connection(connection)
    ensure_inventory_schema(connection)

    return connection


def save_switch_to_database(
    connection,
    host: str,
    ports: List[Dict],
    sys_name: str = "-",
    model: str = "-"
):
    """Save one switch: current port state, history and detected changes.

    port_history gets a row only when a port is seen for the first time or
    its state (device, speed, link, MAC, ifIndex, ifName) differs from the
    previous poll. Unchanged ports are not copied every 5 minutes; the state
    at any moment is the latest history row of the port before it.

    ВАЖНО: параметр host здесь - это уникальный
    идентификатор свича для БД (в main() туда передаётся
    switch_config["name"], а не реальный IP), потому что
    колонка switches.host имеет ограничение UNIQUE, а два
    логических свича могут иметь один и тот же реальный IP.
    """

    now = now_iso()

    switches = SwitchRepository(connection)
    history = HistoryRepository(connection)

    switch_id = switches.upsert(
        host,
        sys_name,
        model,
        now,
    )

    if switch_id is None:

        raise RuntimeError(
            f"Не удалось получить ID "
            f"свича {host}"
        )

    # --------------------------------------------------------
    # MAC state is current-state only.
    #
    # IMPORTANT: do NOT preserve the previous MAC when the current FDB
    # has no MAC for the port. A missing MAC is written as '-' so stale
    # devices disappear from the web UI immediately after the next poll.
    # --------------------------------------------------------

    for port in ports:
        if port.get("MAC") in (None, ""):
            port["MAC"] = "-"

    previous_states = switches.current_port_states(switch_id)
    previous_extras = switches.port_vlans_and_counters(switch_id)
    # The device that worked on each port before (kept while the port is down).
    previous_devices = switches.last_macs(switch_id)

    for port in ports:
        previous = previous_states.get(port["Port"])

        if previous is not None and _same_state(previous, port):
            continue

        history_id = history.insert_port_snapshot(switch_id, port, now)

        # The first poll of a port has nothing to compare with.
        if previous is None:
            continue

        for (change_type, key), old_value in zip(TRACKED_FIELDS, previous):
            new_value = port[key]

            if (old_value or "") != (new_value or ""):
                history.insert_change(
                    switch_id,
                    port,
                    change_type,
                    old_value,
                    new_value,
                    now,
                    history_id,
                )

    for port in ports:
        _record_vlan_change(history, switch_id, port, previous_extras.get(port["Port"]), now)
        _record_error_growth(switches, switch_id, port, previous_extras.get(port["Port"]), now)

        # Another device on the port than the one that worked there before (Cabling Check).
        replaced = device_replaced(previous_devices.get(port["Port"]), port["MAC"])
        if replaced:
            history.insert_device_change(switch_id, port, *replaced, now)

    for port in ports:
        switches.upsert_port(switch_id, port, now)

    _confirm_port_names(connection, switch_id, ports, now)

    connection.commit()


def _confirm_port_names(connection, switch_id, ports, now):
    """A name written on a port (Cabling Check) becomes "confirmed" the first
    time its MAC is seen on that port."""

    try:
        pending = connection.execute(
            "SELECT port, mac FROM port_names WHERE switch_id = ? AND confirmed_at IS NULL", (switch_id,)
        ).fetchall()
    except sqlite3.OperationalError:          # the web app has not created the table yet
        return
    macs_by_port = {port["Port"]: str(port.get("MAC") or "").lower() for port in ports}
    for port_number, mac in pending:
        if mac and mac.lower() in macs_by_port.get(port_number, ""):
            connection.execute(
                "UPDATE port_names SET confirmed_at = ? WHERE switch_id = ? AND port = ?",
                (now, switch_id, port_number),
            )


def _record_vlan_change(history, switch_id, port, previous, now):
    """A "VLAN" row in Change History when the VLANs of a port changed.

    previous: (vlan_mode, vlan, vlan_tagged, ...) from the last poll. Nothing
    is recorded the first time VLANs are seen, or when the switch did not
    report them this time.
    """

    vlan = port.get("_vlan")
    if not vlan or previous is None or previous[0] is None:
        return
    old = vlan_summary(previous[0], previous[1], previous[2] or "")
    new = vlan_summary(vlan.get("mode"), vlan.get("vlan"), format_vlans(vlan.get("tagged") or []))
    if old != new:
        history.insert_change(switch_id, port, "VLAN", old, new, now, None)


def _record_error_growth(switches, switch_id, port, previous, now):
    """port_error_events row when the error counters grew since the last poll."""

    errors = port.get("_errors")
    if not errors or previous is None:
        return
    grown = {
        "in": counter_growth(previous[3], errors.get("in")),
        "out": counter_growth(previous[4], errors.get("out")),
        "fcs": counter_growth(previous[5], errors.get("fcs")),
    }
    if any(grown.values()):
        switches.insert_error_event(switch_id, port["Port"], now, grown)


def save_neighbors_to_database(connection, host: str, ports: List[Dict], neighbors_by_if_index: Dict) -> int:
    """Replace the LLDP/CDP neighbours of one logical switch (``host`` = its name).

    Only neighbours on this switch's own ports are kept, so SW106 and SW107
    (one device, one IP) each get their own.
    """

    switches = SwitchRepository(connection)
    switch_id = switches.find_id(host)
    if switch_id is None:
        return 0

    port_by_if_index = {port["_ifIndex"]: port["Port"] for port in ports if port.get("_ifIndex") is not None}
    rows = []
    for if_index, entries in neighbors_by_if_index.items():
        port = port_by_if_index.get(if_index)
        if port is None:
            continue
        for entry in entries:
            rows.append((port, entry))

    switches.replace_neighbors(switch_id, rows, now_iso())
    connection.commit()
    return len(rows)


def _same_state(previous, port):
    """previous: (device, speed, link, mac, if_index, if_name) from ports."""

    current = (
        port["Device"],
        port["Speed"],
        port["Link"],
        port["MAC"],
        port["_ifIndex"],
        port["_ifName"],
    )

    return all(
        _comparable(old) == _comparable(new)
        for old, new in zip(previous, current)
    )


def _comparable(value):
    return "" if value is None else str(value)
