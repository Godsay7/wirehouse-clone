"""VLAN lists as text: "1,10-12,20"."""

from typing import Iterable, List, Optional


def format_vlans(vlans: Iterable[int]) -> str:
    """[1, 10, 11, 12, 20] -> '1,10-12,20'."""

    ids = sorted(set(int(v) for v in vlans))
    parts = []
    start = previous = None
    for vlan in ids:
        if start is None:
            start = previous = vlan
        elif vlan == previous + 1:
            previous = vlan
        else:
            parts.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = vlan
    if start is not None:
        parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)


def parse_vlans(text: str) -> List[int]:
    """'1,10-12,20' -> [1, 10, 11, 12, 20] (bad parts are skipped)."""

    result = []
    for part in (text or "").split(","):
        part = part.strip()
        if "-" in part:
            low, _, high = part.partition("-")
            if low.isdigit() and high.isdigit() and int(low) <= int(high) <= 4095:
                result.extend(range(int(low), int(high) + 1))
        elif part.isdigit():
            result.append(int(part))
    return result


def vlan_summary(mode: Optional[str], vlan: Optional[int], tagged: str) -> str:
    """One line for history and tooltips: "140", "trunk 1 + 10-20", ""."""

    if mode == "trunk":
        native = str(vlan) if vlan else "—"
        return f"trunk {native}" + (f" + {tagged}" if tagged else "")
    if mode == "access":
        return str(vlan) if vlan else ""
    return ""
