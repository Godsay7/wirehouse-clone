"""Rack View / Rack Change tables and their in-place migrations.

v3 adds:
  - server_rooms
  - duplicate rack names allowed in different server rooms
  - front/rear rack sides

Existing racks and mounted equipment are preserved. Existing equipment is
assigned to the front side during migration.
"""

from .audit import ensure_audit_schema
from ...core.text import now_iso


def _table_columns(connection, table_name):
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def _has_unique_index(connection, table_name, column_names):
    expected = list(column_names)

    for index_row in connection.execute(f"PRAGMA index_list({table_name})"):
        # PRAGMA index_list: seq, name, unique, origin, partial
        if not index_row[2]:
            continue

        index_name = index_row[1]
        indexed_columns = [
            row[2]
            for row in connection.execute(f"PRAGMA index_info('{index_name}')")
        ]

        if indexed_columns == expected:
            return True

    return False


RACKS_TABLE_SQL = """
    CREATE TABLE {name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_room_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        location TEXT,
        units INTEGER NOT NULL DEFAULT 42,
        created_at TEXT,
        UNIQUE(server_room_id, name),
        FOREIGN KEY (server_room_id) REFERENCES server_rooms(id)
    )
"""

PORT_CONNECTIONS_TABLE_SQL = """
    CREATE TABLE {name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint_a_type TEXT NOT NULL,
        endpoint_a_id INTEGER NOT NULL,
        endpoint_a_port INTEGER NOT NULL,
        endpoint_b_type TEXT NOT NULL,
        endpoint_b_id INTEGER NOT NULL,
        endpoint_b_port INTEGER NOT NULL,
        cable_type TEXT DEFAULT 'ethernet',
        cable_label TEXT,
        note TEXT,
        created_at TEXT,
        updated_at TEXT
    )
"""

RACK_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS patch_panels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rack_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        rack_unit INTEGER NOT NULL,
        port_count INTEGER NOT NULL DEFAULT 24,
        patch_type TEXT NOT NULL DEFAULT 'ethernet',
        side TEXT NOT NULL DEFAULT 'front',
        created_at TEXT,
        -- 'row': 1, 2, 3 … left to right; 'odd_even': 1, 3, 5 … on top, 2, 4, 6 … below
        port_layout TEXT NOT NULL DEFAULT 'row',
        UNIQUE(rack_id, name),
        FOREIGN KEY (rack_id) REFERENCES racks(id)
    );

    CREATE TABLE IF NOT EXISTS patch_ports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patch_panel_id INTEGER NOT NULL,
        port INTEGER NOT NULL,
        label TEXT,
        description TEXT,
        UNIQUE(patch_panel_id, port),
        FOREIGN KEY (patch_panel_id) REFERENCES patch_panels(id)
    );

    CREATE TABLE IF NOT EXISTS rack_switches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rack_id INTEGER NOT NULL,
        switch_id INTEGER NOT NULL,
        rack_unit INTEGER NOT NULL,
        height_units INTEGER NOT NULL DEFAULT 1,
        side TEXT NOT NULL DEFAULT 'front',
        UNIQUE(rack_id, switch_id),
        FOREIGN KEY (rack_id) REFERENCES racks(id),
        FOREIGN KEY (switch_id) REFERENCES switches(id)
    );

    CREATE TABLE IF NOT EXISTS rack_switch_placeholders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rack_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        model TEXT,
        rack_unit INTEGER NOT NULL,
        height_units INTEGER NOT NULL DEFAULT 1,
        port_count INTEGER NOT NULL DEFAULT 24,
        side TEXT NOT NULL DEFAULT 'front',
        created_at TEXT,
        UNIQUE(rack_id, name, side),
        FOREIGN KEY (rack_id) REFERENCES racks(id)
    );

    CREATE TABLE IF NOT EXISTS cable_organizers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rack_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        rack_unit INTEGER NOT NULL,
        height_units INTEGER NOT NULL DEFAULT 1,
        side TEXT NOT NULL DEFAULT 'front',
        created_at TEXT,
        FOREIGN KEY (rack_id) REFERENCES racks(id)
    );

    CREATE TABLE IF NOT EXISTS rack_view_order (
        server_room_id INTEGER NOT NULL,
        rack_id INTEGER NOT NULL UNIQUE,
        position_index INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT,
        PRIMARY KEY (server_room_id, rack_id),
        FOREIGN KEY (server_room_id) REFERENCES server_rooms(id),
        FOREIGN KEY (rack_id) REFERENCES racks(id)
    );

    CREATE TABLE IF NOT EXISTS patch_connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patch_panel_a_id INTEGER NOT NULL,
        patch_port_a INTEGER NOT NULL,
        patch_panel_b_id INTEGER NOT NULL,
        patch_port_b INTEGER NOT NULL,
        cable_type TEXT NOT NULL DEFAULT 'ethernet',
        cable_label TEXT,
        note TEXT,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (patch_panel_a_id) REFERENCES patch_panels(id),
        FOREIGN KEY (patch_panel_b_id) REFERENCES patch_panels(id)
    );

    CREATE INDEX IF NOT EXISTS idx_patch_connections_a
        ON patch_connections (patch_panel_a_id, patch_port_a);
    CREATE INDEX IF NOT EXISTS idx_patch_connections_b
        ON patch_connections (patch_panel_b_id, patch_port_b);

    CREATE TABLE IF NOT EXISTS servers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rack_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        rack_unit INTEGER NOT NULL,
        height_units INTEGER NOT NULL DEFAULT 1,
        side TEXT NOT NULL DEFAULT 'front',
        created_at TEXT,
        UNIQUE(rack_id, name),
        FOREIGN KEY (rack_id) REFERENCES racks(id)
    );

    CREATE TABLE IF NOT EXISTS server_ports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER NOT NULL,
        port INTEGER NOT NULL,
        label TEXT,
        UNIQUE(server_id, port),
        FOREIGN KEY (server_id) REFERENCES servers(id)
    );
"""


def ensure_rack_schema(connection, two_unit_switch_hosts=()):
    """Create/migrate Rack View tables on an open connection and commit.

    ``two_unit_switch_hosts`` are switch names whose chassis is physically 2U;
    their existing rack placements get height_units = 2.
    """

    db = connection
    db.execute("PRAGMA foreign_keys = OFF")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS server_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    _migrate_racks(db)
    # Width of a rack in percent of a normal one (a narrow "rack" of tower PCs by a wall).
    if "width_percent" not in _table_columns(db, "racks"):
        db.execute("ALTER TABLE racks ADD COLUMN width_percent INTEGER NOT NULL DEFAULT 100")

    db.executescript(RACK_TABLES_SQL)

    _migrate_port_connections(db)

    patch_columns = _table_columns(db, "patch_panels")
    if "side" not in patch_columns:
        db.execute(
            "ALTER TABLE patch_panels ADD COLUMN side TEXT NOT NULL DEFAULT 'front'"
        )
    if "patch_type" not in patch_columns:
        db.execute(
            "ALTER TABLE patch_panels ADD COLUMN patch_type TEXT NOT NULL DEFAULT 'ethernet'"
        )
    if "port_layout" not in patch_columns:
        db.execute(
            "ALTER TABLE patch_panels ADD COLUMN port_layout TEXT NOT NULL DEFAULT 'row'"
        )

    rack_switch_columns = _table_columns(db, "rack_switches")
    if "side" not in rack_switch_columns:
        db.execute(
            "ALTER TABLE rack_switches ADD COLUMN side TEXT NOT NULL DEFAULT 'front'"
        )

    # A management port (mng) drawn after the switch ports: SNMP does not
    # report it, so it is switched on by hand in Rack Change (port 0).
    if "mgmt_port" not in rack_switch_columns:
        db.execute("ALTER TABLE rack_switches ADD COLUMN mgmt_port INTEGER NOT NULL DEFAULT 0")

    # Rack View board: "grid" = the classic 2 x 6 positions, "custom" = only
    # occupied positions plus empty ones added on purpose (rack_view_slots).
    room_columns = _table_columns(db, "server_rooms")
    if room_columns and "board_layout" not in room_columns:
        db.execute("ALTER TABLE server_rooms ADD COLUMN board_layout TEXT NOT NULL DEFAULT 'grid'")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS rack_view_slots (
            server_room_id INTEGER NOT NULL,
            position_index INTEGER NOT NULL,
            PRIMARY KEY (server_room_id, position_index),
            FOREIGN KEY (server_room_id) REFERENCES server_rooms(id)
        )
        """
    )

    # Trunk cables between ODF panels (usually in different rooms):
    # port_a_start .. +port_count-1 of panel A <-> port_b_start .. of panel B.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS trunk_cables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_a_id INTEGER NOT NULL,
            port_a_start INTEGER NOT NULL,
            panel_b_id INTEGER NOT NULL,
            port_b_start INTEGER NOT NULL,
            port_count INTEGER NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            created_at TEXT,
            FOREIGN KEY (panel_a_id) REFERENCES patch_panels(id),
            FOREIGN KEY (panel_b_id) REFERENCES patch_panels(id)
        )
        """
    )

    # Notes on the ports of temporary switches (their ports can be cabled).
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS placeholder_ports (
            placeholder_id INTEGER NOT NULL,
            port INTEGER NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (placeholder_id, port)
        )
        """
    )

    # The device (MAC) documented on a switch port, e.g. from the cable
    # journal; the cabling check compares it with the switch MAC tables.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS port_expected_devices (
            switch_id INTEGER NOT NULL,
            port INTEGER NOT NULL,
            mac TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            PRIMARY KEY (switch_id, port, mac)
        )
        """
    )

    # The documented device's name written on its switch port (Cabling Check
    # "Write to the switch"): shown on the switch page, "not verified" until
    # the collector sees that MAC on the port (confirmed_at).
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS port_names (
            switch_id INTEGER NOT NULL,
            port INTEGER NOT NULL,
            mac TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            confirmed_at TEXT,
            created_at TEXT,
            PRIMARY KEY (switch_id, port)
        )
        """
    )

    # Hostnames typed in by hand for a device (MAC), for addresses DNS does
    # not know or names it wrongly. They follow the device to any port.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS host_names (
            mac TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            updated_at TEXT
        )
        """
    )

    server_columns = _table_columns(db, "servers")
    if server_columns and "side" not in server_columns:
        db.execute("ALTER TABLE servers ADD COLUMN side TEXT NOT NULL DEFAULT 'front'")
    if server_columns and "front_image" not in server_columns:
        db.execute("ALTER TABLE servers ADD COLUMN front_image TEXT")
    # 'full' = spans the rack depth (front and rear), 'half' = only its own side.
    if server_columns and "depth" not in server_columns:
        db.execute("ALTER TABLE servers ADD COLUMN depth TEXT NOT NULL DEFAULT 'full'")

    _normalize_rows(db, two_unit_switch_hosts)

    ports_columns = _table_columns(db, "ports")
    if ports_columns and "description" not in ports_columns:
        db.execute("ALTER TABLE ports ADD COLUMN description TEXT")

    # Change history triggers last: they copy the current columns of each table.
    # Cable checklist (/checklist): private marks of one user's walk through
    # the racks; not audited, shown nowhere else.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS cable_checklist (
            switch_id INTEGER NOT NULL,
            port INTEGER NOT NULL,
            confirmed_target TEXT,              -- what was confirmed (port <-> panel / device); NULL = not confirmed
            confirmed_at TEXT,
            confirmed_by TEXT,
            shorter INTEGER NOT NULL DEFAULT 0, -- the cable must be replaced by a shorter one
            tidy INTEGER NOT NULL DEFAULT 0,    -- the cable must be laid neatly
            note TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            updated_by TEXT,
            PRIMARY KEY (switch_id, port)
        )
        """
    )

    checklist_columns = _table_columns(db, "cable_checklist")
    if "actual" not in checklist_columns:
        # "Not as documented": where the cable really goes, and what the
        # documentation said when that was noted.
        db.execute("ALTER TABLE cable_checklist ADD COLUMN actual TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE cable_checklist ADD COLUMN mismatch_target TEXT")
    if "label" not in _table_columns(db, "cable_checklist"):
        # A sticker on the cable: NULL not checked, 1 there, 0 missing.
        db.execute("ALTER TABLE cable_checklist ADD COLUMN label INTEGER")

    ensure_audit_schema(db)

    db.commit()
    db.execute("PRAGMA foreign_keys = ON")


def _migrate_racks(db):
    """Migrate old global UNIQUE(name) to UNIQUE(server_room_id, name)."""

    rack_columns = _table_columns(db, "racks")

    if not rack_columns:
        db.execute(RACKS_TABLE_SQL.format(name="racks"))
        return

    needs_rack_rebuild = (
        "server_room_id" not in rack_columns
        or _has_unique_index(db, "racks", ["name"])
    )

    if not needs_rack_rebuild:
        return

    old_rows = [
        dict(row)
        for row in db.execute("SELECT * FROM racks ORDER BY id")
    ]

    db.execute("DROP TABLE IF EXISTS racks_v3_new")
    db.execute(RACKS_TABLE_SQL.format(name="racks_v3_new"))

    for old_rack in old_rows:
        room_id = old_rack.get("server_room_id")

        if room_id:
            room_exists = db.execute(
                "SELECT id FROM server_rooms WHERE id = ?",
                (room_id,),
            ).fetchone()
            if not room_exists:
                room_id = None

        if not room_id:
            room_name = str(
                old_rack.get("location")
                or "Default Server Room"
            ).strip() or "Default Server Room"

            db.execute(
                """
                INSERT OR IGNORE INTO server_rooms (
                    name,
                    description,
                    created_at
                )
                VALUES (?, NULL, ?)
                """,
                (
                    room_name,
                    now_iso(),
                ),
            )

            room_row = db.execute(
                "SELECT id FROM server_rooms WHERE name = ?",
                (room_name,),
            ).fetchone()
            room_id = room_row[0]

        db.execute(
            """
            INSERT INTO racks_v3_new (
                id,
                server_room_id,
                name,
                location,
                units,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                old_rack.get("id"),
                room_id,
                old_rack.get("name"),
                old_rack.get("location"),
                old_rack.get("units") or 42,
                old_rack.get("created_at"),
            ),
        )

    db.execute("DROP TABLE racks")
    db.execute("ALTER TABLE racks_v3_new RENAME TO racks")


def _migrate_port_connections(db):
    """v4: switch<->patch links became generic endpoint<->endpoint links."""

    conn_columns = _table_columns(db, "port_connections")

    if "switch_id" in conn_columns:
        db.execute("DROP TABLE IF EXISTS port_connections_v4")
        db.execute(PORT_CONNECTIONS_TABLE_SQL.format(name="port_connections_v4"))
        db.execute("""
            INSERT INTO port_connections_v4 (
                id, endpoint_a_type, endpoint_a_id, endpoint_a_port,
                endpoint_b_type, endpoint_b_id, endpoint_b_port,
                cable_label, note, created_at, updated_at
            )
            SELECT
                id, 'switch', switch_id, switch_port,
                'patch', patch_panel_id, patch_port,
                cable_label, note, created_at, updated_at
            FROM port_connections
        """)
        db.execute("DROP TABLE port_connections")
        db.execute("ALTER TABLE port_connections_v4 RENAME TO port_connections")
    elif not conn_columns:
        db.execute(PORT_CONNECTIONS_TABLE_SQL.format(name="port_connections"))


def _normalize_rows(db, two_unit_switch_hosts):
    """Normalize any manually created / incomplete rows."""

    db.execute(
        "UPDATE patch_panels SET side = 'front' WHERE side NOT IN ('front', 'rear') OR side IS NULL"
    )
    db.execute(
        "UPDATE patch_panels SET patch_type = 'ethernet' WHERE lower(COALESCE(patch_type, '')) NOT IN ('ethernet', 'sdi', 'odf')"
    )
    db.execute(
        "UPDATE patch_panels SET patch_type = lower(patch_type)"
    )
    db.execute(
        "UPDATE rack_switches SET side = 'front' WHERE side NOT IN ('front', 'rear') OR side IS NULL"
    )
    db.execute(
        "UPDATE rack_switch_placeholders SET side = 'front' WHERE side NOT IN ('front', 'rear') OR side IS NULL"
    )
    db.execute(
        "UPDATE rack_switch_placeholders SET height_units = 1 WHERE height_units IS NULL OR height_units < 1"
    )
    db.execute(
        "UPDATE rack_switch_placeholders SET port_count = 0 WHERE port_count IS NULL OR port_count < 0"
    )

    # rack_switches.rack_unit is treated as the TOP occupied U for switches,
    # so an existing 2U placement at U42 becomes U42+U41 without moving it.
    hosts = [str(host).upper() for host in two_unit_switch_hosts]
    if hosts:
        placeholders = ", ".join("?" for _ in hosts)
        db.execute(
            f"""
            UPDATE rack_switches
            SET height_units = 2
            WHERE switch_id IN (
                SELECT id
                FROM switches
                WHERE UPPER(host) IN ({placeholders})
            )
            """,
            hosts,
        )

    db.execute(
        "UPDATE cable_organizers SET side = 'front' WHERE side NOT IN ('front', 'rear') OR side IS NULL"
    )
    db.execute(
        "UPDATE cable_organizers SET height_units = 1 WHERE height_units NOT IN (1, 2) OR height_units IS NULL"
    )
