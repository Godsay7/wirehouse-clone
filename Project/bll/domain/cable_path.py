"""Trace the full cable path of one port through patch cords and ODF trunks.

A port has at most two sides:

* the patch cord plugged into it (a row in port_connections / patch_connections);
* for an ODF port only, the trunk cable to the ODF with the same name in
  another server room: port N of one panel is spliced to port N of the other.

The path alternates cord, trunk, cord, ... and stops at a switch/server
port or where the next piece is missing. Pure logic: the caller passes
functions that look the neighbours up in the database.
"""

DEVICE_TYPES = {"switch", "server", "placeholder"}

# Why one end of a path stops.
END_DEVICE = "device"            # switch or server port: a normal end
END_NOT_PATCHED = "not_patched"  # patch-panel port without a patch cord
END_NO_TRUNK = "no_trunk"        # ODF without a same-named ODF in another room
END_PATCH_PANEL = "patch_panel"  # copper/SDI panel: its rear cabling is not stored
END_AMBIGUOUS = "ambiguous"      # several cords or several same-named ODFs
END_LOOP = "loop"                # path came back to a port already on it
END_TOO_LONG = "too_long"

MAX_HOPS = 64


def trunk_key(name):
    """ODF names that differ only in case or spacing describe the same trunk."""

    return " ".join(str(name or "").split()).casefold()


def _walk(start, first_step, cord_peers, trunk_peers, visited):
    """Follow the path from ``start`` beginning with ``first_step``.

    Returns (hops, end_reason) where hops is a list of (link, endpoint).
    """

    hops = []
    current = start
    step = first_step

    for _ in range(MAX_HOPS):
        if step == "cord":
            peers = cord_peers(current)
            if not peers:
                return hops, END_DEVICE if current[0] in DEVICE_TYPES else END_NOT_PATCHED
        else:
            peers = trunk_peers(current)
            if peers is None:
                return hops, END_DEVICE if current[0] in DEVICE_TYPES else END_PATCH_PANEL
            if not peers:
                return hops, END_NO_TRUNK

        if len(peers) > 1:
            return hops, END_AMBIGUOUS

        endpoint, link = peers[0]

        if endpoint in visited:
            return hops, END_LOOP

        visited.add(endpoint)
        hops.append((dict(link, kind=step), endpoint))
        current = endpoint
        step = "trunk" if step == "cord" else "cord"

    return hops, END_TOO_LONG


def trace_cable_path(start, cord_peers, trunk_peers):
    """Full path through ``start``, an endpoint tuple (type, id, port).

    cord_peers(endpoint)  -> [(endpoint, link_info), ...]
    trunk_peers(endpoint) -> None when the port has no trunk side (not an ODF),
                             else [(endpoint, link_info), ...]

    Returns {"endpoints": [...], "links": [...], "ends": [reason_first, reason_last]}
    with len(links) == len(endpoints) - 1. The path starts from the
    switch/server end; with devices on both ends, from the clicked one.
    """

    visited = {start}
    forward, forward_end = _walk(start, "cord", cord_peers, trunk_peers, visited)
    backward, backward_end = _walk(start, "trunk", cord_peers, trunk_peers, visited)

    endpoints = [endpoint for _, endpoint in reversed(backward)] + [start]
    links = [link for link, _ in reversed(backward)]

    for link, endpoint in forward:
        links.append(link)
        endpoints.append(endpoint)

    ends = [backward_end, forward_end]

    first_is_device = endpoints[0][0] in DEVICE_TYPES and ends[0] == END_DEVICE
    last_is_device = endpoints[-1][0] in DEVICE_TYPES and ends[1] == END_DEVICE

    # Start from the device end; if both ends are devices, from the clicked one.
    if (last_is_device and not first_is_device) or (first_is_device and last_is_device and endpoints[-1] == start):
        endpoints.reverse()
        links.reverse()
        ends.reverse()

    return {"endpoints": endpoints, "links": links, "ends": ends}


# ------------------------------------------------------------
# Trunk cables: explicit port ranges between two ODF panels
# ------------------------------------------------------------

def trunk_peer(trunk, panel_id, port):
    """(other panel id, other port) if this trunk carries panel_id/port, else None."""

    for here, start, there, there_start in (
        ("panel_a_id", "port_a_start", "panel_b_id", "port_b_start"),
        ("panel_b_id", "port_b_start", "panel_a_id", "port_a_start"),
    ):
        if trunk[here] == panel_id and trunk[start] <= port < trunk[start] + trunk["port_count"]:
            return trunk[there], trunk[there_start] + (port - trunk[start])
    return None


def ranges_overlap(start_a, start_b, count_a, count_b):
    return start_a < start_b + count_b and start_b < start_a + count_a


# ------------------------------------------------------------
# All cabling in memory: trace many ports without a query per hop
# ------------------------------------------------------------

class CableGraph:
    """Patch cords, ODF panels and trunk cables loaded once.

    cord_peers / trunk_peers have the signatures trace_cable_path expects.
    """

    def __init__(self, port_connections, patch_connections, odf_panels, trunks):
        self._cords = {}
        for row in port_connections:
            a = (row["endpoint_a_type"], row["endpoint_a_id"], row["endpoint_a_port"])
            b = (row["endpoint_b_type"], row["endpoint_b_id"], row["endpoint_b_port"])
            info = {"connection_ref": f"sp-{row['id']}", "cable_label": row.get("cable_label")}
            self._cords.setdefault(a, []).append((b, info))
            self._cords.setdefault(b, []).append((a, info))
        for row in patch_connections:
            a = ("patch", row["patch_panel_a_id"], row["patch_port_a"])
            b = ("patch", row["patch_panel_b_id"], row["patch_port_b"])
            info = {"connection_ref": f"pp-{row['id']}", "cable_label": row.get("cable_label")}
            self._cords.setdefault(a, []).append((b, info))
            self._cords.setdefault(b, []).append((a, info))

        self._odf = {panel["id"]: panel for panel in odf_panels}
        self._odf_by_key = {}
        for panel in self._odf.values():
            self._odf_by_key.setdefault(trunk_key(panel["name"]), []).append(panel)
        self._trunks = {}
        for trunk in trunks:
            self._trunks.setdefault(trunk["panel_a_id"], []).append(trunk)
            self._trunks.setdefault(trunk["panel_b_id"], []).append(trunk)

    def cord_peers(self, endpoint):
        return list(self._cords.get(tuple(endpoint), ()))

    def has_cord(self, endpoint):
        return tuple(endpoint) in self._cords

    def trunk_peers(self, endpoint):
        endpoint_type, panel_id, port = endpoint
        panel = self._odf.get(panel_id) if endpoint_type == "patch" else None
        if panel is None:
            return None

        # Trunk cables entered explicitly win; a panel that has any does
        # not use the same-name rule.
        if panel_id in self._trunks:
            peers = []
            for trunk in self._trunks[panel_id]:
                peer = trunk_peer(trunk, panel_id, port)
                if peer and peer[0] in self._odf:
                    peers.append((("patch", peer[0], peer[1]), {"trunk_name": trunk["name"] or self._odf[peer[0]]["name"]}))
            return peers

        return [
            (("patch", other["id"], port), {"trunk_name": other["name"]})
            for other in self._odf_by_key[trunk_key(panel["name"])]
            if other["server_room_id"] != panel["server_room_id"]
            and port <= int(other["port_count"] or 0)
        ]

    def trace(self, endpoint):
        return trace_cable_path(tuple(endpoint), self.cord_peers, self.trunk_peers)

    def far_end(self, endpoint):
        """(far endpoint, end reason, hops) of the cable through ``endpoint``, or None if no cable."""

        endpoint = tuple(endpoint)
        if not self.has_cord(endpoint):
            return None
        path = self.trace(endpoint)
        points = path["endpoints"]
        if points[0] == endpoint:
            return points[-1], path["ends"][1], len(points) - 1
        return points[0], path["ends"][0], len(points) - 1
