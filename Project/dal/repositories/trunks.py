"""Trunk cables between ODF panels: a range of ports on one panel spliced to
a range on another (usually in another room)."""

from .base import Repository

TRUNK_COLUMNS = "id, panel_a_id, port_a_start, panel_b_id, port_b_start, port_count, name"


class TrunkRepository(Repository):

    def list_all(self):
        return self._dicts(f"SELECT {TRUNK_COLUMNS} FROM trunk_cables ORDER BY id")

    def list_for_panels(self, panel_ids):
        panel_ids = list(panel_ids)
        if not panel_ids:
            return []
        marks = ", ".join("?" for _ in panel_ids)
        return self._dicts(
            f"SELECT {TRUNK_COLUMNS} FROM trunk_cables WHERE panel_a_id IN ({marks}) OR panel_b_id IN ({marks}) ORDER BY id",
            (*panel_ids, *panel_ids),
        )

    def get(self, trunk_id):
        row = self._one(f"SELECT {TRUNK_COLUMNS} FROM trunk_cables WHERE id = ?", (trunk_id,))
        return dict(row) if row is not None else None

    def create(self, panel_a_id, port_a_start, panel_b_id, port_b_start, port_count, name, now):
        cursor = self._execute(
            """
            INSERT INTO trunk_cables (panel_a_id, port_a_start, panel_b_id, port_b_start, port_count, name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (panel_a_id, port_a_start, panel_b_id, port_b_start, port_count, name, now),
        )
        return cursor.lastrowid

    def delete(self, trunk_id):
        self._execute("DELETE FROM trunk_cables WHERE id = ?", (trunk_id,))

    def odf_panels(self):
        """Every ODF with its room and rack, for the "trunk to" picker."""

        return self._dicts(
            """
            SELECT pp.id, pp.name, pp.port_count, pp.rack_unit, pp.side,
                   r.id AS rack_id, r.name AS rack, sr.id AS room_id, sr.name AS room
            FROM patch_panels pp
            JOIN racks r ON r.id = pp.rack_id
            JOIN server_rooms sr ON sr.id = r.server_room_id
            WHERE pp.patch_type = 'odf'
            ORDER BY sr.name, r.name, pp.rack_unit DESC, pp.name
            """
        )
