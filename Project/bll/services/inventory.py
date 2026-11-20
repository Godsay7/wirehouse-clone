"""Dashboard, switch page, change history and health use cases."""

import re
from datetime import datetime, timedelta, timezone

from ..domain.change_history import (
    is_multiple_macs_history_row,
    prepare_change_history_rows,
)
from ..domain.ports import (
    port_is_expected,
    DocumentedNames,
    InventorySearchTerm,
    add_documented_names,
    add_written_name_and_last_known,
    build_arp_map,
    enrich_port,
    switch_port_matches,
    vlan_search,
)
from ..domain.vendors import (
    build_cisco_4900m_panel,
    detect_manufacturer,
    get_port_panel_layout,
    optical_port_labels,
)
from ...core.mac import normalize_mac, split_macs
from ...core.text import now_iso
from ..errors import NotFoundError, ValidationError
from .cabling import load_cable_graph
from .cabling_check import endpoint_text

# Order of documentation search results: ports first, then equipment, maps.
DOC_KIND_ORDER = (
    "Documented device", "Switch port", "Patch port", "Server port", "Server", "Patch panel",
    "Temporary switch", "Rack", "Workplace", "Phone", "Wi-Fi",
)


def errors_since(hours):
    """ISO time ``hours`` ago, comparable with the stored UTC timestamps."""

    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


class InventoryService:
    SEARCH_LIMIT = 100
    # "vlan 140" lists every port of the VLAN, not the first hundred.
    VLAN_SEARCH_LIMIT = 5000
    # Ports whose error counters grew within this window are marked.
    ERROR_WINDOW_HOURS = 24

    # Read a larger window first, then completely hide noisy MAC-change
    # rows where either the old or new value contains 2 or more MACs.
    CHANGES_WINDOW = 2000
    CHANGES_SHOWN = 500

    def __init__(self, database):
        self.database = database

    # --------------------------------------------------------
    # Dashboard
    # --------------------------------------------------------

    def dashboard(self, search="", errors_only=False):
        with self.database.read() as uow:
            error_ports = (
                uow.switches.error_ports_since(errors_since(self.ERROR_WINDOW_HOURS), limit=1000)
                if errors_only else []
            )
            search_results = (
                self._search_ports(uow, search)
                if search
                else []
            )
            doc_results = self._search_documentation(uow, search) if search else []

            switches = []
            errors = uow.switches.error_growth_since(errors_since(self.ERROR_WINDOW_HOURS))
            error_ports_by_switch = {}
            for (switch_id, _port) in errors:
                error_ports_by_switch[switch_id] = error_ports_by_switch.get(switch_id, 0) + 1

            for row in uow.switches.list_with_port_summary():
                switch = dict(row)
                switch["error_ports"] = error_ports_by_switch.get(switch["id"], 0)

                manufacturer_name, manufacturer_slug = detect_manufacturer(
                    switch.get("model"),
                    switch.get("host")
                )

                switch["manufacturer_name"] = manufacturer_name
                switch["manufacturer_slug"] = manufacturer_slug
                switches.append(switch)

            statistics = dict(uow.switches.port_statistics() or {})
            statistics["error_ports"] = len(errors)

        return {
            "switches": switches,
            "statistics": statistics,
            "error_window_hours": self.ERROR_WINDOW_HOURS,
            "error_ports": error_ports,
            "search_results": search_results,
            "doc_results": doc_results,
        }

    def suggest(self, search, limit=8):
        """A few quick matches for the search box: documented things first
        (PCs, sockets, racks...), then switch ports. No cable tracing, so it
        is fast enough to run on every keystroke."""

        term = InventorySearchTerm(search)
        if len(term.term) < 2:
            return {"docs": [], "ports": []}
        with self.database.read() as uow:
            docs = self._search_documentation(uow, search, limit=limit, with_cables=False)
            ports = self._search_ports(uow, search, limit=limit)
        docs = docs[: max(3, limit - min(len(ports), limit // 2))]
        return {"docs": docs, "ports": ports[: limit - len(docs)]}

    def _documented_names(self, uow):
        """Device names from the racks, documented devices and floor maps
        (shown when DNS has no name for an address)."""

        by_mac = {row["mac"]: row["name"] for row in uow.checks.expected_devices() if row.get("name")}
        by_ip = {}
        for row in uow.checks.workplace_ips():
            if row["ip"]:
                by_ip[row["ip"]] = row["pc_name"]
            if row["dante_ip"]:
                by_ip.setdefault(row["dante_ip"], f"{row['pc_name']} (Dante)")

        servers = uow.checks.server_names()
        patch_notes = {
            (row["patch_panel_id"], row["port"]): row["description"] or row["label"]
            for row in uow.checks.patch_port_notes()
        }
        graph = load_cable_graph(uow)
        by_port = {}
        for row in uow.checks.ports():
            key = (row["switch_id"], row["port"])
            endpoint = ("switch", row["switch_id"], row["port"])
            name = ""
            if graph.has_cord(endpoint):
                far = graph.far_end(endpoint)
                if far:
                    far_type, far_id, far_port = far[0]
                    if far_type == "server":
                        name = servers.get(far_id, "")
                    elif far_type == "patch":
                        name = patch_notes.get((far_id, far_port), "")
            by_port[key] = name or row["description"]
        return DocumentedNames(by_mac=by_mac, by_ip=by_ip, by_port=by_port, manual=uow.checks.host_names())

    MAX_HOSTNAME_LENGTH = 80

    def set_port_name(self, switch_id, port, name):
        """Name typed in for a switch port as a whole (ports with no device or
        many devices, or to correct a name written from the Cabling Check).
        Tied to the device MAC when one is known (the name already written,
        else the last MAC of an empty port), so it can still be confirmed.
        An empty name removes it. Recorded in Rack History."""

        name = " ".join(str(name or "").split())
        if len(name) > self.MAX_HOSTNAME_LENGTH:
            raise ValidationError(f"The hostname is longer than {self.MAX_HOSTNAME_LENGTH} characters")
        with self.database.write(touch="rack") as uow:
            row = uow.switches.get_port(switch_id, port)
            if row is None:
                raise NotFoundError("Switch port not found")
            if not name:
                uow.checks.delete_port_name(switch_id, port)
                return {"name": ""}
            current = split_macs(row["mac"])
            written = uow.checks.port_names(switch_id).get((switch_id, port))
            if written and written["mac"]:
                mac = written["mac"]
            elif len(current) == 1:
                mac = current[0]
            elif not current:
                mac = normalize_mac(uow.switches.last_mac(switch_id, port) or "")
            else:
                mac = ""                       # an uplink: a name for the port, nothing to confirm
            now = now_iso()
            confirmed_at = now if mac and mac in current else None
            if written and written["mac"] == mac and written["confirmed_at"] and mac in current:
                confirmed_at = written["confirmed_at"]
            uow.checks.set_port_name(switch_id, port, mac, name, confirmed_at, now)
        return {"name": name, "mac": mac}

    def set_host_name(self, mac, name):
        """Type a hostname in by hand for a device (MAC); an empty name removes it.
        Recorded in Rack History (can be undone)."""

        mac = normalize_mac(mac)
        name = " ".join(str(name or "").split())
        if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac or ""):
            raise ValidationError("Invalid MAC address")
        if len(name) > self.MAX_HOSTNAME_LENGTH:
            raise ValidationError(f"The hostname is longer than {self.MAX_HOSTNAME_LENGTH} characters")
        with self.database.write(touch="rack") as uow:
            if name:
                uow.checks.set_host_name(mac, name, now_iso())
            else:
                uow.checks.delete_host_name(mac)
        return {"mac": mac, "name": name}

    def _search_documentation(self, uow, search, limit=SEARCH_LIMIT, with_cables=True):
        """Rack Change / Floor Maps documentation matching the search, with where each cable leads."""

        term = InventorySearchTerm(search)
        if not term:
            return []

        results = []
        for row in uow.checks.documentation_rows():
            haystack = " ".join(str(row.get(key) or "") for key in ("title", "text", "room", "rack", "mac")).lower()
            matched = term.lower in haystack
            if not matched and term.looks_like_mac and term.mac_compact and row.get("mac"):
                matched = term.mac_compact in row["mac"].replace(":", "")
            if matched:
                results.append(row)

        results.sort(key=lambda row: (DOC_KIND_ORDER.index(row["kind"]) if row["kind"] in DOC_KIND_ORDER else 99, row["title"].lower()))
        results = results[:limit]

        if with_cables and any(row["endpoint"] for row in results):
            graph = load_cable_graph(uow)
            switches = {row["id"]: row for row in uow.checks.switches()}
            ports = {}
            for row in uow.checks.ports():
                ports.setdefault(row["switch_id"], {})[row["port"]] = row
            for row in results:
                row["cabled_to"] = ""
                if not row["endpoint"]:
                    continue
                far = graph.far_end(row["endpoint"])
                if far is None:
                    continue
                endpoint = far[0]
                details = uow.equipment.endpoint_details(*endpoint) or {}
                row["cabled_to"] = endpoint_text(endpoint, details, switches, ports)
                row["path_complete"] = far[0][0] in ("switch", "server") and far[1] == "device"

        for row in results:
            endpoint = row["endpoint"]
            row["element_id"] = f"{endpoint[0]}-{endpoint[1]}-port-{endpoint[2]}" if endpoint else ""
        return results

    def search_ports(self, search, limit=SEARCH_LIMIT):
        """Search current port inventory by IP, MAC, hostname or device description."""

        with self.database.read() as uow:
            return self._search_ports(uow, search, limit)

    def _search_ports(self, uow, search, limit=SEARCH_LIMIT):
        term = InventorySearchTerm(search)

        if not term:
            return []
        if vlan_search(search) is not None and limit == self.SEARCH_LIMIT:
            limit = max(limit, self.VLAN_SEARCH_LIMIT)

        rows = uow.switches.list_all_ports_with_switch()
        arp_map = build_arp_map(uow.arp.list_newest_first())
        documented = self._documented_names(uow)
        results = []

        for row in rows:
            port = add_documented_names(enrich_port(row, arp_map), documented)

            if not term.matches(port):
                continue

            port["mac_display"] = (
                ", ".join(port.get("mac_list", []))
                if port.get("mac_list")
                else "-"
            )
            results.append(port)

            if len(results) >= limit:
                break

        return results

    # --------------------------------------------------------
    # Switch page
    # --------------------------------------------------------

    def switch_page(self, switch_id, search=""):
        with self.database.read() as uow:
            switch = uow.switches.get(switch_id)

            if switch is None:
                raise NotFoundError(f"Switch {switch_id} not found")

            arp_map = build_arp_map(uow.arp.list_newest_first())

            documented = self._documented_names(uow)
            port_names = uow.checks.port_names(switch_id)
            all_ports = []
            for row in uow.switches.list_ports(switch_id):
                port = enrich_port(row, arp_map)
                port["switch_id"] = switch_id
                add_documented_names(port, documented)
                add_written_name_and_last_known(port, port_names.get((switch_id, port["port"])), documented, arp_map)
                all_ports.append(port)

            stats = uow.switches.switch_port_statistics(switch_id)

            # LLDP / CDP neighbours, shown next to each port.
            neighbors = {}
            for row in uow.switches.list_neighbors(switch_id):
                neighbors.setdefault(row["port"], []).append(neighbor_label(row))
            for port in all_ports:
                port["neighbors"] = [label for label in neighbors.get(port.get("port"), []) if label]

                        # Error counters that grew recently (CRC, in, out).
            errors = uow.switches.error_growth_since(errors_since(self.ERROR_WINDOW_HOURS), switch_id)
            for port in all_ports:
                port["errors"] = errors.get((switch_id, port.get("port")))

            # A port that is down but should not be: a documented cable, a
            # description, a name typed in, or a device seen there before.
            # Other down ports are just free (grey on the front panel).
            cabled = uow.connections.cabled_switch_ports(switch_id)
            for port in all_ports:
                port["cabled"] = port.get("port") in cabled
                port["expected"] = port_is_expected(port)

        if search:
            search_lower = search.lower()
            ports = [
                port
                for port in all_ports
                if switch_port_matches(port, search_lower)
            ]
        else:
            ports = list(all_ports)

        port_layout = get_port_panel_layout(
            switch,
            all_ports
        )

        cisco_4900m_panel = None

        if port_layout == "cisco_4900m":
            cisco_4900m_panel = build_cisco_4900m_panel(
                all_ports
            )

        return {
            "switch": switch,
            "ports": ports,
            "all_ports": all_ports,
            "stats": stats,
            "port_layout": port_layout,
            "cisco_4900m_panel": cisco_4900m_panel,
            "optical_labels": optical_port_labels(dict(switch), all_ports) if port_layout != "cisco_4900m" else {},
            "error_window_hours": self.ERROR_WINDOW_HOURS,
        }

    # --------------------------------------------------------
    # Change history
    # --------------------------------------------------------

    def change_history(self, search=""):
        with self.database.read() as uow:
            raw_rows = uow.history.list_changes(
                search=search,
                limit=self.CHANGES_WINDOW,
            )

        filtered_rows = [
            row
            for row in raw_rows
            if not is_multiple_macs_history_row(row)
        ][:self.CHANGES_SHOWN]

        return prepare_change_history_rows(filtered_rows)

    # --------------------------------------------------------
    # Health
    # --------------------------------------------------------

    def health(self):
        with self.database.read() as uow:
            row = uow.switches.inventory_counts()

        return {
            "status": "ok",
            "database": self.database.path,
            "switches": row["switches"],
            "ports": row["ports"],
            "history": row["history"],
            "arp_entries": row["arp_entries"],
        }


def neighbor_label(row):
    """'nh-sw3-core1 ethernet1/1/21 (LLDP)'; a neighbour without a name shows its MAC."""

    name = row.get("remote_name") or ""
    if name.lower() == "not advertised":
        name = ""
    name = name.split(".newshouse.lan")[0] or row.get("remote_chassis") or ""
    if not name:
        return ""
    port = row.get("remote_port") or ""
    if port == name or port == row.get("remote_chassis"):
        port = ""
    return f"{name} {port}".strip() + f" ({row.get('protocol', '').upper()})"
