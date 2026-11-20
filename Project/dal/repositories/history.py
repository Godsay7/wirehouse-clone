"""Port history snapshots and the change log (port_changes).

The collector appends every poll to port_history and records the differences
to the previous poll in port_changes. HISTORY_CHANGES_QUERY derives the same
changes from port_history; it scans millions of rows and is only used to
backfill port_changes once (scripts/backfill_port_changes.py).
"""

from .base import Repository


HISTORY_CHANGES_QUERY = """
    WITH h AS (
        SELECT
            id,
            switch_id,
            port,
            device,
            speed,
            link,
            mac,
            if_index,
            if_name,
            collected_at,

            LAG(id) OVER (
                PARTITION BY switch_id, port
                ORDER BY collected_at, id
            ) AS previous_id,

            LAG(device) OVER (
                PARTITION BY switch_id, port
                ORDER BY collected_at, id
            ) AS old_device,

            LAG(speed) OVER (
                PARTITION BY switch_id, port
                ORDER BY collected_at, id
            ) AS old_speed,

            LAG(link) OVER (
                PARTITION BY switch_id, port
                ORDER BY collected_at, id
            ) AS old_link,

            LAG(mac) OVER (
                PARTITION BY switch_id, port
                ORDER BY collected_at, id
            ) AS old_mac

        FROM port_history
    ),

    changes AS (
        SELECT
            id,
            switch_id,
            port,
            'Device' AS change_type,
            old_device AS old_value,
            device AS new_value,
            if_index,
            if_name,
            collected_at AS detected_at
        FROM h
        WHERE previous_id IS NOT NULL
          AND COALESCE(old_device, '') != COALESCE(device, '')

        UNION ALL

        SELECT
            id,
            switch_id,
            port,
            'Speed' AS change_type,
            old_speed AS old_value,
            speed AS new_value,
            if_index,
            if_name,
            collected_at AS detected_at
        FROM h
        WHERE previous_id IS NOT NULL
          AND COALESCE(old_speed, '') != COALESCE(speed, '')

        UNION ALL

        SELECT
            id,
            switch_id,
            port,
            'Link' AS change_type,
            old_link AS old_value,
            link AS new_value,
            if_index,
            if_name,
            collected_at AS detected_at
        FROM h
        WHERE previous_id IS NOT NULL
          AND COALESCE(old_link, '') != COALESCE(link, '')

        UNION ALL

        SELECT
            id,
            switch_id,
            port,
            'MAC' AS change_type,
            old_mac AS old_value,
            mac AS new_value,
            if_index,
            if_name,
            collected_at AS detected_at
        FROM h
        WHERE previous_id IS NOT NULL
          AND COALESCE(old_mac, '') != COALESCE(mac, '')
    )

    SELECT
        c.id,
        c.switch_id,
        s.host,
        c.port,
        c.change_type,
        c.old_value,
        c.new_value,
        c.if_index,
        c.if_name,
        c.detected_at,
        c.detected_at AS collected_at,
        c.detected_at AS changed_at

    FROM changes c
    JOIN switches s
        ON s.id = c.switch_id
"""


class HistoryRepository(Repository):

    def insert_port_snapshot(self, switch_id, port, collected_at):
        """Append one collector port dict to port_history; return its id."""

        cursor = self._execute(
            """
            INSERT INTO port_history (
                switch_id,
                port,
                device,
                speed,
                link,
                mac,
                if_index,
                if_name,
                collected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                switch_id,
                port["Port"],
                port["Device"],
                port["Speed"],
                port["Link"],
                port["MAC"],
                port["_ifIndex"],
                port["_ifName"],
                collected_at,
            ),
        )
        return cursor.lastrowid

    def list_changes(self, search="", limit=500):
        """Port changes, newest first (columns as Change History expects)."""

        query = """
            SELECT
                COALESCE(c.history_id, c.id) AS id,
                c.switch_id,
                s.host,
                c.port,
                c.change_type,
                c.old_value,
                c.new_value,
                c.if_index,
                c.if_name,
                c.detected_at,
                c.detected_at AS collected_at,
                c.detected_at AS changed_at
            FROM port_changes c
            JOIN switches s
                ON s.id = c.switch_id
        """
        parameters = []

        if search:
            pattern = f"%{search}%"
            query += """
            WHERE
                s.host LIKE ?
                OR CAST(c.port AS TEXT) LIKE ?
                OR c.change_type LIKE ?
                OR COALESCE(c.old_value, '') LIKE ?
                OR COALESCE(c.new_value, '') LIKE ?
                OR COALESCE(c.if_name, '') LIKE ?
            """
            parameters = [pattern] * 6

        query += """
            ORDER BY
                c.detected_at DESC,
                COALESCE(c.history_id, c.id) DESC
            LIMIT ?
        """

        return self._all(query, (*parameters, limit))

    def insert_change(self, switch_id, port, change_type, old_value, new_value, detected_at, history_id):
        """``port`` is the collector port dict (Port/_ifIndex/_ifName)."""

        self._execute(
            """
            INSERT INTO port_changes (
                switch_id,
                port,
                change_type,
                old_value,
                new_value,
                if_index,
                if_name,
                detected_at,
                history_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                switch_id,
                port["Port"],
                change_type,
                old_value,
                new_value,
                port["_ifIndex"],
                port["_ifName"],
                detected_at,
                history_id,
            ),
        )

    # --------------------------------------------------------
    # Retention
    # --------------------------------------------------------

    def last_history_id_before(self, cutoff):
        """Largest port_history id collected before ``cutoff``, or None.

        Rows are appended in time order, so ids grow with collected_at. A
        binary search over the primary key avoids scanning millions of rows
        (collected_at has no index).
        """

        bounds = self._one("SELECT MIN(id), MAX(id) FROM port_history")
        low, high = bounds[0], bounds[1]

        if low is None:
            return None

        def collected_at_from(row_id):
            row = self._one(
                "SELECT collected_at FROM port_history WHERE id >= ? ORDER BY id LIMIT 1",
                (row_id,),
            )
            return row[0] if row else None

        if collected_at_from(low) >= cutoff:
            return None

        # Invariant: the row at/after ``low`` is older than the cutoff.
        while low < high:
            middle = (low + high + 1) // 2
            if collected_at_from(middle) < cutoff:
                low = middle
            else:
                high = middle - 1

        return low

    def delete_history_up_to(self, last_id, batch_size, max_rows):
        """Delete port_history rows with id <= last_id in committed batches.

        Stops after the batch that reaches ``max_rows``; returns the number
        of deleted rows.
        """

        first = self._one("SELECT MIN(id) FROM port_history")[0]
        deleted = 0

        while first is not None and first <= last_id and deleted < max_rows:
            batch_end = min(last_id, first + batch_size - 1)
            cursor = self._execute(
                "DELETE FROM port_history WHERE id BETWEEN ? AND ?",
                (first, batch_end),
            )
            self.connection.commit()
            deleted += cursor.rowcount
            first = batch_end + 1

        return deleted

    # --------------------------------------------------------
    # One port (port history page), newest first:
    # since <= detected_at < before (either may be None); limit None = all
    # --------------------------------------------------------

    def port_changes(self, switch_id, port, before=None, since=None, limit=200):
        return self._dicts(
            """
            SELECT change_type, old_value, new_value, detected_at
            FROM port_changes
            WHERE switch_id = ? AND port = ?
              AND (? IS NULL OR detected_at < ?) AND (? IS NULL OR detected_at >= ?)
            ORDER BY detected_at DESC, id DESC
            LIMIT ?
            """,
            (switch_id, port, before, before, since, since, -1 if limit is None else limit),
        )

    def port_error_events(self, switch_id, port, before=None, since=None, limit=200):
        return self._dicts(
            """
            SELECT detected_at, in_errors, out_errors, fcs_errors
            FROM port_error_events
            WHERE switch_id = ? AND port = ?
              AND (? IS NULL OR detected_at < ?) AND (? IS NULL OR detected_at >= ?)
            ORDER BY detected_at DESC, id DESC
            LIMIT ?
            """,
            (switch_id, port, before, before, since, since, -1 if limit is None else limit),
        )

    def insert_device_change(self, switch_id, port, old_macs, new_macs, detected_at):
        """``port`` is the collector port dict (Port/_ifName)."""

        self._execute(
            """
            INSERT INTO port_device_changes (switch_id, port, if_name, old_macs, new_macs, detected_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (switch_id, port["Port"], port.get("_ifName"), ", ".join(old_macs), ", ".join(new_macs), detected_at),
        )

    def delete_device_changes_before(self, cutoff):
        try:
            cursor = self._execute("DELETE FROM port_device_changes WHERE detected_at < ?", (cutoff,))
        except Exception as exc:              # noqa: BLE001 — table created by a newer schema
            if "no such table" in str(exc):
                return 0
            raise
        self.connection.commit()
        return cursor.rowcount

    def delete_error_events_before(self, cutoff):
        cursor = self._execute("DELETE FROM port_error_events WHERE detected_at < ?", (cutoff,))
        self.connection.commit()
        return cursor.rowcount

    def delete_changes_before(self, cutoff):
        cursor = self._execute(
            "DELETE FROM port_changes WHERE detected_at < ?",
            (cutoff,),
        )
        self.connection.commit()
        return cursor.rowcount

    # --------------------------------------------------------
    # One-time backfill from port_history
    # --------------------------------------------------------

    def earliest_recorded_change(self):
        row = self._one("SELECT MIN(detected_at) FROM port_changes")
        return row[0] if row else None

    def changes_from_history(self, before=None):
        """All changes derived from port_history, oldest first (slow)."""

        query = HISTORY_CHANGES_QUERY
        parameters = ()

        if before:
            query += " WHERE c.detected_at < ?"
            parameters = (before,)

        return self._all(query + " ORDER BY c.detected_at, c.id", parameters)

    def insert_backfilled_changes(self, rows):
        self.connection.executemany(
            """
            INSERT INTO port_changes (
                switch_id, port, change_type, old_value, new_value,
                if_index, if_name, detected_at, history_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["switch_id"], row["port"], row["change_type"],
                    row["old_value"], row["new_value"], row["if_index"],
                    row["if_name"], row["detected_at"], row["id"],
                )
                for row in rows
            ],
        )
