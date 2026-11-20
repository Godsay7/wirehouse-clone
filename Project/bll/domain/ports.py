"""Port enrichment (MAC -> IP -> hostname) and port search matching."""

import ipaddress
import re

from ...core.mac import normalize_mac, split_macs
from ...core.text import normalize_value
from ...core.vlan import parse_vlans, vlan_summary

# "vlan 140", "VLAN140", "vlan:140" in a search box.
VLAN_SEARCH = re.compile(r"^vlan\s*[:#]?\s*(\d{1,4})$", re.IGNORECASE)


def vlan_search(search):
    """The VLAN id when the search asks for a VLAN, else None."""

    match = VLAN_SEARCH.match(str(search or "").strip())
    return int(match.group(1)) if match else None


def add_vlan_fields(port):
    """vlan_text ("140", "trunk 1 + 10-20"), vlan_ids (every VLAN on the port)."""

    tagged = port.get("vlan_tagged") or ""
    port["vlan_text"] = vlan_summary(port.get("vlan_mode"), port.get("vlan"), tagged)
    ids = set(parse_vlans(tagged))
    if port.get("vlan"):
        ids.add(int(port["vlan"]))
    port["vlan_ids"] = ids
    return port


def build_arp_map(rows):
    """Return MAC -> list of known ARP records (rows must be newest first)."""

    result = {}

    for row in rows:
        mac = normalize_mac(row["mac"])

        if not mac:
            continue

        entries = result.setdefault(
            mac,
            []
        )

        # Do not add the same IP twice for one MAC.
        if any(
            entry["ip"] == row["ip"]
            for entry in entries
        ):
            continue

        entries.append(
            {
                "ip": normalize_value(row["ip"]),
                "hostname": normalize_value(row["hostname"]),
                "if_index": row["if_index"],
                "last_seen": row["last_seen"],
            }
        )

    return result


def enrich_port(
    row,
    arp_map
):
    """Add MAC->IP->hostname information to one port row."""

    port = add_vlan_fields(dict(row))

    mac_list = split_macs(
        port.get("mac")
    )

    arp_entries = []
    ips = []
    hostnames = []

    for mac in mac_list:
        for arp_entry in arp_map.get(mac, []):
            arp_entries.append(
                {
                    "mac": mac,
                    **arp_entry,
                }
            )

            ip = arp_entry.get("ip")

            if (
                ip
                and ip != "-"
                and ip not in ips
            ):
                ips.append(ip)

            hostname = arp_entry.get("hostname")

            if (
                hostname
                and hostname != "-"
                and hostname not in hostnames
            ):
                hostnames.append(hostname)

    port["mac_list"] = mac_list
    port["arp_entries"] = arp_entries
    port["ips"] = ips
    port["hostnames"] = hostnames
    port["ip_display"] = ", ".join(ips) if ips else "-"
    port["hostname_display"] = (
        ", ".join(hostnames)
        if hostnames
        else "-"
    )

    return port


class DocumentedNames:
    """Names of devices that DNS does not give us.

    manual:  MAC -> hostname typed in by hand (wins over everything)
    by_mac:  MAC -> name of a documented (expected) device
    by_ip:   IP -> PC name on a floor map (its Dante IP too)
    by_port: (switch_id, port) -> what the documented cable leads to (a
             server, a wall socket's note) or the note on the port itself
    """

    # A port with more devices than this is an uplink: its cable / note
    # names the next switch, not a device, and its devices are not listed
    # one by one for editing.
    MAX_DEVICES_FOR_PORT_NAME = 2

    def __init__(self, by_mac=None, by_ip=None, by_port=None, manual=None):
        self.manual = {normalize_mac(mac): name for mac, name in (manual or {}).items() if normalize_mac(mac) and name}
        self.by_mac = {normalize_mac(mac): name for mac, name in (by_mac or {}).items() if normalize_mac(mac) and name}
        self.by_ip = {ip: name for ip, name in (by_ip or {}).items() if ip and name}
        self.by_port = {key: name for key, name in (by_port or {}).items() if name}

    def names_for(self, port):
        """Documentation names for a port's devices, in the order of its MACs / IPs."""

        names = []

        def add(name):
            if name and name not in names:
                names.append(name)

        for mac in port.get("mac_list", []):
            add(self.by_mac.get(mac))
        for ip in port.get("ips", []):
            add(self.by_ip.get(ip))
        if not names and 0 < len(port.get("mac_list", [])) <= self.MAX_DEVICES_FOR_PORT_NAME:
            add(self.by_port.get((port.get("switch_id"), port.get("port"))))
        return names

    def device_name(self, port, mac):
        """(name, source) of one device: "manual", "dns", "doc" or ("", "")."""

        if self.manual.get(mac):
            return self.manual[mac], "manual"
        entries = [entry for entry in port.get("arp_entries", []) if entry.get("mac") == mac]
        for entry in entries:
            if entry.get("hostname") not in (None, "", "-"):
                return entry["hostname"], "dns"
        if self.by_mac.get(mac):
            return self.by_mac[mac], "doc"
        for entry in entries:
            if self.by_ip.get(entry.get("ip")):
                return self.by_ip[entry["ip"]], "doc"
        if len(port.get("mac_list", [])) == 1:
            name = self.by_port.get((port.get("switch_id"), port.get("port")))
            if name:
                return name, "doc"
        return "", ""


def add_documented_names(port, documented):
    """Names for a port's devices when DNS has none (or a hand-typed one).

    port["devices"]: [{"mac", "name", "source"}] for ports with at most
    MAX_DEVICES_FOR_PORT_NAME devices (each can get a hostname by hand);
    port["manual_names"] / ["doc_names"]; hostname_display (searchable);
    hostname_source: "manual", "dns", "doc" or "" (nothing known).
    """

    documented = documented or DocumentedNames()
    macs = port.get("mac_list", [])
    port["devices"] = []
    if 0 < len(macs) <= documented.MAX_DEVICES_FOR_PORT_NAME:
        for mac in macs:
            name, source = documented.device_name(port, mac)
            port["devices"].append({"mac": mac, "name": name, "source": source})

    port["manual_names"] = []
    for mac in macs:
        name = documented.manual.get(mac)
        if name and name not in port["manual_names"]:
            port["manual_names"].append(name)
    port["doc_names"] = []

    if port["manual_names"]:
        names = port["manual_names"] + [name for name in port.get("hostnames", []) if name not in port["manual_names"]]
        port["hostname_display"] = ", ".join(names)
        port["hostname_source"] = "manual"
    elif port.get("hostnames"):
        port["hostname_source"] = "dns"
    else:
        port["doc_names"] = documented.names_for(port)
        if port["doc_names"]:
            port["hostname_display"] = ", ".join(port["doc_names"])
            port["hostname_source"] = "doc"
        else:
            port["hostname_source"] = ""
    return port


def add_written_name_and_last_known(port, written, documented, arp_map):
    """The name written on the port (Cabling Check) and, while the port shows
    no device (link down or no MAC), the last MAC seen there.

    port["written"]: {"name", "mac", "confirmed"} or None
    port["last_known"]: {"mac", "name", "at"} or None — only when the port has
    no device right now and a MAC was seen on it before.
    """

    port["written"] = None
    if written:
        port["written"] = {"name": written["name"], "mac": written["mac"], "confirmed": bool(written["confirmed_at"]),
                           "manual": not written["mac"]}

    port["last_known"] = None
    last_mac = normalize_mac(port.get("last_mac"))
    live = port.get("link") == "UP" and port.get("mac_list")
    if last_mac and not live:
        name = (documented.manual.get(last_mac) if documented else "") or ""
        if not name:
            name = next((entry["hostname"] for entry in arp_map.get(last_mac, [])
                         if entry.get("hostname") not in (None, "", "-")), "")
        if not name and documented:
            name = documented.by_mac.get(last_mac, "")
        if not name and written and normalize_mac(written["mac"]) == last_mac:
            name = written["name"]
        port["last_known"] = {"mac": last_mac, "name": name, "at": port.get("last_mac_at")}
    return port


class InventorySearchTerm:
    """Search term for the dashboard: plain text or (part of) a MAC address."""

    def __init__(self, search):
        self.term = str(search or "").strip()
        self.lower = self.term.lower()
        self.mac_compact = re.sub(r"[^0-9a-f]", "", self.lower)
        self.looks_like_mac = (
            any(separator in self.term for separator in (":", "-", "."))
            or (len(self.mac_compact) >= 6 and self.mac_compact == self.lower)
        )

    def __bool__(self):
        return bool(self.term)

    def matches(self, port):
        """port is an enriched port row that includes switch_name."""

        vlan = vlan_search(self.term)
        if vlan is not None:
            return vlan in port.get("vlan_ids", ())

        text_values = [
            port.get("switch_name"),
            port.get("device"),
            port.get("if_name"),
            port.get("ip_display"),
            port.get("hostname_display"),
            port.get("mac"),
        ]

        if any(
            self.lower in str(value or "").lower()
            for value in text_values
        ):
            return True

        if self.looks_like_mac and self.mac_compact:
            for mac in port.get("mac_list", []):
                compact_mac = re.sub(r"[^0-9a-f]", "", mac.lower())
                if self.mac_compact in compact_mac:
                    return True

        return False


def switch_port_matches(port, search_lower):
    """Search filter on the switch page ("vlan 140": ports carrying VLAN 140)."""

    vlan = vlan_search(search_lower)
    if vlan is not None:
        return vlan in port.get("vlan_ids", ())

    searchable_values = [
        str(port.get("port", "")),
        normalize_value(port.get("device")),
        normalize_value(port.get("mac")),
        normalize_value(port.get("if_name")),
        port.get("ip_display", "-"),
        port.get("hostname_display", "-"),
    ]

    return any(
        search_lower in str(value).lower()
        for value in searchable_values
    )


def _text(value):
    value = normalize_value(value)
    return "" if value == "-" else value


def _canonical_ip(value):
    try:
        return str(ipaddress.ip_address(str(value or "").strip()))
    except ValueError:
        return ""


def locate_ips(ips, arp_rows, port_rows, max_ports=3):
    """Where each IP is plugged in: IP -> MAC (ARP) -> switch port (FDB).

    A MAC is learned on its access port and on every uplink on the way to the
    core, so the port with the fewest MACs wins (ties are all returned, up to
    ``max_ports``). arp_rows must be newest first.

    Returns {ip: {"found": False}} or {ip: {"found": True, "mac", "hostname",
    "last_seen", "ports": [{"switch_id", "switch", "port", "port_name",
    "link", "description", "mac_count"}, ...]}}.
    """

    wanted = {_canonical_ip(ip): ip for ip in ips if _canonical_ip(ip)}

    arp_by_ip = {}
    for row in arp_rows:
        ip = _canonical_ip(row["ip"])
        if ip in wanted and ip not in arp_by_ip:
            arp_by_ip[ip] = row

    macs = {normalize_mac(row["mac"]) for row in arp_by_ip.values()}
    ports_by_mac = {}
    for row in port_rows:
        port_macs = split_macs(row["mac"])
        for mac in port_macs:
            if mac in macs:
                ports_by_mac.setdefault(mac, []).append((len(port_macs), row))

    result = {}
    for ip, original in wanted.items():
        arp = arp_by_ip.get(ip)
        if arp is None:
            result[original] = {"found": False}
            continue

        mac = normalize_mac(arp["mac"])
        candidates = sorted(ports_by_mac.get(mac, []), key=lambda item: (item[0], item[1]["switch_name"], item[1]["port"]))
        fewest = candidates[0][0] if candidates else 0

        result[original] = {
            "found": True,
            "mac": mac,
            "hostname": _text(arp["hostname"]),
            "last_seen": arp["last_seen"],
            "ports": [
                {
                    "switch_id": row["switch_id"],
                    "switch": row["switch_name"],
                    "port": row["port"],
                    "port_name": row["if_name"] or f"Port {row['port']}",
                    "link": _text(row["link"]),
                    "description": _text(row["device"]),
                    "mac_count": count,
                }
                for count, row in candidates
                if count == fewest
            ][:max_ports],
        }

    return result


def locate_macs(macs, port_rows, max_ports=3):
    """Like locate_ips, for known MACs (e.g. documented devices without an IP).

    Returns {mac: {"found": True, "mac", "hostname": "", "ports": [...]}} for
    MACs seen on some port; the port with the fewest MACs wins."""

    macs = {normalize_mac(mac) for mac in macs if mac}
    ports_by_mac = {}
    for row in port_rows:
        port_macs = split_macs(row["mac"])
        for mac in port_macs:
            if mac in macs:
                ports_by_mac.setdefault(mac, []).append((len(port_macs), row))

    result = {}
    for mac, candidates in ports_by_mac.items():
        candidates.sort(key=lambda item: (item[0], item[1]["switch_name"], item[1]["port"]))
        fewest = candidates[0][0]
        result[mac] = {
            "found": True,
            "mac": mac,
            "hostname": "",
            "by": "documented MAC",
            "ports": [
                {
                    "switch_id": row["switch_id"],
                    "switch": row["switch_name"],
                    "port": row["port"],
                    "port_name": row["if_name"] or f"Port {row['port']}",
                    "link": _text(row["link"]),
                    "description": _text(row["device"]),
                    "mac_count": count,
                }
                for count, row in candidates
                if count == fewest
            ][:max_ports],
        }
    return result


def port_is_expected(port):
    """Something should be on this switch port: a documented cable, a
    description, a name typed in, or a device seen there before. A down port
    is a fault only then; other down ports are just free."""

    device = (port.get("device") or "").strip()
    return bool(port.get("cabled") or (device and device != "-") or port.get("written") or port.get("last_mac"))


# The management port of a mounted switch (rack_switches.mgmt_port): not in
# SNMP, drawn after the switch ports as "mng"; cables use this port number.
SWITCH_MGMT_PORT = 0


def switch_port_label(port):
    """'mng' for the management port, else the port number as text."""

    return "mng" if port == SWITCH_MGMT_PORT else str(port)
