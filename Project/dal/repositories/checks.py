"""Read-only data for the cabling check, plus the documented (expected) devices."""

from .base import Repository


class CheckRepository(Repository):

    def switches(self):
        return self._dicts(
            """
            SELECT s.id, s.host, s.sys_name, s.model,
                   rs.rack_id, r.name AS rack, sr.name AS room, rs.side, rs.rack_unit
            FROM switches s
            LEFT JOIN rack_switches rs ON rs.switch_id = s.id
            LEFT JOIN racks r ON r.id = rs.rack_id
            LEFT JOIN server_rooms sr ON sr.id = r.server_room_id
            ORDER BY s.host
            """
        )

    def ports(self):
        return self._dicts(
            """
            SELECT switch_id, port, if_name, link, speed, mac, device AS alias,
                   COALESCE(description, '') AS description, last_mac, vlan_mode
            FROM ports
            ORDER BY switch_id, port
            """
        )

    def neighbors(self):
        return self._dicts("SELECT * FROM port_neighbors ORDER BY switch_id, port")

    def hostnames(self):
        """mac -> hostname from the core ARP table (only resolved names)."""

        return {
            row["mac"]: row["hostname"]
            for row in self._dicts(
                "SELECT mac, hostname FROM arp_entries WHERE hostname IS NOT NULL AND hostname NOT IN ('', '-') ORDER BY last_seen"
            )
        }

    def ips(self):
        return {row["mac"]: row["ip"] for row in self._dicts("SELECT mac, ip FROM arp_entries ORDER BY last_seen")}

    # --------------------------------------------------------
    # Documented devices (MAC expected on a switch port)
    # --------------------------------------------------------

    def expected_devices(self):
        return self._dicts("SELECT switch_id, port, mac, name, updated_at FROM port_expected_devices ORDER BY switch_id, port")

    def patch_port_notes(self):
        """Patch ports that have a label or note (socket lookup for Floor Maps)."""

        return self._dicts(
            """
            SELECT pt.patch_panel_id, pt.port, COALESCE(pt.label, '') AS label, COALESCE(pt.description, '') AS description,
                   pp.name AS panel, r.name AS rack, sr.name AS room
            FROM patch_ports pt
            JOIN patch_panels pp ON pp.id = pt.patch_panel_id
            JOIN racks r ON r.id = pp.rack_id
            JOIN server_rooms sr ON sr.id = r.server_room_id
            WHERE COALESCE(pt.label, '') <> '' OR COALESCE(pt.description, '') <> ''
            """
        )

    # --------------------------------------------------------
    # Hostnames typed in by hand (per MAC)
    # --------------------------------------------------------

    def host_names(self):
        return {row["mac"]: row["name"] for row in self._dicts("SELECT mac, name FROM host_names")}

    def set_host_name(self, mac, name, now):
        self._execute(
            """
            INSERT INTO host_names (mac, name, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (mac) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at
            WHERE host_names.name <> excluded.name
            """,
            (mac, name, now),
        )

    def delete_host_name(self, mac):
        self._execute("DELETE FROM host_names WHERE mac = ?", (mac,))

    # --------------------------------------------------------
    # Another device on a port (collector: port_device_changes)
    # --------------------------------------------------------

    def device_changes(self, since=None):
        """The latest device change of every port (newest first), with the
        number of changes the port had since ``since`` (all if None)."""

        where, params = ("WHERE detected_at >= ?", (since,)) if since else ("", ())
        try:
            return self._dicts(
                f"""
                SELECT d.switch_id, d.port, d.if_name, d.old_macs, d.new_macs, d.detected_at, c.changes
                FROM port_device_changes d
                JOIN (
                    SELECT MAX(id) AS id, COUNT(*) AS changes
                    FROM port_device_changes {where}
                    GROUP BY switch_id, port
                ) c ON c.id = d.id
                ORDER BY d.detected_at DESC, d.id DESC
                """,
                params,
            )
        except Exception as exc:              # noqa: BLE001 — the collector has not created it yet
            if "no such table" in str(exc):
                return []
            raise

    # --------------------------------------------------------
    # Device names written on switch ports (Cabling Check)
    # --------------------------------------------------------

    def port_names(self, switch_id=None):
        """(switch_id, port) -> {mac, name, confirmed_at}."""

        query = "SELECT switch_id, port, mac, name, confirmed_at FROM port_names"
        params = ()
        if switch_id is not None:
            query += " WHERE switch_id = ?"
            params = (switch_id,)
        return {(row["switch_id"], row["port"]): row for row in self._dicts(query, params)}

    def set_port_name(self, switch_id, port, mac, name, confirmed_at, now):
        self._execute(
            """
            INSERT INTO port_names (switch_id, port, mac, name, confirmed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (switch_id, port) DO UPDATE SET
                mac = excluded.mac, name = excluded.name, confirmed_at = excluded.confirmed_at,
                created_at = excluded.created_at
            WHERE port_names.mac <> excluded.mac OR port_names.name <> excluded.name
               OR port_names.confirmed_at IS NOT excluded.confirmed_at
            """,
            (switch_id, port, mac, name, confirmed_at, now),
        )

    def delete_port_name(self, switch_id, port):
        self._execute("DELETE FROM port_names WHERE switch_id = ? AND port = ?", (switch_id, port))

    def server_names(self):
        """server id -> name."""

        return {row["id"]: row["name"] for row in self._dicts("SELECT id, name FROM servers")}

    def workplace_ips(self):
        """PC names on the floor maps with their IP and Dante IP."""

        return self._dicts(
            """
            SELECT pc_name, COALESCE(ip, '') AS ip, COALESCE(dante_ip, '') AS dante_ip
            FROM floor_map_workplaces
            WHERE COALESCE(pc_name, '') <> ''
            """
        )

    # --------------------------------------------------------
    # Documentation search: everything typed into Rack Change / Floor Maps
    # --------------------------------------------------------

    def documentation_rows(self):
        """Searchable rows: {kind, title, text, endpoint (type,id,port)|None, room, rack, rack_id, side, unit, map_id}."""

        rows = []
        for r in self._dicts(
            """
            SELECT s.id, s.host, p.port, p.if_name, p.description, rs.rack_id, rs.side, rs.rack_unit,
                   r.name AS rack, sr.name AS room
            FROM ports p JOIN switches s ON s.id = p.switch_id
            LEFT JOIN rack_switches rs ON rs.switch_id = s.id
            LEFT JOIN racks r ON r.id = rs.rack_id
            LEFT JOIN server_rooms sr ON sr.id = r.server_room_id
            WHERE COALESCE(p.description, '') <> ''
            """
        ):
            rows.append({"kind": "Switch port", "title": f"{r['host']} {r['if_name'] or r['port']}", "text": r["description"],
                         "endpoint": ("switch", r["id"], r["port"]), **_place(r)})

        for r in self._dicts(
            """
            SELECT pp.id, pp.name, pp.patch_type, pt.port, pt.label, pt.description, pp.rack_id, pp.side, pp.rack_unit,
                   r.name AS rack, sr.name AS room
            FROM patch_ports pt JOIN patch_panels pp ON pp.id = pt.patch_panel_id
            JOIN racks r ON r.id = pp.rack_id JOIN server_rooms sr ON sr.id = r.server_room_id
            WHERE COALESCE(pt.description, '') <> '' OR COALESCE(pt.label, '') <> ''
            """
        ):
            text = " · ".join(x for x in (r["label"], r["description"]) if x)
            rows.append({"kind": "Patch port", "title": f"{r['name']} p{r['port']}", "text": text,
                         "endpoint": ("patch", r["id"], r["port"]), **_place(r)})

        for r in self._dicts(
            """
            SELECT sv.id, sv.name, sp.port, sp.label, sv.rack_id, sv.side, sv.rack_unit, r.name AS rack, sr.name AS room
            FROM server_ports sp JOIN servers sv ON sv.id = sp.server_id
            JOIN racks r ON r.id = sv.rack_id JOIN server_rooms sr ON sr.id = r.server_room_id
            WHERE COALESCE(sp.label, '') <> ''
            """
        ):
            port = "mng" if r["port"] == 0 else f"p{r['port']}"
            rows.append({"kind": "Server port", "title": f"{r['name']} {port}", "text": r["label"],
                         "endpoint": ("server", r["id"], r["port"]), **_place(r)})

        equipment = (
            ("Server", "SELECT sv.id, sv.name, '' AS text, sv.rack_id, sv.side, sv.rack_unit, r.name AS rack, sr.name AS room FROM servers sv"),
            ("Patch panel", "SELECT pp.id, pp.name, pp.patch_type AS text, pp.rack_id, pp.side, pp.rack_unit, r.name AS rack, sr.name AS room FROM patch_panels pp"),
            ("Temporary switch", "SELECT ph.id, ph.name, COALESCE(ph.model, '') AS text, ph.rack_id, ph.side, ph.rack_unit, r.name AS rack, sr.name AS room FROM rack_switch_placeholders ph"),
        )
        for kind, select in equipment:
            alias = select.split(" FROM ")[1].split()[1]
            for r in self._dicts(
                select + f" JOIN racks r ON r.id = {alias}.rack_id JOIN server_rooms sr ON sr.id = r.server_room_id"
            ):
                rows.append({"kind": kind, "title": r["name"], "text": r["text"] or "", "endpoint": None, **_place(r)})

        for r in self._dicts(
            "SELECT r.id AS rack_id, r.name AS rack, sr.name AS room FROM racks r JOIN server_rooms sr ON sr.id = r.server_room_id"
        ):
            rows.append({"kind": "Rack", "title": f"{r['room']} / {r['rack']}", "text": "", "endpoint": None,
                         **_place(dict(r, side="front", rack_unit=None))})

        for r in self._dicts(
            """
            SELECT e.switch_id, e.port, e.mac, e.name, s.host, p.if_name, rs.rack_id, rs.side, rs.rack_unit,
                   r.name AS rack, sr.name AS room
            FROM port_expected_devices e JOIN switches s ON s.id = e.switch_id
            LEFT JOIN ports p ON p.switch_id = e.switch_id AND p.port = e.port
            LEFT JOIN rack_switches rs ON rs.switch_id = s.id
            LEFT JOIN racks r ON r.id = rs.rack_id
            LEFT JOIN server_rooms sr ON sr.id = r.server_room_id
            """
        ):
            rows.append({"kind": "Documented device", "title": r["name"] or r["mac"], "text": f"{r['mac']} on {r['host']} {r['if_name'] or r['port']}",
                         "mac": r["mac"], "endpoint": ("switch", r["switch_id"], r["port"]), **_place(r)})

        for r in self._dicts(
            """
            SELECT w.map_id, m.name AS map_name, w.device_type, w.role, w.pc_name, w.ip, w.note, w.dante_ip
            FROM floor_map_workplaces w JOIN floor_maps m ON m.id = w.map_id
            """
        ):
            kind = {"phone": "Phone", "wifi": "Wi-Fi"}.get(r["device_type"], "Workplace")
            rows.append({"kind": kind, "title": r["pc_name"] or r["role"] or r["ip"] or kind,
                         "text": " · ".join(x for x in (r["role"], r["ip"], r["dante_ip"] and f"Dante {r['dante_ip']}", r["note"]) if x),
                         "endpoint": None, "room": f"Floor map {r['map_name']}", "rack": "", "rack_id": None,
                         "side": "", "unit": None, "map_id": r["map_id"]})
        return rows


def _place(row):
    return {
        "room": row.get("room") or "",
        "rack": row.get("rack") or "",
        "rack_id": row.get("rack_id"),
        "side": row.get("side") or "front",
        "unit": row.get("rack_unit"),
        "map_id": None,
    }

