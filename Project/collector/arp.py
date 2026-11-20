"""Current MAC -> IP neighbors from the L3 core switches."""

from typing import Dict, List

from ..core.text import now_iso
from ..dal.repositories.arp import ArpRepository
from .dns import resolve_dns_hostnames
from .snmp.client import snmp_walk_raw
from .snmp.oids import (
    OID_IP_NET_TO_MEDIA_PHYS_ADDRESS,
    OID_IP_NET_TO_PHYSICAL_PHYS_ADDRESS,
)
from .snmp.parsers import parse_ipnet_to_media, parse_ipnet_to_physical


def collect_core_arp(host: str, community: str) -> List[Dict]:
    """Collect current IPv4 MAC->IP neighbors directly from one L3 core."""

    print(f"Collecting ARP/neighbor table from core {host}...")

    lines = snmp_walk_raw(
        host,
        community,
        OID_IP_NET_TO_PHYSICAL_PHYS_ADDRESS
    )
    entries = parse_ipnet_to_physical(lines)

    if entries:
        print(f"  IP-MIB neighbors: {len(entries)}")
        return entries

    print("  IP-MIB returned no IPv4 neighbors; trying legacy MIB-II ARP...")

    lines = snmp_walk_raw(
        host,
        community,
        OID_IP_NET_TO_MEDIA_PHYS_ADDRESS
    )
    entries = parse_ipnet_to_media(lines)

    if entries:
        print(f"  MIB-II ARP entries: {len(entries)}")

    return entries


def save_core_arp_snapshot(connection, arp_sources: List[Dict]):
    """Replace arp_entries with the current Core ARP/neighbor snapshot.

    MAC and IP are authoritative from the current L3 Core snapshot. Reverse
    DNS is used only to populate hostname for those CURRENT IPs. The table is
    rebuilt after a successful Core poll, so hostnames from IPs that disappear
    from Core are removed instead of being kept as stale ARP/DNS history.
    """

    if not arp_sources:
        print("WARNING: ARP source is not configured and Core1 was not auto-detected.")
        return

    merged = {}
    successful_sources = 0

    for source in arp_sources:
        host = source["host"]
        name = source.get("name") or host
        source_community = source.get("community") or ""

        try:
            entries = collect_core_arp(host, source_community)
        except Exception as exc:
            print(f"WARNING: ARP collection failed on {name} ({host}): {exc}")
            continue

        if not entries:
            print(f"WARNING: No ARP entries returned by {name} ({host}).")
            continue

        successful_sources += 1
        for entry in entries:
            merged[(entry["mac"], entry["ip"])] = entry

    if not merged:
        print("WARNING: Core ARP snapshot is empty; existing arp_entries were preserved.")
        return

    # Resolve names only for IPs that are present in the CURRENT Core snapshot.
    # This keeps MAC/IP authoritative from Core while still showing a DNS name.
    dns_hostnames = resolve_dns_hostnames([entry["ip"] for entry in merged.values()])

    now = now_iso()
    repository = ArpRepository(connection)

    try:
        # Preserve first_seen for entries that are still present.
        existing_first_seen = repository.first_seen_by_key()

        # Core ARP is the authoritative CURRENT snapshot. This removes stale
        # IP/DNS-derived rows from older collector versions.
        repository.replace_all(
            {
                **merged[key],
                "hostname": dns_hostnames.get(merged[key]["ip"], "-"),
                "first_seen": existing_first_seen.get(key) or now,
                "last_seen": now,
            }
            for key in sorted(merged)
        )

        connection.commit()
        print(
            f"Core ARP snapshot saved: {len(merged)} entries "
            f"from {successful_sources} source(s). DNS hostnames refreshed."
        )
    except Exception:
        connection.rollback()
        raise
