"""Parsers for raw snmpwalk output lines (net-snmp, -On)."""

import re
from typing import Dict, List, Tuple

from .oids import (
    OID_DOT1D_BASE_PORT_IFINDEX,
    OID_DOT1D_TP_FDB_PORT,
    OID_DOT1Q_TP_FDB_PORT,
    OID_IP_NET_TO_MEDIA_PHYS_ADDRESS,
    OID_IP_NET_TO_PHYSICAL_PHYS_ADDRESS,
)


def numbers_to_mac(
    numbers: List[str]
) -> str:

    if len(numbers) != 6:
        return "-"

    try:

        values = [
            int(x)
            for x in numbers
        ]

    except ValueError:

        return "-"

    if any(
        x < 0 or x > 255
        for x in values
    ):

        return "-"

    return ":".join(
        f"{x:02x}"
        for x in values
    )


def parse_qbridge_fdb(
    lines: List[str]
) -> List[Tuple[str, int]]:

    result = []

    prefix = (
        OID_DOT1Q_TP_FDB_PORT
        + "."
    )

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if "=" not in line:
            continue

        oid_part = line.split(
            "=",
            1
        )[0].strip()

        if prefix not in oid_part:
            continue

        suffix = oid_part.split(
            prefix,
            1
        )[1]

        parts = suffix.split(".")

        # VLAN + 6 MAC bytes

        if len(parts) != 7:
            continue

        try:

            int(parts[0])

        except ValueError:

            continue

        mac = numbers_to_mac(
            parts[1:]
        )

        if mac == "-":
            continue

        value_part = line.split(
            "=",
            1
        )[1].strip()

        match = re.search(
            r"(-?\d+)\s*$",
            value_part
        )

        if not match:
            continue

        bridge_port = int(
            match.group(1)
        )

        result.append(
            (
                mac,
                bridge_port
            )
        )

    return result


def parse_bridge_fdb(
    lines: List[str]
) -> List[Tuple[str, int]]:

    result = []

    prefix = (
        OID_DOT1D_TP_FDB_PORT
        + "."
    )

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if "=" not in line:
            continue

        oid_part = line.split(
            "=",
            1
        )[0].strip()

        if prefix not in oid_part:
            continue

        suffix = oid_part.split(
            prefix,
            1
        )[1]

        parts = suffix.split(".")

        if len(parts) != 6:
            continue

        mac = numbers_to_mac(
            parts
        )

        if mac == "-":
            continue

        value_part = line.split(
            "=",
            1
        )[1].strip()

        match = re.search(
            r"(-?\d+)\s*$",
            value_part
        )

        if not match:
            continue

        bridge_port = int(
            match.group(1)
        )

        result.append(
            (
                mac,
                bridge_port
            )
        )

    return result


def parse_bridge_port_ifindex(
    lines: List[str]
) -> Dict[int, int]:
    """
    Parses dot1dBasePortIfIndex and returns:

        bridge_port -> ifIndex

    This raw parser is required for Cisco VLAN-indexed contexts
    because dot1dBasePortIfIndex must be queried with the SAME
    community@VLAN as dot1dTpFdbPort.
    """

    result = {}
    prefix = OID_DOT1D_BASE_PORT_IFINDEX + "."

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

        # dot1dBasePortIfIndex has one table index:
        # the bridge-port number.
        if not suffix.isdigit():
            continue

        bridge_port = int(suffix)

        match = re.search(
            r"(-?\d+)\s*$",
            value_part
        )

        if not match:
            continue

        if_index = int(match.group(1))

        if bridge_port <= 0 or if_index <= 0:
            continue

        result[bridge_port] = if_index

    return result


def parse_snmp_mac_value(line: str) -> str:
    """Extract a normal aa:bb:cc:dd:ee:ff MAC from one snmpwalk line."""

    if "=" not in line:
        return ""

    value = line.split("=", 1)[1].strip()
    payload = value.split(":", 1)[1].strip() if ":" in value else value

    # Typical net-snmp forms:
    #   Hex-STRING: AA BB CC DD EE FF
    #   STRING: aa:bb:cc:dd:ee:ff
    hex_bytes = re.findall(r"(?i)(?<![0-9a-f])([0-9a-f]{2})(?![0-9a-f])", payload)
    if len(hex_bytes) >= 6:
        mac = ":".join(part.lower() for part in hex_bytes[:6])
    else:
        compact = re.sub(r"[^0-9A-Fa-f]", "", payload)
        if len(compact) < 12:
            return ""
        compact = compact[:12].lower()
        mac = ":".join(compact[i:i + 2] for i in range(0, 12, 2))

    if mac in {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}:
        return ""

    return mac


def parse_ipnet_to_physical(lines: List[str]) -> List[Dict]:
    """Parse IPv4 entries from IP-MIB ipNetToPhysicalPhysAddress."""

    result = []
    prefix = OID_IP_NET_TO_PHYSICAL_PHYS_ADDRESS + "."

    for line in lines:
        if "=" not in line:
            continue

        oid_part = line.split("=", 1)[0].strip().lstrip(".")
        normalized_prefix = prefix.lstrip(".")
        if not oid_part.startswith(normalized_prefix):
            continue

        suffix = oid_part[len(normalized_prefix):]
        try:
            parts = [int(part) for part in suffix.split(".") if part != ""]
        except ValueError:
            continue

        # Expected suffix is normally:
        #   <ifIndex>.1.<a>.<b>.<c>.<d>
        # Some agents include InetAddress length:
        #   <ifIndex>.1.4.<a>.<b>.<c>.<d>
        if len(parts) < 6:
            continue

        if_index = parts[0]
        address_type = parts[1]
        if address_type != 1:  # IPv4 only
            continue

        addr_parts = parts[2:]
        if len(addr_parts) == 5 and addr_parts[0] == 4:
            addr_parts = addr_parts[1:]
        if len(addr_parts) != 4 or any(octet < 0 or octet > 255 for octet in addr_parts):
            continue

        mac = parse_snmp_mac_value(line)
        if not mac:
            continue

        result.append({
            "mac": mac,
            "ip": ".".join(str(octet) for octet in addr_parts),
            "if_index": if_index,
        })

    return result


def parse_ipnet_to_media(lines: List[str]) -> List[Dict]:
    """Parse IPv4 entries from legacy MIB-II ipNetToMediaPhysAddress."""

    result = []
    prefix = OID_IP_NET_TO_MEDIA_PHYS_ADDRESS + "."

    for line in lines:
        if "=" not in line:
            continue

        oid_part = line.split("=", 1)[0].strip().lstrip(".")
        normalized_prefix = prefix.lstrip(".")
        if not oid_part.startswith(normalized_prefix):
            continue

        suffix = oid_part[len(normalized_prefix):]
        try:
            parts = [int(part) for part in suffix.split(".") if part != ""]
        except ValueError:
            continue

        if len(parts) != 5:
            continue

        if_index = parts[0]
        addr_parts = parts[1:]
        if any(octet < 0 or octet > 255 for octet in addr_parts):
            continue

        mac = parse_snmp_mac_value(line)
        if not mac:
            continue

        result.append({
            "mac": mac,
            "ip": ".".join(str(octet) for octet in addr_parts),
            "if_index": if_index,
        })

    return result
