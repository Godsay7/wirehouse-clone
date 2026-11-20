"""Data access layer: SQLite connection, schema/migrations and repositories.

Only this package contains SQL. Repositories return ``sqlite3.Row`` objects or
plain dicts and never contain business rules.
"""

from .database import Database

__all__ = ["Database"]
