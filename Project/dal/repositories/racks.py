"""Server rooms, racks and the Rack View board order."""

from .base import Repository


class RackRepository(Repository):

    # --------------------------------------------------------
    # Server rooms
    # --------------------------------------------------------

    def list_rooms(self):
        return self._dicts(
            """
            SELECT
                sr.id,
                sr.name,
                sr.description,
                (
                    SELECT r.id
                    FROM racks r
                    WHERE r.server_room_id = sr.id
                    ORDER BY r.name, r.id
                    LIMIT 1
                ) AS first_rack_id
            FROM server_rooms sr
            ORDER BY sr.name
            """
        )

    def get_room(self, room_id):
        return self._one(
            "SELECT id, name FROM server_rooms WHERE id = ?",
            (room_id,),
        )

    def find_room_id_by_name(self, name):
        row = self._one(
            "SELECT id FROM server_rooms WHERE name = ?",
            (name,),
        )
        return row[0] if row else None

    def create_room(self, name, created_at):
        cursor = self._execute(
            """
            INSERT INTO server_rooms (name, description, created_at)
            VALUES (?, NULL, ?)
            """,
            (name, created_at),
        )
        return cursor.lastrowid

    def first_room_id(self):
        row = self._one(
            "SELECT id FROM server_rooms ORDER BY name, id LIMIT 1"
        )
        return row[0] if row else None

    def delete_room_with_contents(self, room_id):
        """Delete one room and only its rack-layout metadata.

        SNMP inventory tables (switches/ports/history/ARP) are never deleted.
        """

        self._execute(
            """
            DELETE FROM port_connections
            WHERE (endpoint_a_type = 'patch' AND endpoint_a_id IN (
                    SELECT pp.id FROM patch_panels pp
                    JOIN racks r ON r.id = pp.rack_id
                    WHERE r.server_room_id = ?
                  ))
               OR (endpoint_b_type = 'patch' AND endpoint_b_id IN (
                    SELECT pp.id FROM patch_panels pp
                    JOIN racks r ON r.id = pp.rack_id
                    WHERE r.server_room_id = ?
                  ))
               OR (endpoint_a_type = 'switch' AND endpoint_a_id IN (
                    SELECT rs.switch_id FROM rack_switches rs
                    JOIN racks r ON r.id = rs.rack_id
                    WHERE r.server_room_id = ?
                  ))
               OR (endpoint_b_type = 'switch' AND endpoint_b_id IN (
                    SELECT rs.switch_id FROM rack_switches rs
                    JOIN racks r ON r.id = rs.rack_id
                    WHERE r.server_room_id = ?
                  ))
               OR (endpoint_a_type = 'server' AND endpoint_a_id IN (
                    SELECT sv.id FROM servers sv
                    JOIN racks r ON r.id = sv.rack_id
                    WHERE r.server_room_id = ?
                  ))
               OR (endpoint_b_type = 'server' AND endpoint_b_id IN (
                    SELECT sv.id FROM servers sv
                    JOIN racks r ON r.id = sv.rack_id
                    WHERE r.server_room_id = ?
                  ))
               OR (endpoint_a_type = 'placeholder' AND endpoint_a_id IN (
                    SELECT ph.id FROM rack_switch_placeholders ph
                    JOIN racks r ON r.id = ph.rack_id
                    WHERE r.server_room_id = ?
                  ))
               OR (endpoint_b_type = 'placeholder' AND endpoint_b_id IN (
                    SELECT ph.id FROM rack_switch_placeholders ph
                    JOIN racks r ON r.id = ph.rack_id
                    WHERE r.server_room_id = ?
                  ))
            """,
            (room_id, room_id, room_id, room_id, room_id, room_id, room_id, room_id),
        )

        self._execute(
            """
            DELETE FROM placeholder_ports WHERE placeholder_id IN (
                SELECT ph.id FROM rack_switch_placeholders ph
                JOIN racks r ON r.id = ph.rack_id
                WHERE r.server_room_id = ?
            )
            """,
            (room_id,),
        )

        self._execute(
            """
            DELETE FROM patch_connections
            WHERE patch_panel_a_id IN (
                SELECT pp.id
                FROM patch_panels pp
                JOIN racks r ON r.id = pp.rack_id
                WHERE r.server_room_id = ?
            )
               OR patch_panel_b_id IN (
                SELECT pp.id
                FROM patch_panels pp
                JOIN racks r ON r.id = pp.rack_id
                WHERE r.server_room_id = ?
            )
            """,
            (room_id, room_id),
        )

        self._execute(
            """
            DELETE FROM trunk_cables
            WHERE panel_a_id IN (SELECT pp.id FROM patch_panels pp JOIN racks r ON r.id = pp.rack_id WHERE r.server_room_id = ?)
               OR panel_b_id IN (SELECT pp.id FROM patch_panels pp JOIN racks r ON r.id = pp.rack_id WHERE r.server_room_id = ?)
            """,
            (room_id, room_id),
        )

        self._execute(
            """
            DELETE FROM patch_ports
            WHERE patch_panel_id IN (
                SELECT pp.id
                FROM patch_panels pp
                JOIN racks r ON r.id = pp.rack_id
                WHERE r.server_room_id = ?
            )
            """,
            (room_id,),
        )

        self._execute(
            """
            DELETE FROM server_ports
            WHERE server_id IN (
                SELECT sv.id
                FROM servers sv
                JOIN racks r ON r.id = sv.rack_id
                WHERE r.server_room_id = ?
            )
            """,
            (room_id,),
        )

        for table in (
            "servers",
            "rack_switch_placeholders",
            "patch_panels",
            "cable_organizers",
            "rack_switches",
        ):
            self._execute(
                f"""
                DELETE FROM {table}
                WHERE rack_id IN (
                    SELECT id FROM racks WHERE server_room_id = ?
                )
                """,
                (room_id,),
            )

        self._execute(
            "DELETE FROM rack_view_order WHERE server_room_id = ?",
            (room_id,),
        )
        self._execute(
            "DELETE FROM rack_view_slots WHERE server_room_id = ?",
            (room_id,),
        )
        self._execute(
            "DELETE FROM racks WHERE server_room_id = ?",
            (room_id,),
        )
        self._execute(
            "DELETE FROM server_rooms WHERE id = ?",
            (room_id,),
        )

    # --------------------------------------------------------
    # Racks
    # --------------------------------------------------------

    def list_room_racks(self, server_room_id):
        return self._dicts(
            """
            SELECT
                r.id,
                r.server_room_id,
                r.name,
                r.location,
                r.units,
                COALESCE(r.width_percent, 100) AS width_percent,
                rvo.position_index AS view_position
            FROM racks r
            LEFT JOIN rack_view_order rvo
                ON rvo.rack_id = r.id
               AND rvo.server_room_id = r.server_room_id
            WHERE r.server_room_id = ?
            ORDER BY
                CASE WHEN rvo.position_index IS NULL THEN 1 ELSE 0 END,
                rvo.position_index,
                r.name,
                r.id
            """,
            (server_room_id,),
        )

    def list_room_rack_ids(self, server_room_id):
        return [
            int(row["id"])
            for row in self._all(
                """
                SELECT id
                FROM racks
                WHERE server_room_id = ?
                ORDER BY name, id
                """,
                (server_room_id,),
            )
        ]

    def get(self, rack_id):
        return self._one(
            "SELECT id, server_room_id, name FROM racks WHERE id = ?",
            (rack_id,),
        )

    def get_units(self, rack_id):
        return self._one(
            "SELECT id, units FROM racks WHERE id = ?",
            (rack_id,),
        )

    def set_width(self, rack_id, width_percent):
        return self._execute("UPDATE racks SET width_percent = ? WHERE id = ?", (width_percent, rack_id)).rowcount

    def get_with_room(self, rack_id):
        return self._one(
            """
            SELECT r.id, r.server_room_id, r.name, r.location, r.units, sr.name AS server_room_name,
                   COALESCE(r.width_percent, 100) AS width_percent
            FROM racks r
            JOIN server_rooms sr ON sr.id = r.server_room_id
            WHERE r.id = ?
            """,
            (rack_id,),
        )

    def create(self, server_room_id, name, units, created_at):
        cursor = self._execute(
            """
            INSERT INTO racks (
                server_room_id,
                name,
                location,
                units,
                created_at
            )
            VALUES (?, ?, NULL, ?, ?)
            """,
            (server_room_id, name, units, created_at),
        )
        return cursor.lastrowid

    def first_rack_id_in_room(self, server_room_id):
        row = self._one(
            "SELECT id FROM racks WHERE server_room_id = ? ORDER BY name, id LIMIT 1",
            (server_room_id,),
        )
        return row[0] if row else None

    def delete_with_contents(self, rack_id):
        self._execute("""
            DELETE FROM port_connections
            WHERE (endpoint_a_type = 'patch' AND endpoint_a_id IN (SELECT id FROM patch_panels WHERE rack_id = ?))
               OR (endpoint_b_type = 'patch' AND endpoint_b_id IN (SELECT id FROM patch_panels WHERE rack_id = ?))
               OR (endpoint_a_type = 'switch' AND endpoint_a_id IN (SELECT switch_id FROM rack_switches WHERE rack_id = ?))
               OR (endpoint_b_type = 'switch' AND endpoint_b_id IN (SELECT switch_id FROM rack_switches WHERE rack_id = ?))
               OR (endpoint_a_type = 'server' AND endpoint_a_id IN (SELECT id FROM servers WHERE rack_id = ?))
               OR (endpoint_b_type = 'server' AND endpoint_b_id IN (SELECT id FROM servers WHERE rack_id = ?))
               OR (endpoint_a_type = 'placeholder' AND endpoint_a_id IN (SELECT id FROM rack_switch_placeholders WHERE rack_id = ?))
               OR (endpoint_b_type = 'placeholder' AND endpoint_b_id IN (SELECT id FROM rack_switch_placeholders WHERE rack_id = ?))
        """, (rack_id, rack_id, rack_id, rack_id, rack_id, rack_id, rack_id, rack_id))
        self._execute(
            "DELETE FROM placeholder_ports WHERE placeholder_id IN (SELECT id FROM rack_switch_placeholders WHERE rack_id = ?)",
            (rack_id,),
        )

        self._execute("DELETE FROM patch_ports WHERE patch_panel_id IN (SELECT id FROM patch_panels WHERE rack_id = ?)", (rack_id,))
        self._execute("DELETE FROM server_ports WHERE server_id IN (SELECT id FROM servers WHERE rack_id = ?)", (rack_id,))

        self._execute("DELETE FROM servers WHERE rack_id = ?", (rack_id,))
        self._execute("DELETE FROM rack_switch_placeholders WHERE rack_id = ?", (rack_id,))
        self._execute(
            """
            DELETE FROM trunk_cables
            WHERE panel_a_id IN (SELECT id FROM patch_panels WHERE rack_id = ?)
               OR panel_b_id IN (SELECT id FROM patch_panels WHERE rack_id = ?)
            """,
            (rack_id, rack_id),
        )
        self._execute("DELETE FROM patch_panels WHERE rack_id = ?", (rack_id,))
        self._execute("DELETE FROM cable_organizers WHERE rack_id = ?", (rack_id,))
        self._execute("DELETE FROM rack_switches WHERE rack_id = ?", (rack_id,))
        self._execute("DELETE FROM racks WHERE id = ?", (rack_id,))

    # --------------------------------------------------------
    # Rack View board order
    # --------------------------------------------------------

    def board_layout(self, server_room_id):
        """("grid" | "custom", set of empty-or-occupied slot positions kept on the board)."""

        row = self._one("SELECT board_layout FROM server_rooms WHERE id = ?", (server_room_id,))
        layout = (row["board_layout"] if row is not None else None) or "grid"
        positions = {
            int(r["position_index"])
            for r in self._all("SELECT position_index FROM rack_view_slots WHERE server_room_id = ?", (server_room_id,))
        }
        return layout, positions

    def set_board_layout(self, server_room_id, layout, positions=()):
        self._execute("UPDATE server_rooms SET board_layout = ? WHERE id = ?", (layout, server_room_id))
        self._execute("DELETE FROM rack_view_slots WHERE server_room_id = ?", (server_room_id,))
        for position in sorted(set(positions)):
            self._execute(
                "INSERT INTO rack_view_slots (server_room_id, position_index) VALUES (?, ?)",
                (server_room_id, int(position)),
            )

    def clear_view_order(self, server_room_id):
        self._execute(
            "DELETE FROM rack_view_order WHERE server_room_id = ?",
            (server_room_id,),
        )

    def add_view_position(self, server_room_id, rack_id, position_index, updated_at):
        self._execute(
            """
            INSERT INTO rack_view_order (
                server_room_id, rack_id, position_index, updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (server_room_id, rack_id, position_index, updated_at),
        )
