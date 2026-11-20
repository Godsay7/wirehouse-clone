"""Switches and their current port state (filled by the SNMP collector)."""

from ...core.vlan import format_vlans
from .base import Repository


PORT_COLUMNS = """
    port,
    device,
    speed,
    link,
    mac,
    if_index,
    if_name,
    last_seen,
    vlan_mode,
    vlan,
    vlan_tagged,
    last_mac,
    last_mac_at
"""


class SwitchRepository(Repository):

    # --------------------------------------------------------
    # Switches
    # --------------------------------------------------------

    def get(self, switch_id):
        return self._one(
            """
            SELECT
                id,
                host,
                sys_name,
                model,
                last_seen
            FROM switches
            WHERE id = ?
            """,
            (switch_id,),
        )

    def get_host(self, switch_id):
        return self._one(
            "SELECT id, host FROM switches WHERE id = ?",
            (switch_id,),
        )

    def list_for_rack_picker(self):
        return self._dicts(
            "SELECT id, host, model FROM switches ORDER BY host"
        )

    def list_with_port_summary(self):
        return self._all(
            """
            SELECT
                s.id,
                s.host,
                s.model,
                s.last_seen,

                COUNT(p.id) AS port_count,

                SUM(
                    CASE
                        WHEN p.link = 'UP'
                        THEN 1
                        ELSE 0
                    END
                ) AS up_count,

                SUM(
                    CASE
                        WHEN p.link = 'DOWN'
                        THEN 1
                        ELSE 0
                    END
                ) AS down_count

            FROM switches s

            LEFT JOIN ports p
                ON p.switch_id = s.id

            GROUP BY
                s.id,
                s.host,
                s.model,
                s.last_seen

            ORDER BY s.host
            """
        )

    def upsert(self, host, sys_name, model, last_seen):
        """Insert or update one switch and return its id."""

        self._execute(
            """
            INSERT INTO switches (
                host,
                sys_name,
                model,
                last_seen
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT(host)
            DO UPDATE SET
                sys_name = excluded.sys_name,
                model = excluded.model,
                last_seen = excluded.last_seen
            """,
            (host, sys_name, model, last_seen),
        )

        row = self._one(
            """
            SELECT id
            FROM switches
            WHERE host = ?
            """,
            (host,),
        )

        return row[0] if row else None

    # --------------------------------------------------------
    # Ports
    # --------------------------------------------------------

    def list_ports(self, switch_id):
        return self._all(
            f"""
            SELECT
                {PORT_COLUMNS}
            FROM ports
            WHERE switch_id = ?
            ORDER BY port
            """,
            (switch_id,),
        )

    def current_port_states(self, switch_id):
        """port -> (device, speed, link, mac, if_index, if_name) from the previous poll."""

        return {
            row[0]: tuple(row[1:])
            for row in self._all(
                "SELECT port, device, speed, link, mac, if_index, if_name FROM ports WHERE switch_id = ?",
                (switch_id,),
            )
        }

    def list_ports_with_description(self, switch_id):
        return self._dicts(
            "SELECT port, device, speed, link, mac, if_index, if_name, last_seen, description, last_mac"
            " FROM ports WHERE switch_id = ? ORDER BY port",
            (switch_id,),
        )

    def list_all_ports_with_switch(self):
        return self._all(
            """
            SELECT
                s.id AS switch_id,
                s.host AS switch_name,
                p.port,
                p.device,
                p.speed,
                p.link,
                p.mac,
                p.if_index,
                p.if_name,
                p.last_seen,
                p.vlan_mode,
                p.vlan,
                p.vlan_tagged
            FROM ports p
            JOIN switches s
                ON s.id = p.switch_id
            ORDER BY
                s.host,
                p.port
            """
        )

    def error_ports_since(self, since, limit=10):
        """Ports whose error counters grew since ``since``, most errors first:
        switch_id, host, port, if_name, in/out/fcs growth, total, last."""

        return self._dicts(
            """
            SELECT e.switch_id, s.host, e.port, p.if_name,
                   SUM(e.in_errors) AS in_errors, SUM(e.out_errors) AS out_errors, SUM(e.fcs_errors) AS fcs_errors,
                   SUM(e.in_errors + e.out_errors + e.fcs_errors) AS total, MAX(e.detected_at) AS last
            FROM port_error_events e
            JOIN switches s ON s.id = e.switch_id
            LEFT JOIN ports p ON p.switch_id = e.switch_id AND p.port = e.port
            WHERE e.detected_at >= ?
            GROUP BY e.switch_id, e.port
            ORDER BY total DESC
            LIMIT ?
            """,
            (since, limit),
        )

    def error_growth_since(self, since, switch_id=None):
        """(switch_id, port) -> {"in", "out", "fcs", "total", "last"}: how much the
        error counters grew since ``since`` (ISO time), only ports that grew."""

        where = "WHERE detected_at >= ?"
        params = [since]
        if switch_id is not None:
            where += " AND switch_id = ?"
            params.append(switch_id)
        result = {}
        for row in self._all(
            f"""
            SELECT switch_id, port, SUM(in_errors), SUM(out_errors), SUM(fcs_errors), MAX(detected_at)
            FROM port_error_events {where}
            GROUP BY switch_id, port
            """,
            params,
        ):
            grown = {"in": row[2] or 0, "out": row[3] or 0, "fcs": row[4] or 0, "last": row[5]}
            grown["total"] = grown["in"] + grown["out"] + grown["fcs"]
            result[(row[0], row[1])] = grown
        return result

    def port_statistics(self):
        return self._one(
            """
            SELECT
                COUNT(*) AS total_ports,

                SUM(
                    CASE
                        WHEN link = 'UP'
                        THEN 1
                        ELSE 0
                    END
                ) AS up_ports,

                SUM(
                    CASE
                        WHEN link = 'DOWN'
                        THEN 1
                        ELSE 0
                    END
                ) AS down_ports,

                COUNT(
                    CASE
                        WHEN mac IS NOT NULL
                         AND mac != ''
                         AND mac != '-'
                        THEN 1
                    END
                ) AS mac_count

            FROM ports
            """
        )

    def switch_port_statistics(self, switch_id):
        return self._one(
            """
            SELECT
                COUNT(*) AS total,

                SUM(
                    CASE
                        WHEN link = 'UP'
                        THEN 1
                        ELSE 0
                    END
                ) AS up,

                SUM(
                    CASE
                        WHEN link = 'DOWN'
                        THEN 1
                        ELSE 0
                    END
                ) AS down,

                COUNT(
                    CASE
                        WHEN mac IS NOT NULL
                         AND mac != ''
                         AND mac != '-'
                        THEN 1
                    END
                ) AS macs

            FROM ports
            WHERE switch_id = ?
            """,
            (switch_id,),
        )

    def last_macs(self, switch_id):
        """port -> the last MAC list seen on it (kept while the port is down)."""

        return {
            row[0]: row[1]
            for row in self._all("SELECT port, last_mac FROM ports WHERE switch_id = ?", (switch_id,))
        }

    def last_mac(self, switch_id, port):
        row = self._one("SELECT last_mac FROM ports WHERE switch_id = ? AND port = ?", (switch_id, port))
        return row[0] if row else None

    def get_port(self, switch_id, port):
        return self._one("SELECT switch_id, port, if_name, mac FROM ports WHERE switch_id = ? AND port = ?", (switch_id, port))

    def find_id(self, host):
        row = self._one("SELECT id FROM switches WHERE host = ?", (host,))
        return row[0] if row else None

    def replace_neighbors(self, switch_id, rows, now):
        """rows: [(port, {protocol, remote_name, remote_port, ...}), ...]"""

        self._execute("DELETE FROM port_neighbors WHERE switch_id = ?", (switch_id,))
        for port, entry in rows:
            self._execute(
                """
                INSERT INTO port_neighbors (switch_id, port, protocol, remote_name, remote_port,
                                            remote_port_desc, remote_chassis, remote_platform, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (switch_id, port, entry["protocol"], entry.get("remote_name") or "", entry.get("remote_port") or "",
                 entry.get("remote_port_desc") or "", entry.get("remote_chassis") or "",
                 entry.get("remote_platform") or "", now),
            )

    def list_neighbors(self, switch_id=None):
        query = "SELECT * FROM port_neighbors"
        if switch_id is None:
            return self._dicts(query + " ORDER BY switch_id, port")
        return self._dicts(query + " WHERE switch_id = ? ORDER BY port", (switch_id,))

    def set_port_description(self, switch_id, port, description):
        self._execute(
            "UPDATE ports SET description = ? WHERE switch_id = ? AND port = ?",
            (description, switch_id, port),
        )

    def upsert_port(self, switch_id, port, last_seen):
        """Save the current state of one collected port.

        ``port`` is the collector dict: Port/Device/Speed/Link/MAC/_ifIndex/_ifName,
        optionally _vlan {mode, vlan, tagged} and _errors {in, out, fcs}.
        VLANs / counters the switch did not report keep their previous value.
        """

        vlan = port.get("_vlan")
        errors = port.get("_errors")
        has_vlan = 1 if vlan else 0
        has_errors = 1 if errors else 0
        vlan = vlan or {}
        errors = errors or {}

        self._execute(
            """
            INSERT INTO ports (
                switch_id, port, device, speed, link, mac, if_index, if_name, last_seen,
                vlan_mode, vlan, vlan_tagged, in_errors, out_errors, fcs_errors,
                last_mac, last_mac_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    CASE WHEN ? NOT IN ('', '-') THEN ? END, CASE WHEN ? NOT IN ('', '-') THEN ? END)

            ON CONFLICT(
                switch_id,
                port
            )
            DO UPDATE SET
                device = excluded.device,
                speed = excluded.speed,
                link = excluded.link,
                mac = excluded.mac,
                if_index = excluded.if_index,
                if_name = excluded.if_name,
                last_seen = excluded.last_seen,
                last_mac = CASE WHEN excluded.mac NOT IN ('', '-') THEN excluded.mac ELSE last_mac END,
                last_mac_at = CASE WHEN excluded.mac NOT IN ('', '-') THEN excluded.last_seen ELSE last_mac_at END,
                vlan_mode = CASE WHEN ? THEN excluded.vlan_mode ELSE vlan_mode END,
                vlan = CASE WHEN ? THEN excluded.vlan ELSE vlan END,
                vlan_tagged = CASE WHEN ? THEN excluded.vlan_tagged ELSE vlan_tagged END,
                in_errors = CASE WHEN ? THEN excluded.in_errors ELSE in_errors END,
                out_errors = CASE WHEN ? THEN excluded.out_errors ELSE out_errors END,
                fcs_errors = CASE WHEN ? THEN excluded.fcs_errors ELSE fcs_errors END
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
                last_seen,
                vlan.get("mode"),
                vlan.get("vlan"),
                format_vlans(vlan.get("tagged") or []),
                errors.get("in"),
                errors.get("out"),
                errors.get("fcs"),
                port["MAC"] or "", port["MAC"], port["MAC"] or "", last_seen,
                has_vlan, has_vlan, has_vlan,
                has_errors, has_errors, has_errors,
            ),
        )

    def port_vlans_and_counters(self, switch_id):
        """port -> (vlan_mode, vlan, vlan_tagged, in_errors, out_errors, fcs_errors) from the previous poll."""

        return {
            row[0]: tuple(row[1:])
            for row in self._all(
                "SELECT port, vlan_mode, vlan, vlan_tagged, in_errors, out_errors, fcs_errors FROM ports WHERE switch_id = ?",
                (switch_id,),
            )
        }

    def insert_error_event(self, switch_id, port_number, detected_at, grown):
        self._execute(
            "INSERT INTO port_error_events (switch_id, port, detected_at, in_errors, out_errors, fcs_errors) VALUES (?, ?, ?, ?, ?, ?)",
            (switch_id, port_number, detected_at, grown["in"], grown["out"], grown["fcs"]),
        )

    # --------------------------------------------------------
    # Health
    # --------------------------------------------------------

    def inventory_counts(self):
        return self._one(
            """
            SELECT
                COUNT(*) AS switches,
                (
                    SELECT COUNT(*)
                    FROM ports
                ) AS ports,
                (
                    SELECT COUNT(*)
                    FROM port_history
                ) AS history,
                (
                    SELECT COUNT(*)
                    FROM arp_entries
                ) AS arp_entries
            FROM switches
            """
        )
