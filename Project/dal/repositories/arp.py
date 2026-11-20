"""Current MAC -> IP -> hostname snapshot learned from the L3 core."""

from .base import Repository


class ArpRepository(Repository):

    def list_newest_first(self):
        return self._all(
            """
            SELECT
                mac,
                ip,
                hostname,
                if_index,
                last_seen
            FROM arp_entries
            ORDER BY
                last_seen DESC,
                ip
            """
        )

    def first_seen_by_key(self):
        return {
            (mac, ip): first_seen
            for mac, ip, first_seen in self._all(
                "SELECT mac, ip, first_seen FROM arp_entries"
            )
        }

    def replace_all(self, entries):
        """Replace the whole table.

        ``entries`` are dicts with mac, ip, hostname, if_index, first_seen, last_seen.
        """

        self._execute("DELETE FROM arp_entries")

        for entry in entries:
            self._execute(
                """
                INSERT INTO arp_entries (
                    mac, ip, hostname, if_index, first_seen, last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["mac"],
                    entry["ip"],
                    entry["hostname"],
                    entry.get("if_index"),
                    entry["first_seen"],
                    entry["last_seen"],
                ),
            )
