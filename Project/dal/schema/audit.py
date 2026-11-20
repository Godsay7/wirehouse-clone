"""Rack change history: every row the web app changes in the rack tables.

Triggers copy the old and new row (JSON) of each INSERT / UPDATE / DELETE
into rack_audit_rows, but only while rack_audit_context points at an open
rack_audit entry — Database.write(touch="rack") opens one per request. The
collector never sets it, so its writes are not recorded. Undo replays the
rows backwards (see dal/repositories/audit.py).
"""

# Tables whose rows are recorded. ports: only its description (written in
# Rack Change); the rest of a port row belongs to the collector.
AUDITED_TABLES = (
    "server_rooms",
    "racks",
    "rack_switches",
    "rack_switch_placeholders",
    "patch_panels",
    "patch_ports",
    "cable_organizers",
    "servers",
    "server_ports",
    "port_connections",
    "patch_connections",
    "trunk_cables",
    "rack_view_order",
    "rack_view_slots",
    "port_expected_devices",
    "placeholder_ports",
    "host_names",
    "port_names",
)

ACTIVE = "(SELECT audit_id FROM rack_audit_context WHERE id = 1) IS NOT NULL"
CURRENT = "(SELECT audit_id FROM rack_audit_context WHERE id = 1)"


def _columns(db, table):
    return [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]


def _json(prefix, columns):
    return "json_object(" + ", ".join(f"'{c}', {prefix}.\"{c}\"" for c in columns) + ")"


def ensure_audit_schema(db):
    """Create the history tables and (re)create the triggers for the current columns."""

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS rack_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            actor_ip TEXT NOT NULL DEFAULT '',
            actor_name TEXT NOT NULL DEFAULT '',
            actor_user TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT '',
            undo_of INTEGER,
            undone_by INTEGER
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS rack_audit_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id INTEGER NOT NULL,
            tbl TEXT NOT NULL,
            op TEXT NOT NULL,
            row_id INTEGER NOT NULL,
            old_row TEXT,
            new_row TEXT
        )
        """
    )
    # Who was signed in (web/auth.py); older entries have none.
    if "actor_user" not in _columns(db, "rack_audit"):
        db.execute("ALTER TABLE rack_audit ADD COLUMN actor_user TEXT NOT NULL DEFAULT ''")
    db.execute("CREATE INDEX IF NOT EXISTS idx_rack_audit_rows_audit ON rack_audit_rows (audit_id)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS rack_audit_context (id INTEGER PRIMARY KEY CHECK (id = 1), audit_id INTEGER)"
    )
    db.execute("INSERT OR IGNORE INTO rack_audit_context (id, audit_id) VALUES (1, NULL)")
    # A crash between begin and finish must not leave recording switched on.
    db.execute("UPDATE rack_audit_context SET audit_id = NULL WHERE id = 1")

    existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    for table in AUDITED_TABLES:
        for op in ("ins", "upd", "del"):
            db.execute(f"DROP TRIGGER IF EXISTS audit_{table}_{op}")
        if table not in existing:
            continue
        columns = _columns(db, table)
        new_json, old_json = _json("NEW", columns), _json("OLD", columns)
        db.execute(
            f"""
            CREATE TRIGGER audit_{table}_ins AFTER INSERT ON {table} WHEN {ACTIVE}
            BEGIN
                INSERT INTO rack_audit_rows (audit_id, tbl, op, row_id, old_row, new_row)
                VALUES ({CURRENT}, '{table}', 'insert', NEW.rowid, NULL, {new_json});
            END
            """
        )
        db.execute(
            f"""
            CREATE TRIGGER audit_{table}_upd AFTER UPDATE ON {table} WHEN {ACTIVE}
            BEGIN
                INSERT INTO rack_audit_rows (audit_id, tbl, op, row_id, old_row, new_row)
                SELECT {CURRENT}, '{table}', 'update', NEW.rowid, {old_json}, {new_json}
                WHERE {old_json} IS NOT {new_json};
            END
            """
        )
        db.execute(
            f"""
            CREATE TRIGGER audit_{table}_del AFTER DELETE ON {table} WHEN {ACTIVE}
            BEGIN
                INSERT INTO rack_audit_rows (audit_id, tbl, op, row_id, old_row, new_row)
                VALUES ({CURRENT}, '{table}', 'delete', OLD.rowid, {old_json}, NULL);
            END
            """
        )

    db.execute("DROP TRIGGER IF EXISTS audit_ports_description")
    if "ports" in existing:
        db.execute(
            f"""
            CREATE TRIGGER audit_ports_description AFTER UPDATE OF description ON ports
            WHEN {ACTIVE} AND OLD.description IS NOT NEW.description
            BEGIN
                INSERT INTO rack_audit_rows (audit_id, tbl, op, row_id, old_row, new_row)
                VALUES ({CURRENT}, 'ports', 'update', NEW.rowid,
                        json_object('switch_id', OLD.switch_id, 'port', OLD.port, 'description', OLD.description),
                        json_object('switch_id', NEW.switch_id, 'port', NEW.port, 'description', NEW.description));
            END
            """
        )
