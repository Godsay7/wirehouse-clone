"""Error counters of each port: ifInErrors, ifOutErrors and CRC (dot3StatsFCSErrors).

The counters only grow (until the switch reboots or a 32-bit counter
wraps), so a single value says little; the collector stores how much they
grew since the previous poll (see storage.save_switch_to_database), and the
web pages show ports whose errors are growing.
"""

from typing import Dict, Optional

from .snmp.client import snmp_walk_table
from .snmp.oids import OID_DOT3_FCS_ERRORS, OID_IF_IN_ERRORS, OID_IF_OUT_ERRORS

COUNTERS = (("in", OID_IF_IN_ERRORS), ("out", OID_IF_OUT_ERRORS), ("fcs", OID_DOT3_FCS_ERRORS))


def _int(value) -> Optional[int]:
    try:
        return int(str(value).split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def collect_error_counters(host: str, community: str) -> Dict[int, Dict[str, Optional[int]]]:
    """ifIndex -> {"in": n, "out": n, "fcs": n or None}; {} if nothing answers."""

    result: Dict[int, Dict[str, Optional[int]]] = {}
    for name, oid in COUNTERS:
        for index, value in snmp_walk_table(host, community, oid).items():
            result.setdefault(index[-1], {"in": None, "out": None, "fcs": None})[name] = _int(value)
    return result


def counter_growth(previous: Optional[int], current: Optional[int]) -> int:
    """How much a counter grew; 0 after a reset or wrap (the value went down)."""

    if previous is None or current is None or current < previous:
        return 0
    return current - previous
