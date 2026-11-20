"""Reverse DNS for IPs from the current Core ARP snapshot."""

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List


def resolve_dns_hostname(ip: str, timeout: float = 2.5) -> str:
    """Resolve the current IP to a hostname through the system DNS/NSS resolver.

    The IP itself still comes only from the current Core ARP/neighbor table.
    A failed/timeout lookup returns '-' and never reuses an older hostname.
    """

    try:
        result = subprocess.run(
            ["getent", "hosts", ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "-"

    if result.returncode != 0:
        return "-"

    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue

        hostname = parts[1].strip().rstrip(".")
        if hostname and hostname != ip:
            return hostname

    return "-"


def resolve_dns_hostnames(ips: List[str]) -> Dict[str, str]:
    """Resolve a set of current IPs, caching each IP lookup once per run."""

    unique_ips = sorted({str(ip).strip() for ip in ips if str(ip).strip()})
    if not unique_ips:
        return {}

    # Limit concurrency so a large ARP table does not create hundreds of
    # simultaneous resolver processes, while still keeping collection fast.
    worker_count = min(16, max(1, len(unique_ips)))
    resolved = {}

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(resolve_dns_hostname, ip): ip
            for ip in unique_ips
        }

        for future in as_completed(futures):
            ip = futures[future]
            try:
                resolved[ip] = future.result() or "-"
            except Exception:
                resolved[ip] = "-"

    found = sum(1 for hostname in resolved.values() if hostname != "-")
    print(f"DNS hostnames resolved: {found}/{len(unique_ips)} current IPs.")
    return resolved
