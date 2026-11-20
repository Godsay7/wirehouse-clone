"""Switch system name and model."""

from typing import Tuple

from .snmp.client import snmp_get_value, snmp_walk
from .snmp.oids import (
    OID_ENT_PHYSICAL_MODEL,
    OID_MIKROTIK_BOARD_NAME,
    OID_SYS_NAME,
)


def collect_switch_identity(
    host: str,
    community: str
) -> Tuple[str, str]:
    """
    Returns:

        (sys_name, model)

    Model order:
      1. ENTITY-MIB entPhysicalModelName
      2. MikroTik board-name fallback
    """

    print("Collecting switch system name and model...")

    sys_name = snmp_get_value(
        host,
        community,
        OID_SYS_NAME
    )

    if not sys_name:
        sys_name = "-"

    model = ""

    # ENTITY-MIB can contain chassis, PSUs, SFPs, fans, etc.
    # Keep a chassis-like value and ignore obvious accessories.
    try:
        models = snmp_walk(
            host,
            community,
            OID_ENT_PHYSICAL_MODEL
        )
    except Exception:
        models = {}

    ignored_patterns = (
        "sfp",
        "qsfp",
        "pwr-",
        "power supply",
        "powersupply",
        "fan",
        "transceiver",
    )

    candidates = []

    for raw_value in models.values():
        value = str(raw_value).strip()

        if not value:
            continue

        lower_value = value.lower()

        if any(
            pattern in lower_value
            for pattern in ignored_patterns
        ):
            continue

        if value not in candidates:
            candidates.append(value)

    if candidates:
        model = candidates[0]

    # RouterOS ENTITY-MIB commonly leaves model name empty.
    if not model:
        model = snmp_get_value(
            host,
            community,
            OID_MIKROTIK_BOARD_NAME
        )

    if not model:
        model = "-"

    print(f"System Name: {sys_name}")
    print(f"Model: {model}")

    return sys_name, model
