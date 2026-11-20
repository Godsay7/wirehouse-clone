"""VLANs of each port: access VLAN, or trunk with its native and tagged VLANs.

Two sources, whichever the switch answers:

* Q-BRIDGE-MIB (Dell, MikroTik, Cisco CBS, most non-Cisco switches):
  dot1qPvid.<bridgePort> is the untagged (access / native) VLAN, and the
  per-VLAN port bitmaps dot1qVlanCurrentEgressPorts / ...UntaggedPorts
  (or the static ones) say which ports carry which VLAN tagged. Dell OS10
  has no dot1qPvid: the VLAN a port is untagged in is used instead.
  MikroTik has only dot1qPvid, so its trunks show the native VLAN only.
* Cisco IOS (CISCO-VTP-MIB, CISCO-VLAN-MEMBERSHIP-MIB): vlanTrunkPortDynamicStatus
  says whether a port is trunking; trunks have vlanTrunkPortNativeVlan and the
  4 x 1024-bit vlanTrunkPortVlansEnabled bitmaps, access ports have vmVlan.

The result per ifIndex: {"mode": "access"|"trunk", "vlan": native/access id
or None, "tagged": [vlan ids]}. Ports a switch says nothing about are left out.
"""

from typing import Dict, List, Optional

from ..core.vlan import format_vlans  # noqa: F401  (re-exported for callers)

from .snmp.client import snmp_walk_table
from .snmp.oids import (
    OID_CISCO_TRUNK_NATIVE_VLAN,
    OID_CISCO_TRUNK_STATUS,
    OID_CISCO_TRUNK_VLANS_ENABLED,
    OID_CISCO_TRUNK_VLANS_ENABLED_2K,
    OID_CISCO_TRUNK_VLANS_ENABLED_3K,
    OID_CISCO_TRUNK_VLANS_ENABLED_4K,
    OID_CISCO_VM_VLAN,
    OID_DOT1Q_PVID,
    OID_DOT1Q_VLAN_CURRENT_EGRESS,
    OID_DOT1Q_VLAN_CURRENT_UNTAGGED,
    OID_DOT1Q_VLAN_STATIC_EGRESS,
    OID_DOT1Q_VLAN_STATIC_UNTAGGED,
)

CISCO_TRUNKING = "1"


def hex_bytes(value: str) -> bytes:
    """'80 00 0F' / '80:00:0F' / '0x80000F' -> bytes; anything else -> b''."""

    text = (value or "").strip().replace(":", " ")
    if text.lower().startswith("0x"):
        text = text[2:]
    text = "".join(text.split())
    if len(text) % 2 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        return b""
    return bytes.fromhex(text)


def bitmap_members(data: bytes, first: int = 1) -> List[int]:
    """Set bits of an SNMP PortList / VLAN bitmap, most significant bit first.

    PortList: bit 0 of byte 0 (0x80) is bridge port 1, so first=1.
    Cisco vlansEnabled: the first bit is VLAN 0 (first=0), the 2k table
    starts at 1024 and so on.
    """

    members = []
    for byte_index, byte in enumerate(data):
        for bit in range(8):
            if byte & (0x80 >> bit):
                members.append(first + byte_index * 8 + bit)
    return members


def _int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def qbridge_vlans(pvid: Dict, egress: Dict, untagged: Dict, bridge_to_if: Dict[int, int]) -> Dict[int, Dict]:
    """Q-BRIDGE-MIB tables -> per-ifIndex VLANs.

    pvid: bridgePort -> VLAN; egress / untagged: VLAN -> PortList hex string
    (the index of the current tables starts with a time mark; only the last
    number, the VLAN, is used); bridge_to_if: bridgePort -> ifIndex.
    """

    tagged: Dict[int, List[int]] = {}
    untagged_on: Dict[int, List[int]] = {}
    for vlan, value in egress.items():
        vlan_id = int(vlan[-1] if isinstance(vlan, tuple) else vlan)
        untagged_ports = set(bitmap_members(hex_bytes(untagged.get(vlan, ""))))
        for bridge_port in untagged_ports:
            untagged_on.setdefault(bridge_port, []).append(vlan_id)
        for bridge_port in bitmap_members(hex_bytes(value)):
            if bridge_port not in untagged_ports:
                tagged.setdefault(bridge_port, []).append(vlan_id)

    result = {}
    for bridge_port, if_index in bridge_to_if.items():
        access = _int(pvid.get(bridge_port))
        # No dot1qPvid (Dell OS10): the VLAN the port is untagged in.
        if access is None and len(untagged_on.get(bridge_port, [])) == 1:
            access = untagged_on[bridge_port][0]
        port_tagged = sorted(set(tagged.get(bridge_port, [])) - {access})
        if access is None and not port_tagged:
            continue
        result[if_index] = {
            "mode": "trunk" if port_tagged else "access",
            "vlan": access,
            "tagged": port_tagged,
        }
    return result


def cisco_vlans(status: Dict, native: Dict, enabled: List[Dict], access: Dict) -> Dict[int, Dict]:
    """Cisco IOS tables (all indexed by ifIndex) -> per-ifIndex VLANs.

    enabled: the four vlanTrunkPortVlansEnabled tables (VLANs 0-1023,
    1024-2047, 2048-3071, 3072-4095).
    """

    result = {}
    for if_index, state in status.items():
        if str(state).strip() != CISCO_TRUNKING:
            continue
        vlans = []
        for block, table in enumerate(enabled):
            vlans += bitmap_members(hex_bytes(table.get(if_index, "")), first=block * 1024)
        native_vlan = _int(native.get(if_index))
        result[if_index] = {
            "mode": "trunk",
            "vlan": native_vlan,
            "tagged": sorted(v for v in vlans if 1 <= v <= 4094 and v != native_vlan),
        }
    for if_index, vlan in access.items():
        if if_index not in result and _int(vlan):
            result[if_index] = {"mode": "access", "vlan": _int(vlan), "tagged": []}
    return result


def collect_vlans(host: str, community: str, bridge_to_if: Dict[int, int]) -> Dict[int, Dict]:
    """VLANs per ifIndex; {} when the switch exposes neither MIB."""

    status = snmp_walk_table(host, community, OID_CISCO_TRUNK_STATUS)
    if status:
        tables = [snmp_walk_table(host, community, oid, hex_values=True) for oid in (
            OID_CISCO_TRUNK_VLANS_ENABLED, OID_CISCO_TRUNK_VLANS_ENABLED_2K,
            OID_CISCO_TRUNK_VLANS_ENABLED_3K, OID_CISCO_TRUNK_VLANS_ENABLED_4K)]
        return cisco_vlans(
            _last(status),
            _last(snmp_walk_table(host, community, OID_CISCO_TRUNK_NATIVE_VLAN)),
            [_last(table) for table in tables],
            _last(snmp_walk_table(host, community, OID_CISCO_VM_VLAN)),
        )

    pvid = _last(snmp_walk_table(host, community, OID_DOT1Q_PVID))
    egress = _last(snmp_walk_table(host, community, OID_DOT1Q_VLAN_CURRENT_EGRESS, hex_values=True))
    untagged = _last(snmp_walk_table(host, community, OID_DOT1Q_VLAN_CURRENT_UNTAGGED, hex_values=True))
    if not egress:
        egress = _last(snmp_walk_table(host, community, OID_DOT1Q_VLAN_STATIC_EGRESS, hex_values=True))
        untagged = _last(snmp_walk_table(host, community, OID_DOT1Q_VLAN_STATIC_UNTAGGED, hex_values=True))
    if not pvid and not egress:
        return {}
    return qbridge_vlans(pvid, egress, untagged, bridge_to_if)


def _last(table: Dict[tuple, str]) -> Dict[int, str]:
    """Index tuples -> their last number (ifIndex, bridge port or VLAN)."""

    return {index[-1]: value for index, value in table.items()}
