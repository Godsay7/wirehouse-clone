"""Pure helpers for the cabling check: what the switches see vs what is documented."""

import re

from ...core.mac import split_macs


def short_interface_name(name):
    """'TenGigabitEthernet1/1/1' -> 'te1/1/1': compares port names across vendors."""

    name = str(name or "").strip().lower().replace(" ", "")
    for long, short in (
        ("twentyfivegige", "twe"), ("hundredgige", "hu"), ("fortygigabitethernet", "fo"),
        ("tengigabitethernet", "te"), ("gigabitethernet", "gi"), ("fastethernet", "fa"),
    ):
        if name.startswith(long):
            return short + name[len(long):]
    return name


def device_key(name):
    """'nh-sw73-all.newshouse.lan' -> 'nh-sw73-all' (no domain, lower case)."""

    name = str(name or "").strip().lower()
    if not name or name == "not advertised":
        return ""
    if not re.fullmatch(r"[\d.]+", name):
        name = name.split(".", 1)[0]
    return name


class SwitchDirectory:
    """Finds inventory switches by the name/port a neighbour advertises."""

    def __init__(self, switches, ports_by_switch):
        """switches: [{id, host, sys_name}]; ports_by_switch: {switch_id: {port: if_name}}."""

        self._by_key = {}
        for switch in switches:
            for name in (switch.get("sys_name"), switch.get("host")):
                key = device_key(name)
                if key and key != "-":
                    self._by_key.setdefault(key, set()).add(switch["id"])
        self._ports = {
            switch_id: {short_interface_name(if_name): port for port, if_name in ports.items() if if_name}
            for switch_id, ports in ports_by_switch.items()
        }

    def resolve(self, remote_name, remote_port, remote_port_desc=""):
        """(switch_id, port or None) of an inventory switch, or (None, None).

        One device can be several inventory switches (SW106/SW107 share an
        IP and sysName); the advertised port name picks the right one.
        """

        candidates = self._by_key.get(device_key(remote_name), set())
        if not candidates:
            return None, None

        for port_name in (remote_port, remote_port_desc):
            key = short_interface_name(port_name)
            if not key:
                continue
            for switch_id in sorted(candidates):
                port = self._ports.get(switch_id, {}).get(key)
                if port is not None:
                    return switch_id, port

        if len(candidates) == 1:
            return next(iter(candidates)), None
        return None, None


def switch_numbers(text):
    """'Sw107-core2-UPLINK' -> {107}; switch numbers named in a port description."""

    return {int(n) for n in re.findall(r"(?<![a-z0-9])sw[\s_-]?(\d{1,3})(?!\d)", str(text or "").lower())}


def host_number(host):
    match = re.search(r"sw(\d{1,3})(?!\d)", str(host or "").lower())
    return int(match.group(1)) if match else None


def port_macs(value):
    """'7c:c2:55:e2:d6:77, 7c:c2:55:e2:ec:28' -> ['7c:c2:55:e2:d6:77', ...]."""

    return [mac for mac in split_macs(value) if MAC_RE.fullmatch(mac)]


# A port with more MACs than this is an uplink or a small switch, not one device.
DEVICE_PORT_MAX_MACS = 4


def device_replaced(previous, current, max_macs=DEVICE_PORT_MAX_MACS):
    """Another device on a switch port: (old MACs, new MACs) or None.

    previous: the last MAC list seen on the port (ports.last_mac, kept while
    the port is down or empty); current: the MAC list of this poll.

    It is a replacement when none of the old MACs is on the port any more and
    other MACs are. Not a replacement: a device that went to sleep and came
    back; a second device next to the first one (they share a MAC).
    Randomized MACs (locally administered: phones and laptops on Wi-Fi access
    points, virtual interfaces) change all the time and are left out, so an
    access point with changing clients is still the same device. Ports with
    many MACs (uplinks) are not looked at."""

    old = [mac for mac in port_macs(previous) if not is_random_mac(mac)]
    new = [mac for mac in port_macs(current) if not is_random_mac(mac)]
    if not old or not new or len(old) > max_macs or len(new) > max_macs:
        return None
    if set(old) & set(new):
        return None
    return old, new


def is_random_mac(mac):
    """A locally administered MAC (second bit of the first byte): randomized
    by phones and laptops, or made up for a virtual interface."""

    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


MAC_RE = re.compile(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}")
# Cyrillic letters typed instead of the Latin ones that look the same.
_LOOKALIKE = str.maketrans("САВЕсаве", "CABEcabe")


def clean_mac(value):
    """A MAC typed by hand -> aa:bb:cc:dd:ee:ff, or '' if it isn't one."""

    text = str(value or "").translate(_LOOKALIKE).strip().lower()
    compact = re.sub(r"[^0-9a-f]", "", text)
    if len(compact) != 12 or re.search(r"[g-z]", text.replace("x", "")):
        return ""
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2))
