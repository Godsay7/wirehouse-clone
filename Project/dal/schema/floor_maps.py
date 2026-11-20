"""Floor maps: schematic plans of work areas (rooms and workplaces)."""

FLOOR_MAP_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS floor_maps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        width INTEGER NOT NULL DEFAULT 80,
        height INTEGER NOT NULL DEFAULT 50,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS floor_map_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        map_id INTEGER NOT NULL,
        room_type TEXT NOT NULL DEFAULT 'room',
        name TEXT NOT NULL DEFAULT '',
        points TEXT NOT NULL,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (map_id) REFERENCES floor_maps(id)
    );

    CREATE TABLE IF NOT EXISTS floor_map_workplaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        map_id INTEGER NOT NULL,
        x REAL NOT NULL,
        y REAL NOT NULL,
        device_type TEXT NOT NULL DEFAULT 'pc',
        role TEXT NOT NULL DEFAULT '',
        pc_name TEXT NOT NULL DEFAULT '',
        ip TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (map_id) REFERENCES floor_maps(id)
    );

    CREATE INDEX IF NOT EXISTS idx_floor_map_rooms_map ON floor_map_rooms (map_id);
    CREATE INDEX IF NOT EXISTS idx_floor_map_workplaces_map ON floor_map_workplaces (map_id);
"""

# Maps created together with the tables. Deleted maps are not recreated.
DEFAULT_MAPS = ("Newsroom", "АСБ")


def ensure_floor_map_schema(connection, now=None):
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'floor_maps'"
    ).fetchone()

    connection.executescript(FLOOR_MAP_SCHEMA_SQL)

    # Columns added later.
    _add_column(connection, "floor_map_workplaces", "device_type", "TEXT NOT NULL DEFAULT 'pc'")  # pc / phone / wifi
    _add_column(connection, "floor_map_rooms", "room_type", "TEXT NOT NULL DEFAULT 'room'")       # room / area
    _add_column(connection, "floor_map_workplaces", "socket", "TEXT NOT NULL DEFAULT ''")          # wall socket, e.g. 2-19
    _add_column(connection, "floor_map_workplaces", "dante_ip", "TEXT NOT NULL DEFAULT ''")        # second NIC (Dante audio network)
    _add_column(connection, "floor_map_workplaces", "dante_socket", "TEXT NOT NULL DEFAULT ''")    # wall socket of the Dante NIC

    if not exists:
        connection.executemany(
            "INSERT OR IGNORE INTO floor_maps (name, position, created_at, updated_at) VALUES (?, ?, ?, ?)",
            [(name, index, now, now) for index, name in enumerate(DEFAULT_MAPS)],
        )

    connection.commit()


def _add_column(connection, table, column, definition):
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
