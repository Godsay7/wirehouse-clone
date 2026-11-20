"""Data version counters.

``inventory`` grows after every collector run, ``rack`` after every change
made in Rack Change, ``maps`` after every change on Floor Maps. Browsers poll these numbers and reload only the parts
of a page whose data changed.
"""

from .base import Repository

VERSION_KEYS = ("inventory", "rack", "maps")


class StateRepository(Repository):

    def versions(self):
        """{"inventory": n, "rack": m, "maps": k}; 0 for counters that do not exist yet."""

        result = {key: 0 for key in VERSION_KEYS}

        try:
            rows = self._all("SELECT key, value FROM app_state")
        except Exception:
            # The table is created by the collector / web startup; a brand-new
            # database may not have it yet.
            return result

        for key, value in rows:
            if key in result:
                result[key] = int(value or 0)

        return result

    def bump(self, key, updated_at):
        self._execute(
            """
            INSERT INTO app_state (key, value, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = value + 1,
                updated_at = excluded.updated_at
            """,
            (key, updated_at),
        )
