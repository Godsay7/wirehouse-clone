"""SNMP inventory tables written by the collector."""

from .state import ensure_state_schema


def ensure_inventory_schema(connection):
    """Create switches/ports/port_history/arp_entries and add new columns."""

    cursor = connection.cursor()

    # WAL: the web app keeps reading while the collector writes (instead of
    # waiting for it). The mode is stored in the database file.
    cursor.execute("PRAGMA journal_mode=WAL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS switches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT NOT NULL UNIQUE,
            last_seen TEXT
        )
        """
    )

    # Switch identity columns were added after the first release.
    switch_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(switches)").fetchall()
    }

    if "sys_name" not in switch_columns:
        cursor.execute(
            "ALTER TABLE switches ADD COLUMN sys_name TEXT"
        )

    if "model" not in switch_columns:
        cursor.execute(
            "ALTER TABLE switches ADD COLUMN model TEXT"
        )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            switch_id INTEGER NOT NULL,

            port INTEGER NOT NULL,
            device TEXT,
            speed TEXT,
            link TEXT,
            mac TEXT,

            if_index INTEGER,
            if_name TEXT,

            last_seen TEXT,

            UNIQUE (
                switch_id,
                port
            ),

            FOREIGN KEY (
                switch_id
            )
            REFERENCES switches(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS port_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            switch_id INTEGER NOT NULL,

            port INTEGER NOT NULL,
            device TEXT,
            speed TEXT,
            link TEXT,
            mac TEXT,

            if_index INTEGER,
            if_name TEXT,

            collected_at TEXT NOT NULL,

            FOREIGN KEY (
                switch_id
            )
            REFERENCES switches(id)
        )
        """
    )

    # Current ARP / neighbor snapshot learned from core switches.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS arp_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mac TEXT NOT NULL,
            ip TEXT NOT NULL,
            hostname TEXT,
            if_index INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            UNIQUE(mac, ip)
        )
        """
    )

    # Port changes detected by the collector at save time. Change History
    # reads this table instead of comparing millions of port_history rows.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS port_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            switch_id INTEGER NOT NULL,
            port INTEGER NOT NULL,
            change_type TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            if_index INTEGER,
            if_name TEXT,
            detected_at TEXT NOT NULL,
            history_id INTEGER,
            FOREIGN KEY (switch_id) REFERENCES switches(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_port_changes_detected
            ON port_changes (detected_at, history_id)
        """
    )
    # The history of one port (switch page -> port history).
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_port_changes_port ON port_changes (switch_id, port, detected_at)"
    )

    # LLDP / CDP neighbours seen on each port at the last poll (replaced per switch).
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS port_neighbors (
            switch_id INTEGER NOT NULL,
            port INTEGER NOT NULL,
            protocol TEXT NOT NULL,
            remote_name TEXT NOT NULL DEFAULT '',
            remote_port TEXT NOT NULL DEFAULT '',
            remote_port_desc TEXT NOT NULL DEFAULT '',
            remote_chassis TEXT NOT NULL DEFAULT '',
            remote_platform TEXT NOT NULL DEFAULT '',
            last_seen TEXT NOT NULL,
            FOREIGN KEY (switch_id) REFERENCES switches(id)
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_port_neighbors_switch ON port_neighbors (switch_id, port)"
    )

    # VLANs and error counters of each port at the last poll.
    # vlan_mode: 'access' | 'trunk' | NULL (the switch does not say);
    # vlan: access or native VLAN; vlan_tagged: "10,20-30".
    # *_errors: the raw counters, to compute the growth at the next poll.
    port_columns = {row[1] for row in cursor.execute("PRAGMA table_info(ports)").fetchall()}
    for column, kind in (
        ("vlan_mode", "TEXT"), ("vlan", "INTEGER"), ("vlan_tagged", "TEXT"),
        ("in_errors", "INTEGER"), ("out_errors", "INTEGER"), ("fcs_errors", "INTEGER"),
    ):
        if column not in port_columns:
            cursor.execute(f"ALTER TABLE ports ADD COLUMN {column} {kind}")

    # The last MAC seen on a port and when: shown as "last known data" while
    # the port is down. Filled from the port history once, then by the collector.
    if "last_mac" not in port_columns:
        cursor.execute("ALTER TABLE ports ADD COLUMN last_mac TEXT")
        cursor.execute("ALTER TABLE ports ADD COLUMN last_mac_at TEXT")
        _backfill_last_mac(cursor)

    # A row whenever the error counters of a port grew since the previous poll
    # (how much each grew). Ports with growing errors are found from here.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS port_error_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            switch_id INTEGER NOT NULL,
            port INTEGER NOT NULL,
            detected_at TEXT NOT NULL,
            in_errors INTEGER NOT NULL DEFAULT 0,
            out_errors INTEGER NOT NULL DEFAULT 0,
            fcs_errors INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (switch_id) REFERENCES switches(id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_port_error_events_at ON port_error_events (detected_at, switch_id, port)"
    )

    # Another device on a port where one worked before (the collector,
    # bll/domain/cabling_check.device_replaced). Kept as long as port_changes.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS port_device_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            switch_id INTEGER NOT NULL,
            port INTEGER NOT NULL,
            if_name TEXT,
            old_macs TEXT NOT NULL,
            new_macs TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            FOREIGN KEY (switch_id) REFERENCES switches(id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_port_device_changes_port ON port_device_changes (switch_id, port, id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_port_device_changes_at ON port_device_changes (detected_at)"
    )

    connection.commit()

    ensure_state_schema(connection)


def _backfill_last_mac(cursor):
    """ports.last_mac / last_mac_at from port_history: the newest MAC each port
    had, and the time it was last there (when the next state replaced it)."""

    history = {}
    for switch_id, port, mac, at in cursor.execute(
        "SELECT switch_id, port, mac, collected_at FROM port_history ORDER BY id"
    ):
        history.setdefault((switch_id, port), []).append((mac, at))

    updates = []
    for (switch_id, port), states in history.items():
        for index in range(len(states) - 1, -1, -1):
            mac, at = states[index]
            if mac and mac != "-":
                gone_at = states[index + 1][1] if index + 1 < len(states) else at
                updates.append((mac, gone_at, switch_id, port))
                break
    cursor.executemany("UPDATE ports SET last_mac = ?, last_mac_at = ? WHERE switch_id = ? AND port = ?", updates)
    # Ports with a MAC right now: that one, as of their last poll.
    cursor.execute(
        "UPDATE ports SET last_mac = mac, last_mac_at = last_seen WHERE mac IS NOT NULL AND mac NOT IN ('', '-')"
    )
