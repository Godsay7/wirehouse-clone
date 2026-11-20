"""Cabling check: compare the documented rack cabling with what the switches see.

Sources of "reality":
* LLDP / CDP neighbours (collector, every poll);
* MAC address tables (another device on a port where one worked before);
* link state and port descriptions (ifAlias) of the switch ports.
"""

import re
from datetime import datetime, timedelta, timezone

from ... import settings
from ..domain.cable_path import DEVICE_TYPES, END_DEVICE
from ..domain.cabling_check import (
    SwitchDirectory,
    host_number,
    port_macs,
    switch_numbers,
)
from .cabling import load_cable_graph

def _device_changes_since():
    """Device changes are shown for as long as the history is kept."""

    if settings.RETENTION_DAYS <= 0:
        return None
    since = datetime.now(timezone.utc) - timedelta(days=settings.RETENTION_DAYS)
    return since.isoformat(timespec="seconds")


class CablingCheckService:

    def __init__(self, database):
        self.database = database

    # --------------------------------------------------------
    # Cable journal export
    # --------------------------------------------------------

    def cable_journal(self, switch_id=None):
        """(header, column widths, rows): the switch ports with their documented
        cable and live state (free ports that are down are left out)."""

        with self.database.read() as uow:
            entries = cable_journal_entries(uow, switch_id)
        rows = [row for row in map(journal_row, entries) if row]
        return [name for name, _ in JOURNAL_COLUMNS], [width for _, width in JOURNAL_COLUMNS], rows

    # --------------------------------------------------------
    # The report
    # --------------------------------------------------------

    def report(self):
        with self.database.read() as uow:
            switches = {row["id"]: row for row in uow.checks.switches()}
            ports = {}
            for row in uow.checks.ports():
                ports.setdefault(row["switch_id"], {})[row["port"]] = row
            neighbors = uow.checks.neighbors()
            device_change_rows = uow.checks.device_changes(_device_changes_since())
            # Names typed in by hand (switch page) win over DNS.
            hostnames = {**uow.checks.hostnames(), **uow.checks.host_names()}
            ips = uow.checks.ips()
            graph = load_cable_graph(uow)

            details_cache = {}

            def details(endpoint):
                if endpoint not in details_cache:
                    details_cache[endpoint] = uow.equipment.endpoint_details(*endpoint) or {}
                return details_cache[endpoint]

            def describe(endpoint):
                return endpoint_text(endpoint, details(endpoint), switches, ports)

            def room_of(endpoint):
                return details(endpoint).get("room") or ""

            report = _build_report(switches, ports, neighbors, graph, describe, room_of)

        report["device_changes"] = _device_changes(device_change_rows, switches, ports, hostnames, ips)
        report["summary"]["device_changed"] = len(report["device_changes"])
        report["summary"]["device_change_days"] = settings.RETENTION_DAYS
        return report


def _device_changes(rows, switches, ports, hostnames, ips):
    """Ports where the collector saw one device and later another one
    (port_device_changes): the latest change of each port, newest first."""

    def device(mac):
        return {"mac": mac, "name": hostnames.get(mac, ""), "ip": ips.get(mac, "")}

    changes = []
    for row in rows:
        if row["switch_id"] not in switches:
            continue
        port_row = ports.get(row["switch_id"], {}).get(row["port"]) or {}
        # A trunk carries several VLANs: the MACs behind it are other switches'
        # devices, not one device of its own.
        if port_row.get("vlan_mode") == "trunk":
            continue
        local = _switch_label(switches, ports, row["switch_id"], row["port"])
        if row.get("if_name") and local["if_name"] == f"p{row['port']}":
            local["if_name"] = row["if_name"]
        old, new = port_macs(row["old_macs"]), port_macs(row["new_macs"])
        current = port_macs(port_row.get("mac"))
        changes.append({
            "local": local,
            "old": [device(m) for m in old],
            "new": [device(m) for m in new],
            "at": row["detected_at"],
            "changes": row["changes"],
            # The new device is on the port right now (not replaced again or gone).
            "new_is_there": bool(set(new) & set(current)),
        })
    return changes


# The cable journal: one row per switch port that has something to say (a
# link, a cable, a note or a description); free ports that are down are left
# out. Headers are translation keys (blueprints/checks.py).
JOURNAL_COLUMNS = (
    ("Switch", 22), ("Location", 26), ("Port", 13), ("Link", 10), ("Description on switch", 24),
    ("Port note", 28), ("Cabled to", 36), ("Cable leads to", 36), ("Device", 28), ("IP", 17),
    ("MAC", 19), ("LLDP / CDP neighbour", 30),
)
# Columns whose text the blueprint translates ("(temporary)", "path ends here" …).
JOURNAL_TRANSLATED = ("Cabled to", "Cable leads to", "Device")
# More MACs than this on a port (an uplink, a VM host): only counted.
JOURNAL_MAX_DEVICES = 3


def cable_journal_entries(uow, switch_id=None):
    """Every switch port (of one switch, or all) with its documented cable and
    live state, as dicts. Used by the journal and by the port history page."""

    switches = {row["id"]: row for row in uow.checks.switches()}
    ports = {}
    for row in uow.checks.ports():
        ports.setdefault(row["switch_id"], {})[row["port"]] = row
    hostnames, ips = uow.checks.hostnames(), uow.checks.ips()
    hostnames.update(uow.checks.host_names())            # typed in by hand wins
    expected = {}
    for row in uow.checks.expected_devices():
        expected.setdefault((row["switch_id"], row["port"]), []).append(row)
    neighbors = {}
    for row in uow.checks.neighbors():
        name = row["remote_name"] if row["remote_name"].lower() != "not advertised" else row["remote_chassis"]
        if name:
            remote = row["remote_port"] if row["remote_port"] and row["remote_port"] != name else ""
            neighbors.setdefault((row["switch_id"], row["port"]), []).append(f"{name} {remote}".strip())
    graph = load_cable_graph(uow)

    cache = {}

    def details(endpoint):
        if endpoint not in cache:
            cache[endpoint] = uow.equipment.endpoint_details(*endpoint) or {}
        return cache[endpoint]

    entries = []
    for sid in sorted(switches, key=lambda i: switches[i]["host"].lower()):
        if switch_id is not None and sid != switch_id:
            continue
        sw = switches[sid]
        for port, row in sorted(ports.get(sid, {}).items()):
            endpoint = ("switch", sid, port)
            first_hop = graph.cord_peers(endpoint)
            first = first_note = far = ""
            path_complete = None
            if first_hop:
                hop = first_hop[0][0]
                first = endpoint_text(hop, details(hop), switches, ports)
                first_note = (details(hop).get("description") or "") if hop[0] == "patch" else ""
                end = graph.far_end(endpoint)
                if end is not None:
                    far = endpoint_text(end[0], details(end[0]), switches, ports) if end[0] != hop else ""
                    path_complete = end[0][0] in DEVICE_TYPES and end[1] == END_DEVICE
            alias = row.get("alias")
            entries.append({
                "switch_id": sid, "host": sw["host"], "room": sw.get("room") or "", "rack": sw.get("rack") or "",
                "rack_id": sw.get("rack_id"), "side": sw.get("side") or "front",
                "unit": sw.get("rack_unit") or "", "port": port, "if_name": row.get("if_name") or "",
                "link": row.get("link") or "", "speed": row.get("speed") or "",
                "alias": alias if alias not in (None, "-") else "",
                "note": row.get("description") or "",
                "cabled_to": first, "cabled_note": first_note, "leads_to": far, "path_complete": path_complete,
                "documented": expected.get((sid, port), []),
                "macs": port_macs(row.get("mac")),
                "hostnames": hostnames, "ips": ips,
                "neighbors": neighbors.get((sid, port), []),
            })
    return entries


def _short_host(name):
    return re.sub(r"\.newshouse\.lan$", "", name or "", flags=re.I)


def _in_place(text, room, rack):
    """'P.P. 2.1 p21 (NH Server Room / Rack 2)' -> 'P.P. 2.1 p21' when the
    switch is in that very rack: the place says nothing new there."""

    where = " / ".join(x for x in (room, rack) if x)
    return text[: -len(where) - 3] if where and text.endswith(f" ({where})") else text


def journal_row(entry):
    """One readable row of the cable journal (JOURNAL_COLUMNS order), or None
    for a free port with nothing to say."""

    up = entry["link"].upper() == "UP"
    if not (up or entry["cabled_to"] or entry["note"] or entry["alias"] or entry["documented"]):
        return None

    location = " / ".join(x for x in (entry["room"], entry["rack"]) if x)
    if location and entry["unit"]:
        location += f" · U{entry['unit']}"

    link = entry["link"].upper() or "-"
    if up and entry["speed"] and entry["speed"] != "-":
        link += f" · {entry['speed']}"

    cabled = _in_place(entry["cabled_to"], entry["room"], entry["rack"])
    if cabled and entry["cabled_note"] and entry["cabled_note"].strip() != entry["note"].strip():
        cabled += f" — {entry['cabled_note']}"
    leads = _in_place(entry["leads_to"], entry["room"], entry["rack"])
    if leads and entry["path_complete"] is False:
        leads += " (path ends here)"

    device, ip_text, mac_text = journal_device(entry)

    return [
        entry["host"], location, entry["if_name"] or f"p{entry['port']}", link, entry["alias"], entry["note"],
        cabled, leads, device, ip_text, mac_text, "; ".join(entry["neighbors"]),
    ]


def journal_device(entry):
    """(device, IP, MAC) texts of a port: what is on it now, or the
    documented device that is off; a port with many MACs only counts them."""

    macs, hostnames, ips = entry["macs"], entry["hostnames"], entry["ips"]
    documented = entry["documented"]
    if len(macs) > JOURNAL_MAX_DEVICES:
        device, ip_text, mac_text = f"{len(macs)} devices", "", ""
    elif macs:
        names = {d["mac"]: d["name"] for d in documented if d["name"]}
        device = ", ".join(dict.fromkeys(_short_host(names.get(m) or hostnames.get(m) or "") for m in macs if names.get(m) or hostnames.get(m)))
        ip_text = ", ".join(dict.fromkeys(ips[m] for m in macs if m in ips))
        mac_text = ", ".join(macs)
    else:
        # Nothing on the port now: the documented device, if any.
        device = ", ".join(d["name"] for d in documented if d["name"])
        if device:
            device += " (not seen now)"
        ip_text = ""
        mac_text = ", ".join(d["mac"] for d in documented)
    return device, ip_text, mac_text


def endpoint_text(endpoint, details, switches, ports):
    endpoint_type, endpoint_id, port = endpoint
    if endpoint_type == "switch":
        host = switches.get(endpoint_id, {}).get("host", f"switch {endpoint_id}")
        if_name = ports.get(endpoint_id, {}).get(port, {}).get("if_name")
        return f"{host} {if_name or 'p' + str(port)}"
    name = details.get("name") or endpoint_type
    if endpoint_type == "placeholder":
        name += " (temporary)"
    if endpoint_type == "server":
        port_label = "mng" if port == 0 else (details.get("port_name") or f"p{port}")
    else:
        port_label = f"p{port}"
    where = " / ".join(x for x in (details.get("room"), details.get("rack")) if x)
    return f"{name} {port_label}" + (f" ({where})" if where else "")


def _switch_label(switches, ports, switch_id, port):
    host = switches[switch_id]["host"]
    row = ports.get(switch_id, {}).get(port)
    return {
        "switch_id": switch_id,
        "port": port,
        "host": host,
        "if_name": (row or {}).get("if_name") or f"p{port}",
        "alias": (row or {}).get("alias") if (row or {}).get("alias") not in (None, "-") else "",
        "link": (row or {}).get("link") or "",
        "mounted": switches[switch_id].get("rack_id") is not None,
        "rack_id": switches[switch_id].get("rack_id"),
        "side": switches[switch_id].get("side") or "front",
    }


def ep_json(endpoint):
    """(type, id, port) -> the JSON endpoint /rack/connect expects."""

    endpoint_type, endpoint_id, port = endpoint
    fields = {"switch": ("switch_id", "switch_port"), "patch": ("patch_panel_id", "patch_port"),
              "server": ("server_id", "server_port"), "placeholder": ("placeholder_id", "placeholder_port")}[endpoint_type]
    return {"type": endpoint_type, fields[0]: endpoint_id, fields[1]: port}


def _build_report(switches, ports, neighbors, graph, describe, room_of=lambda e: ""):
    directory = SwitchDirectory(
        switches.values(),
        {switch_id: {port: row["if_name"] for port, row in rows.items()} for switch_id, rows in ports.items()},
    )

    far_reasons = {}

    def documented(switch_id, port):
        """(far endpoint or None, text) of the documented cable of a switch port."""
        far = graph.far_end(("switch", switch_id, port))
        if far is None:
            return None, ""
        endpoint, reason, _ = far
        far_reasons[("switch", switch_id, port)] = reason
        text = describe(endpoint)
        if endpoint[0] not in DEVICE_TYPES or reason != END_DEVICE:
            text += " — path ends here"
        return endpoint, text

    def mounted(switch_id):
        return bool(switches[switch_id].get("rack_id"))

    def link_fix(status, local, remote, far):
        """A one-click fix for a switch-to-switch link the switches report:
        add:      no cable on either port -> direct cable;
        complete: one side's documented path stops at a free patch / ODF port
                  in the other switch's room -> cable from that switch to it;
        recable:  a direct cable to the wrong port of the right switch ->
                  move it to the port LLDP/CDP sees (asks if that port is used)."""
        if remote is None or not mounted(local[1]) or not mounted(remote[1]):
            return None
        local_label = _switch_label(switches, ports, *local[1:])
        remote_label = _switch_label(switches, ports, *remote[1:])
        if status == "missing":
            if not graph.has_cord(local) and not graph.has_cord(remote):
                return {"kind": "add", "label": "Add cable", "a": ep_json(local), "b": ep_json(remote)}
            for here, there, there_label in ((local, remote, remote_label), (remote, local, local_label)):
                end = graph.far_end(here)
                if end is None or graph.has_cord(there):
                    continue
                end_point, reason, _ = end
                if (end_point[0] == "patch" and reason == "not_patched"
                        and room_of(end_point) == (switches[there[1]].get("room") or "")):
                    return {"kind": "complete",
                            "label": f"Connect {there_label['host']} {there_label['if_name']} to {describe(end_point)}",
                            "a": ep_json(there), "b": ep_json(end_point)}
        if status == "mismatch" and far is not None and far[0] == "switch" and far[1] == remote[1]:
            peers = graph.cord_peers(local)
            if len(peers) == 1 and peers[0][0] == far:          # a direct cable, not through panels
                return {"kind": "recable",
                        "label": f"Re-cable to {remote_label['host']} {remote_label['if_name']}",
                        "a": ep_json(local), "b": ep_json(remote)}
        return None

    # ---------------- LLDP / CDP neighbours ----------------
    neighbor_links = []
    seen_pairs = set()
    ports_with_neighbor = set()
    switches_with_lldp = set()

    resolved = []
    for entry in neighbors:
        if entry["switch_id"] in switches:
            switches_with_lldp.add(entry["switch_id"])
            resolved.append((entry, *directory.resolve(entry["remote_name"], entry["remote_port"], entry["remote_port_desc"])))

    # A switch advertising from a VLAN interface (MikroTik) is heard through
    # other switches on every uplink; such entries say nothing about cabling.
    resolved_ports = {(e["switch_id"], e["port"]) for e, rid, rport in resolved if rid is not None and rport is not None}
    heard_on = {}
    for entry, remote_id, remote_port in resolved:
        if remote_id is not None and remote_port is None:
            heard_on.setdefault(remote_id, set()).add((entry["switch_id"], entry["port"]))

    def is_flooded(entry, remote_id, remote_port):
        if remote_id is None or remote_port is not None:
            return False
        return (entry["switch_id"], entry["port"]) in resolved_ports or len(heard_on.get(remote_id, ())) > 2

    for entry, remote_id, remote_port in resolved:
        if is_flooded(entry, remote_id, remote_port):
            continue
        switch_id, port = entry["switch_id"], entry["port"]
        local = ("switch", switch_id, port)
        far, doc_text = documented(switch_id, port)

        if remote_id is None or remote_id == switch_id:
            continue          # not a switch of the inventory

        ports_with_neighbor.add(local)
        remote = ("switch", remote_id, remote_port) if remote_port is not None else None
        if remote is not None:
            ports_with_neighbor.add(remote)
        pair = frozenset((local, remote)) if remote is not None else frozenset((local, ("switch", remote_id, None)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        if far is not None and remote is not None and far == remote:
            status = "ok"
        elif far is not None and far[0] == "switch" and far[1] == remote_id and remote is None:
            status = "ok"
        elif far is not None and far[0] in DEVICE_TYPES:
            status = "mismatch"
        else:
            status = "missing"

        # Seen from the other side too? Its documentation may differ.
        remote_doc = documented(remote_id, remote_port)[1] if remote is not None else ""
        neighbor_links.append({
            "status": status,
            "protocol": entry["protocol"].upper(),
            "local": _switch_label(switches, ports, switch_id, port),
            "remote": _switch_label(switches, ports, remote_id, remote_port) if remote is not None else {
                "host": switches[remote_id]["host"], "if_name": entry["remote_port"] or "?", "mounted": False,
            },
            "documented": doc_text,
            "remote_documented": remote_doc,
            "fix": link_fix(status, local, remote, far),
        })

    # Documented switch-to-switch links that LLDP/CDP do not confirm.
    unconfirmed = []
    reported = set()
    for switch_id in switches:
        for port in ports.get(switch_id, {}):
            local = ("switch", switch_id, port)
            if local in ports_with_neighbor or local in reported:
                continue
            far, doc_text = documented(switch_id, port)
            if far is None or far[0] != "switch" or far in ports_with_neighbor:
                continue
            # Only meaningful when both switches do report neighbours.
            if switch_id not in switches_with_lldp or far[1] not in switches_with_lldp:
                continue
            reported.update((local, far))
            unconfirmed.append({
                "local": _switch_label(switches, ports, switch_id, port),
                "documented": doc_text,
                "link": ports[switch_id][port].get("link") or "",
            })

    # ---------------- Port descriptions naming another switch ----------------
    alias_checks = []
    for switch_id, rows in ports.items():
        own = host_number(switches[switch_id]["host"])
        for port, row in rows.items():
            named = switch_numbers(row.get("alias")) - {own}
            if not named:
                continue
            far, doc_text = documented(switch_id, port)
            if far is None or far[0] != "switch":
                continue
            far_number = host_number(switches[far[1]]["host"])
            if far_number in named:
                continue
            alias_checks.append({
                "local": _switch_label(switches, ports, switch_id, port),
                "alias": row.get("alias"),
                "documented": doc_text,
            })

    status_order = {"mismatch": 0, "missing": 1, "ok": 2}
    neighbor_links.sort(key=lambda x: (status_order[x["status"]], x["local"]["host"], x["local"]["port"]))

    summary = {
        "neighbor_mismatch": sum(1 for x in neighbor_links if x["status"] == "mismatch"),
        "neighbor_missing": sum(1 for x in neighbor_links if x["status"] == "missing"),
        "neighbor_ok": sum(1 for x in neighbor_links if x["status"] == "ok"),
        "unconfirmed": len(unconfirmed),
        "alias": len(alias_checks),
        "neighbors_collected": bool(neighbors),
    }

    return {
        "summary": summary,
        "neighbor_links": neighbor_links,
        "unconfirmed": unconfirmed,
        "alias_checks": alias_checks,
    }
