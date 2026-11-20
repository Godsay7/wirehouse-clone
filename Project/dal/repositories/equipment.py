"""Equipment mounted in racks: servers, switches, temporary switches,
patch panels and cable organizers."""

from .base import Repository


class EquipmentRepository(Repository):

    # --------------------------------------------------------
    # Occupancy (rack unit collision checks)
    # --------------------------------------------------------

    def switch_placements(self, rack_id, side):
        return self._all(
            """
            SELECT
                rs.rack_unit,
                COALESCE(rs.height_units, 1) AS height_units,
                s.host,
                rs.switch_id
            FROM rack_switches rs
            JOIN switches s ON s.id = rs.switch_id
            WHERE rs.rack_id = ? AND rs.side = ?
            """,
            (rack_id, side),
        )

    def placeholder_placements(self, rack_id, side):
        return self._all(
            """
            SELECT rack_unit, COALESCE(height_units, 1) AS height_units, id
            FROM rack_switch_placeholders
            WHERE rack_id = ? AND side = ?
            """,
            (rack_id, side),
        )

    def patch_panel_placements(self, rack_id, side):
        return self._all(
            """
            SELECT rack_unit, id
            FROM patch_panels
            WHERE rack_id = ? AND side = ?
            """,
            (rack_id, side),
        )

    def organizer_placements(self, rack_id, side):
        return self._all(
            """
            SELECT rack_unit, COALESCE(height_units, 1) AS height_units, id
            FROM cable_organizers
            WHERE rack_id = ? AND side = ?
            """,
            (rack_id, side),
        )

    def server_placements(self, rack_id, side=None):
        """Units taken by servers on one side: full-depth servers take both
        sides, half-depth ones only their own. side=None: every server."""

        if side is None:
            return self._all(
                "SELECT rack_unit, COALESCE(height_units, 1) AS height_units, id FROM servers WHERE rack_id = ?",
                (rack_id,),
            )
        return self._all(
            """
            SELECT rack_unit, COALESCE(height_units, 1) AS height_units, id
            FROM servers
            WHERE rack_id = ? AND (COALESCE(depth, 'full') = 'full' OR side = ?)
            """,
            (rack_id, side),
        )

    # --------------------------------------------------------
    # Servers
    # --------------------------------------------------------

    def list_servers(self, rack_id, side=None):
        """Servers of a rack; with side, only those seen from that side."""

        # The front picture itself is served by its own URL (front_image);
        # here only a version of it: its size and its last characters change
        # with every new picture. NULL when there is none.
        query = (
            "SELECT id, rack_id, name, rack_unit, height_units, side, COALESCE(depth, 'full') AS depth, "
            "CASE WHEN front_image IS NULL OR front_image = '' THEN NULL "
            "ELSE length(front_image) || '-' || hex(substr(front_image, -6)) END AS front_image_version "
            "FROM servers WHERE rack_id = ?"
        )
        if side is None:
            return self._dicts(query, (rack_id,))
        return self._dicts(query + " AND (COALESCE(depth, 'full') = 'full' OR side = ?)", (rack_id, side))

    def get_server(self, rack_id, server_id):
        row = self._one(
            "SELECT id, rack_id, name, rack_unit, height_units, side, COALESCE(depth, 'full') AS depth FROM servers WHERE id = ? AND rack_id = ?",
            (server_id, rack_id),
        )
        return dict(row) if row is not None else None

    def move_server(self, rack_id, server_id, bottom_unit):
        self._execute("UPDATE servers SET rack_unit = ? WHERE rack_id = ? AND id = ?", (bottom_unit, rack_id, server_id))

    def get_patch_panel(self, rack_id, panel_id):
        row = self._one("SELECT id, rack_id, name, rack_unit, side FROM patch_panels WHERE id = ? AND rack_id = ?",
                        (panel_id, rack_id))
        return dict(row) if row is not None else None

    def move_patch_panel(self, rack_id, panel_id, rack_unit):
        self._execute("UPDATE patch_panels SET rack_unit = ? WHERE rack_id = ? AND id = ?", (rack_unit, rack_id, panel_id))

    def set_server_depth(self, server_id, depth):
        self._execute("UPDATE servers SET depth = ? WHERE id = ?", (depth, server_id))

    def list_server_ports(self, server_id):
        return self._dicts(
            "SELECT id, server_id, port, label FROM server_ports WHERE server_id = ?",
            (server_id,),
        )

    def create_server(self, rack_id, name, rack_unit, height_units, side, created_at, port_count, depth="full"):
        """Create a server with port 0 (mng) and ports 1..port_count-1."""

        cursor = self._execute(
            """
            INSERT INTO servers (rack_id, name, rack_unit, height_units, side, depth, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rack_id, name, rack_unit, height_units, side, depth, created_at),
        )
        server_id = cursor.lastrowid

        self._execute("INSERT INTO server_ports (server_id, port, label) VALUES (?, 0, 'mng')", (server_id,))

        if port_count > 1:
            self.connection.executemany(
                "INSERT INTO server_ports (server_id, port, label) VALUES (?, ?, NULL)",
                [(server_id, p) for p in range(1, port_count)],
            )

        return server_id

    def front_image(self, server_id):
        """The stored front picture (a data: URL), or None."""

        row = self._one("SELECT front_image FROM servers WHERE id = ?", (server_id,))
        return row[0] if row and row[0] else None

    def set_server_front_image(self, server_id, image_data):
        self._execute("UPDATE servers SET front_image = ? WHERE id = ?", (image_data, server_id))

    def delete_server(self, rack_id, server_id):
        self._execute("DELETE FROM server_ports WHERE server_id = ?", (server_id,))
        self._execute("DELETE FROM servers WHERE id = ? AND rack_id = ?", (server_id, rack_id))

    def add_server_port(self, server_id):
        row = self._one("SELECT MAX(port) as max_p FROM server_ports WHERE server_id = ?", (server_id,))
        next_port = (row["max_p"] or 0) + 1
        self._execute("INSERT INTO server_ports (server_id, port, label) VALUES (?, ?, NULL)", (server_id, next_port))

    def delete_server_port(self, server_id, port):
        self._execute("DELETE FROM server_ports WHERE server_id = ? AND port = ?", (server_id, port))

    def set_server_port_label(self, server_id, port, label):
        self._execute("UPDATE server_ports SET label = ? WHERE server_id = ? AND port = ?", (label, server_id, port))

    # --------------------------------------------------------
    # SNMP switches mounted in racks
    # --------------------------------------------------------

    def list_rack_switches(self, rack_id, side):
        return self._dicts(
            """
            SELECT rs.id AS rack_switch_id, rs.rack_unit, rs.height_units, rs.side, rs.mgmt_port,
                   s.id AS switch_id, s.host, s.sys_name, s.model, s.last_seen
            FROM rack_switches rs
            JOIN switches s ON s.id = rs.switch_id
            WHERE rs.rack_id = ? AND rs.side = ?
            ORDER BY rs.rack_unit DESC, s.host
            """,
            (rack_id, side),
        )

    def mounted_switch_ids(self):
        return {
            row["switch_id"]
            for row in self._all("SELECT DISTINCT switch_id FROM rack_switches")
        }

    def is_switch_mounted(self, switch_id):
        return self._one(
            """
            SELECT 1
            FROM rack_switches
            WHERE switch_id = ?
            LIMIT 1
            """,
            (switch_id,),
        ) is not None

    def mount_switch(self, rack_id, switch_id, rack_unit, height_units, side):
        self._execute(
            """
            INSERT INTO rack_switches (
                rack_id,
                switch_id,
                rack_unit,
                height_units,
                side
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (rack_id, switch_id, rack_unit, height_units, side),
        )

    def get_rack_switch(self, rack_id, switch_id):
        row = self._one(
            """
            SELECT rs.rack_unit, COALESCE(rs.height_units, 1) AS height_units, rs.side, s.host
            FROM rack_switches rs
            JOIN switches s ON s.id = rs.switch_id
            WHERE rs.rack_id = ? AND rs.switch_id = ?
            """,
            (rack_id, switch_id),
        )
        return dict(row) if row else None

    def set_switch_mgmt_port(self, rack_id, switch_id, enabled):
        self._execute(
            "UPDATE rack_switches SET mgmt_port = ? WHERE rack_id = ? AND switch_id = ?",
            (1 if enabled else 0, rack_id, switch_id),
        )

    def move_switch(self, rack_id, switch_id, rack_unit):
        self._execute(
            "UPDATE rack_switches SET rack_unit = ? WHERE rack_id = ? AND switch_id = ?",
            (rack_unit, rack_id, switch_id),
        )

    def move_placeholder(self, rack_id, placeholder_id, rack_unit):
        self._execute(
            "UPDATE rack_switch_placeholders SET rack_unit = ? WHERE rack_id = ? AND id = ?",
            (rack_unit, rack_id, placeholder_id),
        )

    def unmount_switch(self, rack_id, switch_id):
        self._execute("DELETE FROM rack_switches WHERE rack_id = ? AND switch_id = ?", (rack_id, switch_id))

    # --------------------------------------------------------
    # Temporary (placeholder) switches
    # --------------------------------------------------------

    def list_placeholders(self, rack_id, side):
        return self._dicts(
            """
            SELECT id, rack_id, name, model, rack_unit, height_units, port_count, side, created_at
            FROM rack_switch_placeholders
            WHERE rack_id = ? AND side = ?
            ORDER BY rack_unit DESC, name
            """,
            (rack_id, side),
        )

    def create_placeholder(self, rack_id, name, model, rack_unit, height_units, port_count, side, created_at):
        self._execute(
            """
            INSERT INTO rack_switch_placeholders (
                rack_id, name, model, rack_unit, height_units, port_count, side, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rack_id, name, model, rack_unit, height_units, port_count, side, created_at),
        )

    def delete_placeholder(self, rack_id, placeholder_id):
        self._execute(
            "DELETE FROM placeholder_ports WHERE placeholder_id IN "
            "(SELECT id FROM rack_switch_placeholders WHERE id = ? AND rack_id = ?)",
            (placeholder_id, rack_id),
        )
        self._execute(
            "DELETE FROM rack_switch_placeholders WHERE id = ? AND rack_id = ?",
            (placeholder_id, rack_id),
        )

    def get_placeholder(self, placeholder_id):
        row = self._one(
            "SELECT id, rack_id, name, model, rack_unit, height_units, port_count, side FROM rack_switch_placeholders WHERE id = ?",
            (placeholder_id,),
        )
        return dict(row) if row else None

    def placeholder_port_notes(self, placeholder_id):
        return {
            row["port"]: row["description"]
            for row in self._dicts(
                "SELECT port, description FROM placeholder_ports WHERE placeholder_id = ? AND description <> ''",
                (placeholder_id,),
            )
        }

    def set_placeholder_port_description(self, placeholder_id, port, description):
        if description:
            self._execute(
                """
                INSERT INTO placeholder_ports (placeholder_id, port, description) VALUES (?, ?, ?)
                ON CONFLICT (placeholder_id, port) DO UPDATE SET description = excluded.description
                """,
                (placeholder_id, port, description),
            )
        else:
            self._execute("DELETE FROM placeholder_ports WHERE placeholder_id = ? AND port = ?", (placeholder_id, port))

    def placeholder_endpoint_info(self, placeholder_id):
        row = self._one("SELECT name, rack_id, side FROM rack_switch_placeholders WHERE id = ?", (placeholder_id,))
        rack = self._rack_location(row["rack_id"]) if row else None
        return row, rack

    # --------------------------------------------------------
    # Patch panels
    # --------------------------------------------------------

    def list_patch_panels(self, rack_id, side):
        return self._dicts(
            """
            SELECT id, rack_id, name, rack_unit, port_count, patch_type, side, port_layout
            FROM patch_panels
            WHERE rack_id = ? AND side = ?
            ORDER BY rack_unit DESC, name
            """,
            (rack_id, side),
        )

    def list_patch_ports(self, patch_panel_id):
        return self._dicts(
            "SELECT id, patch_panel_id, port, label, description FROM patch_ports WHERE patch_panel_id = ? ORDER BY port",
            (patch_panel_id,),
        )

    def find_patch_type(self, patch_panel_id):
        """Row with patch_type, or None when the panel does not exist."""

        return self._one(
            "SELECT patch_type FROM patch_panels WHERE id = ?",
            (patch_panel_id,),
        )

    def create_patch_panel(self, rack_id, name, rack_unit, port_count, patch_type, side, created_at):
        """Create a panel and its ports 1..port_count."""

        cursor = self._execute(
            """
            INSERT INTO patch_panels (
                rack_id,
                name,
                rack_unit,
                port_count,
                patch_type,
                side,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rack_id, name, rack_unit, port_count, patch_type, side, created_at),
        )
        panel_id = cursor.lastrowid

        self.connection.executemany(
            """
            INSERT INTO patch_ports (
                patch_panel_id,
                port,
                label,
                description
            )
            VALUES (?, ?, NULL, NULL)
            """,
            [
                (panel_id, port_number)
                for port_number in range(1, port_count + 1)
            ],
        )

        return panel_id

    def set_patch_panel_layout(self, rack_id, panel_id, port_layout):
        cursor = self._execute(
            "UPDATE patch_panels SET port_layout = ? WHERE id = ? AND rack_id = ?",
            (port_layout, panel_id, rack_id),
        )
        return cursor.rowcount

    def delete_patch_panel(self, rack_id, panel_id):
        self._execute(
            "DELETE FROM trunk_cables WHERE panel_a_id = ? OR panel_b_id = ?",
            (panel_id, panel_id),
        )
        self._execute("DELETE FROM patch_ports WHERE patch_panel_id = ?", (panel_id,))
        self._execute("DELETE FROM patch_panels WHERE id = ? AND rack_id = ?", (panel_id, rack_id))

    def set_patch_port_description(self, patch_panel_id, port, description):
        self._execute(
            "UPDATE patch_ports SET description = ? WHERE patch_panel_id = ? AND port = ?",
            (description, patch_panel_id, port),
        )

    # --------------------------------------------------------
    # Cable organizers
    # --------------------------------------------------------

    def list_organizers(self, rack_id, side):
        return self._dicts(
            "SELECT id, rack_id, name, rack_unit, height_units, side FROM cable_organizers WHERE rack_id = ? AND side = ? ORDER BY rack_unit DESC, id",
            (rack_id, side),
        )

    def create_organizer(self, rack_id, name, rack_unit, height_units, side, created_at):
        self._execute(
            """
            INSERT INTO cable_organizers (
                rack_id, name, rack_unit, height_units, side, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (rack_id, name, rack_unit, height_units, side, created_at),
        )

    def get_organizer(self, rack_id, organizer_id):
        row = self._one(
            "SELECT id, rack_id, name, rack_unit, COALESCE(height_units, 1) AS height_units, side "
            "FROM cable_organizers WHERE id = ? AND rack_id = ?",
            (organizer_id, rack_id),
        )
        return dict(row) if row is not None else None

    def move_organizer(self, rack_id, organizer_id, bottom_unit):
        self._execute("UPDATE cable_organizers SET rack_unit = ? WHERE rack_id = ? AND id = ?",
                      (bottom_unit, rack_id, organizer_id))

    def delete_organizer(self, rack_id, organizer_id):
        self._execute(
            "DELETE FROM cable_organizers WHERE id = ? AND rack_id = ?",
            (organizer_id, rack_id),
        )

    # --------------------------------------------------------
    # Endpoint labels for connection tooltips
    # --------------------------------------------------------

    def switch_endpoint_info(self, switch_id):
        switch = self._one("SELECT host FROM switches WHERE id = ?", (switch_id,))
        placement = self._one(
            "SELECT r.name, sr.name as room, rs.side FROM rack_switches rs JOIN racks r ON r.id = rs.rack_id JOIN server_rooms sr ON sr.id = r.server_room_id WHERE rs.switch_id = ?",
            (switch_id,),
        )
        return switch, placement

    def patch_endpoint_info(self, patch_panel_id):
        panel = self._one("SELECT name, rack_id, side FROM patch_panels WHERE id = ?", (patch_panel_id,))
        rack = self._rack_location(panel["rack_id"]) if panel else None
        return panel, rack

    def server_endpoint_info(self, server_id):
        server = self._one("SELECT name, rack_id, side FROM servers WHERE id = ?", (server_id,))
        rack = self._rack_location(server["rack_id"]) if server else None
        return server, rack

    def odf_panels(self):
        """Every ODF panel with its server room (input for trunk matching)."""

        return self._dicts(
            """
            SELECT pp.id, pp.name, pp.port_count, r.server_room_id
            FROM patch_panels pp
            JOIN racks r ON r.id = pp.rack_id
            WHERE pp.patch_type = 'odf'
            ORDER BY pp.id
            """
        )

    def endpoint_details(self, endpoint_type, endpoint_id, port):
        """Name, port label and location of one rack port, or None if it is gone."""

        if endpoint_type == "switch":
            row = self._one(
                """
                SELECT s.host AS name, p.if_name AS port_name, p.link,
                       r.name AS rack, sr.name AS room, rs.side
                FROM switches s
                LEFT JOIN ports p ON p.switch_id = s.id AND p.port = ?
                LEFT JOIN rack_switches rs ON rs.switch_id = s.id
                LEFT JOIN racks r ON r.id = rs.rack_id
                LEFT JOIN server_rooms sr ON sr.id = r.server_room_id
                WHERE s.id = ?
                """,
                (port, endpoint_id),
            )
        elif endpoint_type == "patch":
            row = self._one(
                """
                SELECT pp.name, pp.patch_type, pp.side, pt.description,
                       r.name AS rack, sr.name AS room
                FROM patch_panels pp
                JOIN racks r ON r.id = pp.rack_id
                JOIN server_rooms sr ON sr.id = r.server_room_id
                LEFT JOIN patch_ports pt ON pt.patch_panel_id = pp.id AND pt.port = ?
                WHERE pp.id = ?
                """,
                (port, endpoint_id),
            )
        elif endpoint_type == "server":
            row = self._one(
                """
                SELECT s.name, s.side, sp.label AS port_name,
                       r.name AS rack, sr.name AS room
                FROM servers s
                JOIN racks r ON r.id = s.rack_id
                JOIN server_rooms sr ON sr.id = r.server_room_id
                LEFT JOIN server_ports sp ON sp.server_id = s.id AND sp.port = ?
                WHERE s.id = ?
                """,
                (port, endpoint_id),
            )
        elif endpoint_type == "placeholder":
            row = self._one(
                """
                SELECT ph.name, ph.side, pp.description, ph.port_count,
                       r.name AS rack, sr.name AS room
                FROM rack_switch_placeholders ph
                JOIN racks r ON r.id = ph.rack_id
                JOIN server_rooms sr ON sr.id = r.server_room_id
                LEFT JOIN placeholder_ports pp ON pp.placeholder_id = ph.id AND pp.port = ?
                WHERE ph.id = ?
                """,
                (port, endpoint_id),
            )
        else:
            row = None

        return dict(row) if row is not None else None

    def _rack_location(self, rack_id):
        return self._one(
            "SELECT r.name, sr.name as room FROM racks r JOIN server_rooms sr ON sr.id = r.server_room_id WHERE r.id = ?",
            (rack_id,),
        )
