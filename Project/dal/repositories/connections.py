"""Cables between rack endpoints.

port_connections   generic switch/patch/server <-> switch/patch/server links
                   (referenced in the UI as "sp-<id>").
patch_connections  legacy patch-panel <-> patch-panel links ("pp-<id>").
"""

from .base import Repository


class ConnectionRepository(Repository):

    def list_port_connections(self):
        return self._dicts("SELECT * FROM port_connections ORDER BY id")

    def cabled_switch_ports(self, switch_id):
        """Ports of one switch with a documented cable (either end)."""

        rows = self.connection.execute(
            """
            SELECT endpoint_a_port AS port FROM port_connections
            WHERE endpoint_a_type = 'switch' AND endpoint_a_id = ?
            UNION
            SELECT endpoint_b_port FROM port_connections
            WHERE endpoint_b_type = 'switch' AND endpoint_b_id = ?
            """,
            (switch_id, switch_id),
        ).fetchall()
        return {row[0] for row in rows}

    def list_patch_connections(self):
        return self._dicts("SELECT * FROM patch_connections ORDER BY id")

    def list_patch_connections_for_rack_side(self, rack_id, side):
        return self._dicts(
            """
            SELECT pc.*,
                   ppa.name AS patch_a_name, ppa.patch_type AS patch_a_type, ppa.rack_id AS patch_a_rack_id, ppa.side AS patch_a_side, ra.name AS patch_a_rack_name, sra.name AS patch_a_server_room_name,
                   ppb.name AS patch_b_name, ppb.patch_type AS patch_b_type, ppb.rack_id AS patch_b_rack_id, ppb.side AS patch_b_side, rb.name AS patch_b_rack_name, srb.name AS patch_b_server_room_name
            FROM patch_connections pc
            JOIN patch_panels ppa ON ppa.id = pc.patch_panel_a_id
            JOIN racks ra ON ra.id = ppa.rack_id
            JOIN server_rooms sra ON sra.id = ra.server_room_id
            JOIN patch_panels ppb ON ppb.id = pc.patch_panel_b_id
            JOIN racks rb ON rb.id = ppb.rack_id
            JOIN server_rooms srb ON srb.id = rb.server_room_id
            WHERE (ppa.rack_id = ? AND ppa.side = ?) OR (ppb.rack_id = ? AND ppb.side = ?)
            ORDER BY pc.id
            """,
            (rack_id, side, rack_id, side),
        )

    def cords_at(self, endpoint):
        """Links plugged into one port: [((type, id, port), link_info), ...]."""

        endpoint_type, endpoint_id, port = endpoint
        cords = []

        for row in self._dicts(
            """
            SELECT * FROM port_connections
            WHERE (endpoint_a_type = ? AND endpoint_a_id = ? AND endpoint_a_port = ?)
               OR (endpoint_b_type = ? AND endpoint_b_id = ? AND endpoint_b_port = ?)
            ORDER BY id
            """,
            (endpoint_type, endpoint_id, port, endpoint_type, endpoint_id, port),
        ):
            a = (row["endpoint_a_type"], row["endpoint_a_id"], row["endpoint_a_port"])
            b = (row["endpoint_b_type"], row["endpoint_b_id"], row["endpoint_b_port"])
            cords.append((b if a == tuple(endpoint) else a, {
                "connection_ref": f"sp-{row['id']}",
                "cable_label": row.get("cable_label"),
            }))

        if endpoint_type == "patch":
            for row in self._dicts(
                """
                SELECT * FROM patch_connections
                WHERE (patch_panel_a_id = ? AND patch_port_a = ?)
                   OR (patch_panel_b_id = ? AND patch_port_b = ?)
                ORDER BY id
                """,
                (endpoint_id, port, endpoint_id, port),
            ):
                a = ("patch", row["patch_panel_a_id"], row["patch_port_a"])
                b = ("patch", row["patch_panel_b_id"], row["patch_port_b"])
                cords.append((b if a == tuple(endpoint) else a, {
                    "connection_ref": f"pp-{row['id']}",
                    "cable_label": row.get("cable_label"),
                }))

        return cords

    def create(self, endpoint_a, endpoint_b, cable_type, now):
        """Create a link; endpoints are (type, id, port) tuples. Returns its id."""

        t1, id1, p1 = endpoint_a
        t2, id2, p2 = endpoint_b

        cursor = self._execute("""
            INSERT INTO port_connections (
                endpoint_a_type, endpoint_a_id, endpoint_a_port,
                endpoint_b_type, endpoint_b_id, endpoint_b_port,
                cable_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (t1, id1, p1, t2, id2, p2, cable_type, now, now))

        return cursor.lastrowid

    def delete_touching_ports(self, endpoint_a, endpoint_b):
        """Remove every existing link that uses either of the two ports."""

        t1, id1, p1 = endpoint_a
        t2, id2, p2 = endpoint_b

        self._execute("""
            DELETE FROM port_connections
            WHERE (endpoint_a_type = ? AND endpoint_a_id = ? AND endpoint_a_port = ?)
               OR (endpoint_b_type = ? AND endpoint_b_id = ? AND endpoint_b_port = ?)
               OR (endpoint_a_type = ? AND endpoint_a_id = ? AND endpoint_a_port = ?)
               OR (endpoint_b_type = ? AND endpoint_b_id = ? AND endpoint_b_port = ?)
        """, (t1, id1, p1, t1, id1, p1, t2, id2, p2, t2, id2, p2))

    def delete_for_endpoint(self, endpoint_type, endpoint_id):
        self._execute(
            "DELETE FROM port_connections WHERE (endpoint_a_type = ? AND endpoint_a_id = ?) OR (endpoint_b_type = ? AND endpoint_b_id = ?)",
            (endpoint_type, endpoint_id, endpoint_type, endpoint_id),
        )

    def delete_for_endpoint_port(self, endpoint_type, endpoint_id, port):
        self._execute(
            "DELETE FROM port_connections WHERE (endpoint_a_type = ? AND endpoint_a_id = ? AND endpoint_a_port = ?) OR (endpoint_b_type = ? AND endpoint_b_id = ? AND endpoint_b_port = ?)",
            (endpoint_type, endpoint_id, port, endpoint_type, endpoint_id, port),
        )

    def delete_port_connection(self, connection_id):
        self._execute("DELETE FROM port_connections WHERE id = ?", (connection_id,))

    def delete_patch_connection(self, connection_id):
        self._execute("DELETE FROM patch_connections WHERE id = ?", (connection_id,))
