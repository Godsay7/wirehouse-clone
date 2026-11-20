"""Vendor detection and physical front-panel layouts of switches."""

import re

from ...core.text import normalize_value


# Explicit vendor overrides for switches whose SNMP model string
# is absent, unusual, or not enough to identify the vendor.
MANUFACTURER_OVERRIDES = {
    "NH-SW100": ("CISCO", "cisco"),
    "NH-SW101": ("CISCO", "cisco"),
    "NH-SW77-POE": ("CISCO", "cisco"),
    "NH-SW91-TV": ("MIKROTIK", "mikrotik"),
}

# These two switches are Cisco Catalyst 4900M units with
# two expansion modules plus fixed Te1/1..Te1/8 ports.
# The chassis is physically 2U.
SPECIAL_CISCO_4900M_SWITCHES = {
    "NH-SW100",
    "NH-SW101",
}

MIKROTIK_MODEL_PREFIXES = (
    "CRS",
    "CSS",
    "CCR",
    "RB",
    "L009",
    "HAP",
    "HEX",
)

MIKROTIK_INTERFACE_PATTERNS = (
    r"^ether\d+$",
    r"^sfp\d+$",
    r"^sfp-sfpplus\d+$",
    r"^sfpplus\d+$",
    r"^sfp\d+-\d+$",
)


def is_mikrotik_switch(
    switch,
    ports
):
    """
    Detect MikroTik for physical port-panel orientation only.
    """

    switch_name = normalize_value(
        switch["host"]
    ).upper()

    # Explicit override requested for this switch.
    if switch_name == "NH-SW91-TV":
        return True

    model = normalize_value(
        switch["model"]
    ).upper()

    if model != "-" and model.startswith(
        MIKROTIK_MODEL_PREFIXES
    ):
        return True

    for port in ports:
        if_name = str(
            port.get("if_name") or ""
        ).strip()

        if any(
            re.match(
                pattern,
                if_name,
                re.IGNORECASE
            )
            for pattern in MIKROTIK_INTERFACE_PATTERNS
        ):
            return True

    return False


def detect_manufacturer(
    model,
    switch_name=None
):
    """Return (display_name, css_slug) for the dashboard badge."""

    normalized_name = str(
        switch_name or ""
    ).strip().upper()

    if normalized_name in MANUFACTURER_OVERRIDES:
        return MANUFACTURER_OVERRIDES[
            normalized_name
        ]

    value = str(model or "").strip()
    upper = value.upper()

    if not upper or upper == "-":
        return "UNKNOWN", "unknown"

    # MikroTik examples: CRS326-24G-2S+, CSS..., RB..., CCR...
    if (
        upper.startswith(MIKROTIK_MODEL_PREFIXES)
        or "MIKROTIK" in upper
    ):
        return "MIKROTIK", "mikrotik"

    # Dell / Dell EMC examples: N3048ET-ON, N3248TE-ON, S4148F-ON
    if (
        "DELL" in upper
        or "POWEREDGE" in upper
        or "POWERSWITCH" in upper
        or re.match(
            r"^[NSZ]\d{3,4}.*(?:-ON)?$",
            upper
        )
    ):
        return "DELL", "dell"

    # Cisco examples:
    # WS-C4948E, C9300-48T, C9300L-48P-4X, C9200..., CBS..., SG...
    if (
        "CISCO" in upper
        or upper.startswith("WS-")
        or re.match(
            r"^C\d{3,4}[A-Z]*(?:-|$)",
            upper
        )
        or upper.startswith(
            (
                "CBS",
                "SG",
                "IE-",
                "CAT",
            )
        )
    ):
        return "CISCO", "cisco"

    return "UNKNOWN", "unknown"


def _port_has_activity(port):
    """Return True when a logical interface is clearly in use."""

    if not port:
        return False

    if normalize_value(port.get("link")).upper() == "UP":
        return True

    if normalize_value(port.get("device")) != "-":
        return True

    if normalize_value(port.get("mac")) != "-":
        return True

    return False


def build_cisco_4900m_panel(ports):
    """
    Build the physical front-panel representation for Cisco 4900M.

    Expansion module mapping:
        Te2/1 <-> Gi2/9 + Gi2/10
        Te2/2 <-> Gi2/11 + Gi2/12
        ...
        Te2/8 <-> Gi2/23 + Gi2/24

    Module 3 follows the same mapping.

    Te1/1..Te1/8 are the fixed chassis 10G ports.
    """

    by_if_name = {}

    for port in ports:
        if_name = str(
            port.get("if_name") or ""
        ).strip()

        if if_name:
            by_if_name[if_name.lower()] = port

    modules = []

    for module_number in (2, 3):
        slots = []

        for slot_number in range(1, 9):
            te_name = f"Te{module_number}/{slot_number}"
            te_port = by_if_name.get(te_name.lower())

            gi_first_number = 9 + ((slot_number - 1) * 2)
            gi_names = [
                f"Gi{module_number}/{gi_first_number}",
                f"Gi{module_number}/{gi_first_number + 1}",
            ]

            gi_ports = [
                by_if_name[name.lower()]
                for name in gi_names
                if name.lower() in by_if_name
            ]

            gi_active = any(
                _port_has_activity(port)
                for port in gi_ports
            )

            te_active = _port_has_activity(te_port)

            # Prefer the interface family that is actually active.
            # If both sides are down/empty, show the Te interface by
            # default and keep the Gi alternatives in the small label.
            if gi_active and not te_active:
                mode = "gigabit"
                display_ports = gi_ports
            elif te_port is not None:
                mode = "ten_gigabit"
                display_ports = [te_port]
            elif gi_ports:
                mode = "gigabit"
                display_ports = gi_ports
            else:
                mode = "empty"
                display_ports = []

            slots.append(
                {
                    "slot": slot_number,
                    "mode": mode,
                    "te_port": te_port,
                    "gi_ports": gi_ports,
                    "display_ports": display_ports,
                }
            )

        modules.append(
            {
                "module": module_number,
                "slots": slots,
            }
        )

    fixed_ports = []

    for port_number in range(1, 9):
        if_name = f"Te1/{port_number}"
        port = by_if_name.get(if_name.lower())

        if port is not None:
            fixed_ports.append(port)

    return {
        "modules": modules,
        "fixed_ports": fixed_ports,
    }


def get_port_panel_layout(
    switch,
    ports
):
    """
    standard:
      odd ports on top, even ports on bottom.

    mikrotik:
      even ports on top, odd ports on bottom.

    cisco_4900m:
      NH-SW100 and NH-SW101 use a physical Catalyst 4900M layout.
    """

    switch_name = normalize_value(
        switch["host"]
    ).upper()

    if switch_name in SPECIAL_CISCO_4900M_SWITCHES:
        return "cisco_4900m"

    if is_mikrotik_switch(
        switch,
        ports
    ):
        return "mikrotik"

    return "standard"


def get_switch_rack_height(switch_name):
    """Return the physical rack height for switches with a known chassis size."""

    normalized_name = normalize_value(switch_name).upper()
    return 2 if normalized_name in SPECIAL_CISCO_4900M_SWITCHES else 1


# ------------------------------------------------------------
# Optical (SFP / SFP+ / uplink module) ports on the front panel
# ------------------------------------------------------------

# Models whose optical ports cannot be told from the interface names:
# model prefix -> range of port numbers that are SFP slots.
OPTICAL_PORTS_BY_MODEL = (
    ("WS-C3750G-24TS", range(25, 29)),       # 24 copper + 4 SFP, all GigabitEthernet1/0/x
    ("N3248TE", range(49, 53)),               # 48 copper + 4 SFP28, all ethernet1/1/x
)

OPTICAL_NAME = re.compile(r"^(te|tengigabitethernet|twe|twentyfivegige|fo|fortygigabitethernet|hu|sfp)", re.I)


def _family(if_name):
    """('Gi', '1/0') for Gi1/0/12; ('ether', '') for ether5."""

    match = re.match(r"^([A-Za-z-]+?)(\d+(?:/\d+)*?)(?:/)?(\d+)$", if_name or "")
    if not match:
        return (if_name or "", "")
    return (match.group(1), match.group(2) if "/" in (if_name or "") else "")


def optical_port_labels(switch, ports):
    """port number -> its own label on the front panel ("Te1", "Gi2", "SFP3")
    for optical ports; empty when the switch has no copper ports to set them
    apart from (all-SFP switches) or uses its own layout (Cisco 4900M)."""

    if normalize_value(switch.get("host")).upper() in SPECIAL_CISCO_4900M_SWITCHES:
        return {}

    ports = sorted((p for p in ports if p.get("if_name")), key=lambda p: int(p["port"]))
    model = normalize_value(switch.get("model")).upper()
    optical = []

    by_model = next((numbers for prefix, numbers in OPTICAL_PORTS_BY_MODEL if model.startswith(prefix)), None)
    families = {}
    for port in ports:
        families.setdefault(_family(port["if_name"]), []).append(port)
    main_family = max(families, key=lambda key: len(families[key])) if families else None

    for port in ports:
        name = port["if_name"]
        if OPTICAL_NAME.match(name):
            optical.append(port)
        elif by_model is not None and int(port["port"]) in by_model:
            optical.append(port)
        elif (main_family and _family(name) != main_family and len(families[_family(name)]) <= 8
              and not OPTICAL_NAME.match(families[main_family][0]["if_name"])):
            # An uplink module next to the copper block: Gi1/1/x after Gi1/0/x,
            # Gi1/x after Gi0/x, Gi1/0/x next to Fa1/0/x.
            optical.append(port)

    if not optical or len(optical) == len(ports):
        return {}

    labels, counters = {}, {}
    for port in optical:
        name = port["if_name"]
        if name.lower().startswith("sfp") or (by_model is not None and int(port["port"]) in by_model and not name[:2].isalpha()):
            prefix = "SFP"
        elif re.match(r"^(te|tengig)", name, re.I):
            prefix = "Te"
        elif re.match(r"^(twe|twentyfive)", name, re.I):
            prefix = "25G"
        elif re.match(r"^(fo|forty)", name, re.I):
            prefix = "40G"
        elif re.match(r"^hu", name, re.I):
            prefix = "100G"
        elif re.match(r"^gi", name, re.I):
            prefix = "Gi"
        else:
            prefix = "SFP"
        counters[prefix] = counters.get(prefix, 0) + 1
        labels[int(port["port"])] = f"{prefix}{counters[prefix]}"
    return labels
