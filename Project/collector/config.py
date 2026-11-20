"""YAML configuration of the collector."""

import os
import sys
from typing import Dict, List, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML не установлен.")
    print("Установи: pip3 install pyyaml")
    sys.exit(1)


def load_config(
    config_path: str
) -> Tuple[str, List[Dict], List[Dict]]:
    """
    Возвращает (community, switches, arp_sources), где switches -
    список словарей:

        {
            "host": "10.13.40.107",
            "name": "SW106",
            "interface_prefix": ["Gi1/", "Te1/"],
        }

    host             - IP/hostname для SNMP-запросов.
    name             - уникальный идентификатор свича
                        для базы данных и веб-интерфейса.
                        Если не задан в YAML - берётся
                        равным host.
    interface_prefix - список префиксов интерфейсов,
                        которые нужно собирать с этого
                        host. Если не задан - собираются
                        все физические порты.

    Один и тот же host может встречаться несколько раз
    с разными name/interface_prefix - это позволяет
    разделить один физический свич на несколько логических
    (например, свич с двумя независимыми группами портов).
    """

    if not os.path.exists(
        config_path
    ):

        raise RuntimeError(
            f"Config file не найден: "
            f"{config_path}"
        )

    try:

        with open(
            config_path,
            "r",
            encoding="utf-8"
        ) as file:

            config = yaml.safe_load(
                file
            )

    except yaml.YAMLError as exc:

        raise RuntimeError(
            f"Ошибка YAML: {exc}"
        )

    if not isinstance(
        config,
        dict
    ):

        raise RuntimeError(
            "Ошибка YAML: корневой "
            "элемент должен быть объектом."
        )

    # --------------------------------------------------------
    # SNMP
    # --------------------------------------------------------

    snmp_config = config.get(
        "snmp"
    )

    if not isinstance(
        snmp_config,
        dict
    ):

        raise RuntimeError(
            "В YAML отсутствует секция 'snmp'."
        )

    version = str(
        snmp_config.get(
            "version",
            "2c"
        )
    )

    if version != "2c":

        raise RuntimeError(
            "Поддерживается только "
            "SNMP v2c."
        )

    community = snmp_config.get(
        "community"
    )

    if not community:

        raise RuntimeError(
            "В YAML не указан "
            "snmp.community"
        )

    community = str(
        community
    )

    # --------------------------------------------------------
    # Switches
    # --------------------------------------------------------

    switches_config = config.get(
        "switches"
    )

    if not isinstance(
        switches_config,
        list
    ):

        raise RuntimeError(
            "В YAML отсутствует "
            "список 'switches'."
        )

    switches = []
    seen_keys = set()

    for item in switches_config:

        if not isinstance(
            item,
            dict
        ):
            continue

        host = item.get(
            "host"
        )

        if not host:
            continue

        host = str(
            host
        ).strip()

        if not host:
            continue

        # ----------------------------------------------------
        # name
        #
        # Уникальный идентификатор свича. Если не задан -
        # берётся равным host.
        # ----------------------------------------------------

        name = item.get(
            "name"
        )

        if name:
            name = str(
                name
            ).strip()

        if not name:
            name = host

        # ----------------------------------------------------
        # interface_prefix
        # ----------------------------------------------------

        interface_prefix = item.get(
            "interface_prefix"
        )

        if interface_prefix is not None:

            if isinstance(
                interface_prefix,
                str
            ):

                interface_prefix = [
                    interface_prefix
                ]

            elif isinstance(
                interface_prefix,
                list
            ):

                interface_prefix = [
                    str(prefix)
                    for prefix in interface_prefix
                    if prefix
                ]

            else:

                interface_prefix = None

        # ----------------------------------------------------
        # Дедуп по (host, name).
        #
        # Один и тот же host + name, указанный дважды в
        # YAML по ошибке, будет учтён только один раз.
        #
        # При этом host, повторённый с разными name
        # (разделение одного физического свича на
        # несколько логических), сохраняется как есть.
        # ----------------------------------------------------

        key = (
            host,
            name
        )

        if key in seen_keys:
            continue

        seen_keys.add(
            key
        )

        switches.append(
            {
                "host": host,
                "name": name,
                "interface_prefix": interface_prefix,
            }
        )

    if not switches:

        raise RuntimeError(
            "В YAML не найдено "
            "ни одного host."
        )

    # --------------------------------------------------------
    # ARP sources
    #
    # Optional explicit configuration:
    #
    # arp_sources:
    #   - host: "10.13.40.241"
    #     name: "NH-SW3-Core1"
    #   - host: "10.13.40.242"
    #     name: "NH-SW4-Core1"
    #
    # If the section is absent, Core1 switches are auto-detected
    # from the normal switch list. This keeps older YAML files
    # working without modification.
    # --------------------------------------------------------

    raw_arp_sources = config.get("arp_sources")
    arp_sources = []

    if isinstance(raw_arp_sources, list):
        for item in raw_arp_sources:
            if not isinstance(item, dict):
                continue

            source_host = str(item.get("host") or "").strip()
            if not source_host:
                continue

            source_name = str(item.get("name") or source_host).strip() or source_host
            source_community = str(item.get("community") or community).strip() or community

            arp_sources.append({
                "host": source_host,
                "name": source_name,
                "community": source_community,
            })

    if not arp_sources:
        seen_arp_hosts = set()
        for switch in switches:
            switch_name = str(switch.get("name") or "")
            source_host = str(switch.get("host") or "")

            # In this project the L3 core pair is named *-Core1.
            # Core2/Core3 devices are not selected automatically.
            if "core1" not in switch_name.lower():
                continue
            if not source_host or source_host in seen_arp_hosts:
                continue

            seen_arp_hosts.add(source_host)
            arp_sources.append({
                "host": source_host,
                "name": switch_name or source_host,
                "community": community,
            })

    return community, switches, arp_sources
