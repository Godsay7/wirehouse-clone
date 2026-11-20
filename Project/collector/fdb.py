"""MAC address tables (FDB): ifIndex -> [MAC, ...]."""

import re
from typing import Dict, List, Tuple

from .snmp.client import snmp_walk_raw
from .snmp.oids import (
    OID_CISCO_VTP_VLAN_STATE,
    OID_DOT1D_BASE_PORT_IFINDEX,
    OID_DOT1D_TP_FDB_PORT,
    OID_DOT1Q_TP_FDB_PORT,
)
from .snmp.parsers import (
    parse_bridge_fdb,
    parse_bridge_port_ifindex,
    parse_qbridge_fdb,
)


def discover_cisco_vlans(
    host: str,
    community: str
) -> List[int]:
    """
    Discovers operational VLAN IDs using CISCO-VTP-MIB:

        vtpVlanState.<managementDomainIndex>.<vlanId>

    Example raw OID:

        ...1.3.1.1.2.1.140 = INTEGER: 1

    where:
        1   = VTP management-domain index
        140 = VLAN ID
        state 1 = operational
    """

    lines = snmp_walk_raw(
        host,
        community,
        OID_CISCO_VTP_VLAN_STATE
    )

    prefix = OID_CISCO_VTP_VLAN_STATE + "."
    vlans = set()

    for line in lines:

        line = line.strip()

        if not line or "=" not in line:
            continue

        oid_part, value_part = line.split(
            "=",
            1
        )

        oid_part = oid_part.strip().lstrip(".")
        value_part = value_part.strip()

        if not oid_part.startswith(prefix):
            continue

        suffix = oid_part[len(prefix):]
        parts = suffix.split(".")

        # Expected indexes:
        #   managementDomainIndex.vlanId
        if len(parts) < 2:
            continue

        try:
            vlan_id = int(parts[-1])
        except ValueError:
            continue

        state_match = re.search(
            r"(-?\d+)\s*$",
            value_part
        )

        if not state_match:
            continue

        state = int(state_match.group(1))

        # CISCO-VTP-MIB vtpVlanState:
        # 1 = operational
        if state != 1:
            continue

        if 1 <= vlan_id <= 4094:
            vlans.add(vlan_id)

    return sorted(vlans)


def add_fdb_entries_to_mac_map(
    mac_by_ifindex: Dict[int, List[str]],
    fdb_entries: List[Tuple[str, int]],
    bridge_port_map: Dict[int, int]
) -> int:
    """
    Adds FDB entries to mac_by_ifindex.

    Returns number of newly-added unique MAC/ifIndex pairs.
    Entries whose bridge port has no ifIndex mapping are ignored.
    """

    added = 0

    for mac, bridge_port in fdb_entries:

        # 0 means an invalid/not-learned bridge port in BRIDGE-MIB.
        if bridge_port <= 0:
            continue

        if_index = bridge_port_map.get(
            bridge_port
        )

        if if_index is None:
            continue

        mac_list = mac_by_ifindex.setdefault(
            if_index,
            []
        )

        if mac not in mac_list:
            mac_list.append(mac)
            added += 1

    return added


def collect_cisco_vlan_indexed_fdb(
    host: str,
    community: str
) -> Dict[int, List[str]]:
    """
    Collects MAC addresses from older Cisco Catalyst switches
    that expose BRIDGE-MIB in per-VLAN SNMP contexts.

    For each discovered VLAN both tables are queried with the
    SAME indexed community:

        community@VLAN

    Tables:
        dot1dTpFdbPort
        dot1dBasePortIfIndex

    This is necessary because bridge-port numbering belongs to
    that VLAN context and cannot safely be correlated with the
    default/global bridge mapping.
    """

    print(
        "Default FDB is empty/unusable. "
        "Trying Cisco VLAN-indexed FDB..."
    )

    vlans = discover_cisco_vlans(
        host,
        community
    )

    if not vlans:

        print(
            "Cisco VLAN discovery returned no "
            "operational VLANs."
        )

        return {}

    print(
        f"Cisco VLANs detected: {len(vlans)}"
    )

    mac_by_ifindex = {}
    vlans_with_fdb = 0
    vlans_with_mapped_macs = 0
    raw_fdb_entries = 0
    mapped_pairs = 0

    for vlan_id in vlans:

        indexed_community = (
            f"{community}@{vlan_id}"
        )

        # IMPORTANT: both FDB and bridge mapping must be queried
        # in the same VLAN context.
        bridge_lines = snmp_walk_raw(
            host,
            indexed_community,
            OID_DOT1D_BASE_PORT_IFINDEX
        )

        bridge_port_map = parse_bridge_port_ifindex(
            bridge_lines
        )

        if not bridge_port_map:
            # Some VLAN contexts do not instantiate a bridge.
            continue

        fdb_lines = snmp_walk_raw(
            host,
            indexed_community,
            OID_DOT1D_TP_FDB_PORT
        )

        fdb_entries = parse_bridge_fdb(
            fdb_lines
        )

        if not fdb_entries:
            continue

        vlans_with_fdb += 1
        raw_fdb_entries += len(fdb_entries)

        added = add_fdb_entries_to_mac_map(
            mac_by_ifindex,
            fdb_entries,
            bridge_port_map
        )

        if added > 0:
            vlans_with_mapped_macs += 1
            mapped_pairs += added

    unique_macs = {
        mac
        for macs in mac_by_ifindex.values()
        for mac in macs
    }

    if mac_by_ifindex:

        print(
            "Cisco VLAN-indexed FDB collected: "
            f"{len(unique_macs)} unique MACs, "
            f"{mapped_pairs} MAC/interface mappings, "
            f"{vlans_with_mapped_macs}/{len(vlans)} VLANs "
            "with mapped MACs."
        )

    else:

        print(
            "Cisco VLAN-indexed FDB returned no MACs "
            "that could be mapped to ifIndex "
            f"(FDB present in {vlans_with_fdb}/{len(vlans)} "
            f"VLANs, {raw_fdb_entries} raw FDB entries)."
        )

    return mac_by_ifindex


def collect_mac_addresses(
    host: str,
    community: str,
    bridge_port_map: Dict[int, int]
) -> Dict[int, List[str]]:
    """
    Returns:

        ifIndex -> [MAC, MAC, ...]

    Collection order:

      1. Q-BRIDGE-MIB in the default SNMP context.
      2. BRIDGE-MIB in the default SNMP context (only if 1 gave nothing).
      3. Cisco VLAN-indexed BRIDGE-MIB using community@VLAN.

    On Cisco IOS the default context shows only VLAN 1, so a switch can
    return a few MACs there and keep the rest in other VLANs. Step 3 is
    therefore always tried and its MACs are merged with steps 1-2; on
    switches without CISCO-VTP-MIB it finds no VLANs and adds nothing.
    """

    print(
        "Collecting MAC addresses..."
    )

    # --------------------------------------------------------
    # 1. Q-BRIDGE-MIB (default context)
    # --------------------------------------------------------

    lines = snmp_walk_raw(
        host,
        community,
        OID_DOT1Q_TP_FDB_PORT
    )

    fdb_entries = parse_qbridge_fdb(
        lines
    )

    mac_by_ifindex = {}

    if fdb_entries:

        add_fdb_entries_to_mac_map(
            mac_by_ifindex,
            fdb_entries,
            bridge_port_map
        )

    # --------------------------------------------------------
    # 2. BRIDGE-MIB (default context)
    # --------------------------------------------------------

    if not mac_by_ifindex:

        lines = snmp_walk_raw(
            host,
            community,
            OID_DOT1D_TP_FDB_PORT
        )

        fdb_entries = parse_bridge_fdb(
            lines
        )

        if fdb_entries:

            add_fdb_entries_to_mac_map(
                mac_by_ifindex,
                fdb_entries,
                bridge_port_map
            )

    # --------------------------------------------------------
    # 3. Cisco VLAN-indexed BRIDGE-MIB, merged with the above
    # --------------------------------------------------------

    vlan_macs = collect_cisco_vlan_indexed_fdb(
        host,
        community
    )

    for if_index, macs in vlan_macs.items():

        mac_list = mac_by_ifindex.setdefault(
            if_index,
            []
        )

        for mac in macs:
            if mac not in mac_list:
                mac_list.append(mac)

    if mac_by_ifindex:
        return mac_by_ifindex

    print(
        "WARNING: FDB не вернул MAC-адреса."
    )

    return {}
