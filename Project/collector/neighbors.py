"""LLDP and CDP neighbours of a switch, keyed by the local ifIndex.

LLDP-MIB  lldpRemTable   index: timeMark.localPortNum.remIndex
          lldpLocPortTable index: localPortNum (mapped to an ifIndex by the
          port name, or used as the ifIndex itself on Cisco/MikroTik)
CISCO-CDP-MIB cdpCacheTable index: ifIndex.deviceIndex
"""

import re
from typing import Dict, List

from ..bll.domain.cabling_check import short_interface_name
from .snmp.client import snmp_walk_raw
from .snmp.oids import (
    OID_CDP_CACHE_DEVICE_ID,
    OID_CDP_CACHE_DEVICE_PORT,
    OID_CDP_CACHE_PLATFORM,
    OID_IF_NAME,
    OID_LLDP_LOC_PORT_DESC,
    OID_LLDP_LOC_PORT_ID,
    OID_LLDP_REM_CHASSIS_ID,
    OID_LLDP_REM_PORT_DESC,
    OID_LLDP_REM_PORT_ID,
    OID_LLDP_REM_SYS_NAME,
)

_LINE = re.compile(r"^\.?([\d.]+)\s*=\s*(.*)$")


def parse_indexed_walk(lines: List[str], base_oid: str) -> Dict[tuple, str]:
    """snmpwalk -On output -> {(index parts after base_oid): value}.

    Hex-STRING values that net-snmp wraps over several lines are joined.
    """

    base = base_oid.strip(".")
    result = {}
    key = None

    for raw in lines:
        line = raw.rstrip()
        match = _LINE.match(line.strip())
        if not match:
            if key is not None and line.strip():
                result[key] = (result[key] + " " + line.strip()).strip()
            continue

        oid, value = match.group(1).strip("."), match.group(2).strip()
        if not oid.startswith(base + "."):
            key = None
            continue
        if "No Such" in value:
            key = None
            continue

        key = tuple(int(part) for part in oid[len(base) + 1:].split("."))
        if ":" in value:
            value = value.split(":", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        result[key] = value

    return result


def hex_to_text(value: str) -> str:
    """'00 1C 44 0D 33 E0' -> '00:1c:44:0d:33:e0'; other hex -> ASCII if printable."""

    parts = value.split()
    if not parts or not all(re.fullmatch(r"[0-9A-Fa-f]{2}", p) for p in parts):
        return value
    if len(parts) == 6:
        return ":".join(p.lower() for p in parts)
    text = bytes(int(p, 16) for p in parts).decode("latin-1").rstrip("\x00")
    return text if text.isprintable() else value


def _walk(host, community, oid):
    try:
        return parse_indexed_walk(snmp_walk_raw(host, community, oid), oid)
    except RuntimeError:
        return {}


def collect_neighbors(host: str, community: str) -> Dict[int, List[Dict]]:
    """{ifIndex: [{protocol, remote_name, remote_port, remote_port_desc, remote_chassis, remote_platform}]}"""

    if_names = {key[0]: value for key, value in _walk(host, community, OID_IF_NAME).items()}
    by_short_name = {short_interface_name(name): index for index, name in if_names.items()}

    neighbors: Dict[int, List[Dict]] = {}

    # ---- LLDP --------------------------------------------------------
    sys_names = _walk(host, community, OID_LLDP_REM_SYS_NAME)
    if sys_names:
        port_ids = _walk(host, community, OID_LLDP_REM_PORT_ID)
        port_descs = _walk(host, community, OID_LLDP_REM_PORT_DESC)
        chassis = _walk(host, community, OID_LLDP_REM_CHASSIS_ID)
        loc_ids = {k[0]: v for k, v in _walk(host, community, OID_LLDP_LOC_PORT_ID).items()}
        loc_descs = {k[0]: v for k, v in _walk(host, community, OID_LLDP_LOC_PORT_DESC).items()}

        def local_if_index(port_num):
            for candidate in (loc_ids.get(port_num), loc_descs.get(port_num)):
                index = by_short_name.get(short_interface_name(hex_to_text(candidate or "")))
                if index is not None:
                    return index
            return port_num if port_num in if_names else None

        for key in set(sys_names) | set(port_ids):
            if len(key) < 3:
                continue
            if_index = local_if_index(key[1])
            if if_index is None:
                continue
            entry = {
                "protocol": "lldp",
                "remote_name": hex_to_text(sys_names.get(key, "")),
                "remote_port": hex_to_text(port_ids.get(key, "")),
                "remote_port_desc": hex_to_text(port_descs.get(key, "")),
                "remote_chassis": hex_to_text(chassis.get(key, "")),
                "remote_platform": "",
            }
            if entry["remote_name"] or entry["remote_chassis"]:
                neighbors.setdefault(if_index, []).append(entry)

    # ---- CDP (Cisco) -------------------------------------------------
    device_ids = _walk(host, community, OID_CDP_CACHE_DEVICE_ID)
    if device_ids:
        device_ports = _walk(host, community, OID_CDP_CACHE_DEVICE_PORT)
        platforms = _walk(host, community, OID_CDP_CACHE_PLATFORM)
        for key, device_id in device_ids.items():
            if len(key) < 2:
                continue
            neighbors.setdefault(key[0], []).append({
                "protocol": "cdp",
                "remote_name": hex_to_text(device_id),
                "remote_port": hex_to_text(device_ports.get(key, "")),
                "remote_port_desc": "",
                "remote_chassis": "",
                "remote_platform": platforms.get(key, ""),
            })

    return neighbors
