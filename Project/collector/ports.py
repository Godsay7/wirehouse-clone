"""Collect the physical ports of one (logical) switch."""

from typing import Dict, List, Optional

from .fdb import collect_mac_addresses
from .port_errors import collect_error_counters
from .vlans import collect_vlans
from .interfaces import (
    extract_port_number,
    format_link,
    format_speed,
    interface_sort_key,
    is_physical_ethernet,
)
from .snmp.client import snmp_walk
from .snmp.oids import (
    OID_DOT1D_BASE_PORT_IFINDEX,
    OID_IF_ALIAS,
    OID_IF_HIGH_SPEED,
    OID_IF_NAME,
    OID_IF_OPER_STATUS,
)


def collect_switch(
    host: str,
    community: str,
    interface_prefix: Optional[List[str]] = None
) -> List[Dict]:
    """
    interface_prefix:

        Если задан - собираются только интерфейсы,
        имя которых начинается с одного из указанных
        префиксов (регистр не важен).

        Нужно, чтобы разделить один физический свич
        на несколько логических (например, свич с двумя
        независимыми стеками на одном IP).

        Если не задан - собираются все физические порты.
    """

    print(
        f"Collecting interface names from {host}..."
    )

    interface_names = snmp_walk(
        host,
        community,
        OID_IF_NAME
    )

    if not interface_names:

        raise RuntimeError(
            f"Не удалось получить список "
            f"интерфейсов с {host}"
        )

    print(
        "Collecting interface descriptions..."
    )

    interface_aliases = snmp_walk(
        host,
        community,
        OID_IF_ALIAS
    )

    print(
        "Collecting interface speeds..."
    )

    interface_speeds = snmp_walk(
        host,
        community,
        OID_IF_HIGH_SPEED
    )

    print(
        "Collecting interface status..."
    )

    interface_status = snmp_walk(
        host,
        community,
        OID_IF_OPER_STATUS
    )

    # --------------------------------------------------------
    # Physical ports
    # --------------------------------------------------------

    physical_ports = []

    for if_index, interface_name in interface_names.items():

        if not is_physical_ethernet(
            interface_name
        ):
            continue

        # ------------------------------------------------
        # Фильтр по префиксу интерфейса.
        #
        # Используется для разделения одного физического
        # свича на несколько логических (например, SW106
        # и SW107 на одном host).
        # ------------------------------------------------

        if interface_prefix:

            name_lower = interface_name.lower()

            matched = any(
                name_lower.startswith(
                    prefix.lower()
                )
                for prefix in interface_prefix
            )

            if not matched:
                continue

        port_number = extract_port_number(
            interface_name
        )

        if port_number <= 0:
            continue

        physical_ports.append(
            (
                if_index,
                interface_name,
                port_number
            )
        )

    # --------------------------------------------------------
    # Естественная сортировка физических интерфейсов.
    #
    # Важно для Cisco, где разные типы интерфейсов могут
    # иметь одинаковый последний номер:
    #
    #   Gi1/0/1
    #   Gi1/0/2
    #   ...
    #   Gi1/0/48
    #   Te1/1/1
    #   Te1/1/2
    #
    # TenGigabit-порты должны идти после Gigabit-портов,
    # а не перемешиваться по последней цифре.
    # --------------------------------------------------------

    physical_ports.sort(
        key=lambda x: interface_sort_key(
            x[1]
        )
    )

    if not physical_ports:

        raise RuntimeError(
            f"ERROR: Physical Ethernet ports "
            f"не найдены на {host}"
            + (
                f" (префикс: {', '.join(interface_prefix)})"
                if interface_prefix
                else "."
            )
        )

    # --------------------------------------------------------
    # Bridge port -> ifIndex
    # --------------------------------------------------------

    bridge_port_map = {}

    bridge_mapping = snmp_walk(
        host,
        community,
        OID_DOT1D_BASE_PORT_IFINDEX
    )

    for bridge_port, if_index_value in bridge_mapping.items():

        try:

            if_index = int(
                if_index_value
            )

        except (
            ValueError,
            TypeError
        ):

            continue

        bridge_port_map[
            bridge_port
        ] = if_index

    # --------------------------------------------------------
    # MAC
    # --------------------------------------------------------

    mac_by_ifindex = collect_mac_addresses(
        host,
        community,
        bridge_port_map
    )

    # --------------------------------------------------------
    # VLANs and error counters (optional: {} when not answered)
    # --------------------------------------------------------

    print(
        "Collecting VLANs and error counters..."
    )

    try:
        vlans_by_ifindex = collect_vlans(host, community, bridge_port_map)
    except Exception as error:  # a VLAN table must not stop the poll
        print(f"VLANs not collected: {error}")
        vlans_by_ifindex = {}

    try:
        errors_by_ifindex = collect_error_counters(host, community)
    except Exception as error:
        print(f"Error counters not collected: {error}")
        errors_by_ifindex = {}

    # --------------------------------------------------------
    # Build result
    # --------------------------------------------------------

    result = []

    # --------------------------------------------------------
    # ВАЖНО:
    #
    # Port — порядковый физический номер.
    #
    # То есть для:
    #
    # Gi1/1 ... Gi1/48
    #
    # получим:
    #
    # 1 ... 48
    #
    # Для:
    #
    # ether1 ... ether24
    #
    # получим:
    #
    # 1 ... 24
    # --------------------------------------------------------

    # --------------------------------------------------------
    # После правильной сортировки присваиваем отображаемый
    # Port последовательно: 1, 2, 3...
    #
    # Это гарантирует, что:
    #
    #   Gi1/0/1  -> Port 1
    #   Gi1/0/2  -> Port 2
    #   ...
    #   Gi1/0/48 -> Port 48
    #   Te1/1/1  -> Port 49
    #   Te1/1/2  -> Port 50
    #
    # При этом настоящие ifIndex и ifName сохраняются
    # отдельно в SQLite.
    # --------------------------------------------------------

    for port_number, (
        if_index,
        interface_name,
        detected_port
    ) in enumerate(
        physical_ports,
        start=1
    ):

        # ----------------------------------------------------
        # Device = Description / ifAlias
        # ----------------------------------------------------

        device = interface_aliases.get(
            if_index,
            ""
        ).strip()

        if not device:
            device = "-"

        # ----------------------------------------------------
        # Speed
        # ----------------------------------------------------

        speed = format_speed(
            interface_speeds.get(
                if_index,
                "0"
            )
        )

        # ----------------------------------------------------
        # Link
        # ----------------------------------------------------

        link = format_link(
            interface_status.get(
                if_index,
                "0"
            )
        )

        # ----------------------------------------------------
        # MAC
        # ----------------------------------------------------

        macs = mac_by_ifindex.get(
            if_index,
            []
        )

        if macs:

            mac = ", ".join(
                sorted(macs)
            )

        else:

            mac = "-"

        # ----------------------------------------------------
        # Result
        # ----------------------------------------------------

        result.append(
            {
                "Port": port_number,
                "Device": device,
                "Speed": speed,
                "Link": link,
                "MAC": mac,

                # Internal

                "_ifIndex": if_index,
                "_ifName": interface_name,
                "_vlan": vlans_by_ifindex.get(if_index),
                "_errors": errors_by_ifindex.get(if_index),
            }
        )

    # --------------------------------------------------------
    # Final sort
    # --------------------------------------------------------

    result.sort(
        key=lambda x: (
            x["Port"],
            x["_ifIndex"]
        )
    )

    return result
