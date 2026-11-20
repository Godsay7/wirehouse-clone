"""SQLite connection management."""

import os
import sqlite3
from contextlib import contextmanager

from ..core.actor import current_actor
from ..core.text import now_iso

# The collector and the web app write to the same file. SQLite allows one
# writer at a time, so wait for the other one instead of failing quickly.
BUSY_TIMEOUT_SECONDS = 30


def configure_connection(connection):
    """Per-connection settings shared by the web app and the collector."""

    # Safe with WAL: a power loss can lose the last commit, never corrupt.
    connection.execute("PRAGMA synchronous=NORMAL")


class Database:
    """Opens SQLite connections for one database file.

    Use ``read()`` for queries and ``write()`` for changes: ``write()`` commits
    when the block finishes and rolls back if it raises. Both yield a
    ``UnitOfWork`` that exposes every repository bound to one connection.

    ``write(touch="rack")`` also bumps that data version counter in the same
    transaction, so open pages know they have to refresh, and records every
    changed rack row in the change history (rack_audit, with who did it).
    """

    def __init__(self, path, must_exist=True):
        self.path = path
        self.must_exist = must_exist

    def connect(self):
        if self.must_exist and not os.path.exists(self.path):
            raise RuntimeError(
                f"SQLite database not found: {self.path}"
            )

        connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS)
        connection.row_factory = sqlite3.Row
        configure_connection(connection)
        return connection

    @contextmanager
    def read(self):
        from .unit_of_work import UnitOfWork

        connection = self.connect()

        try:
            yield UnitOfWork(connection)
        finally:
            connection.close()

    @contextmanager
    def write(self, touch=None):
        from .unit_of_work import UnitOfWork

        connection = self.connect()

        try:
            uow = UnitOfWork(connection)
            audit_id = uow.audit.begin(now_iso(), current_actor()) if touch == "rack" else None
            yield uow
            if audit_id is not None:
                uow.audit.finish(audit_id)
            if touch:
                uow.state.bump(touch, now_iso())
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
