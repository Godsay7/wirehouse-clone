"""Shared application state: data version counters."""

STATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS app_state (
        key TEXT PRIMARY KEY,
        value INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT
    )
"""


def ensure_state_schema(connection):
    connection.execute(STATE_TABLE_SQL)
    connection.commit()
