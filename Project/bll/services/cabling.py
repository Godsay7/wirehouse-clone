"""Cables between rack ports and port descriptions."""

from ...core.text import now_iso
from ..domain.cable_path import (
    DEVICE_TYPES,
    CableGraph,
    END_DEVICE,
    ranges_overlap,
)
from ..domain.cabling import normalize_patch_type
from ..errors import NotFoundError, ReplaceRequired, ValidationError
from .rack_view import resolve_cable_type_from_db

ENDPOINT_TYPES = ("switch", "patch", "server", "placeholder")


def parse_connection_ref(connection_ref):
    """'sp-12' / '12' -> ('port', 12); 'pp-3' -> ('patch', 3)."""

    raw_ref = str(connection_ref or "").strip().lower()
    table = "port"
    raw_id = raw_ref

    if raw_ref.startswith("sp-"):
        raw_id = raw_ref[3:]
    elif raw_ref.startswith("pp-"):
        raw_id = raw_ref[3:]
        table = "patch"

    try:
        return table, int(raw_id)
    except ValueError:
        raise ValidationError("Invalid connection id")


class CablingService:

    def __init__(self, database):
        self.database = database

    def connect(self, endpoint_a, endpoint_b, replace=False):
        """Cable two ports; endpoints are (type, id, port). Returns the new id.

        A port takes one cable. If either port already has one, nothing is
        changed and ReplaceRequired says which cables are in the way, unless
        ``replace`` is true: then they are removed first. The same cable
        again is a no-op.
        """

        endpoint_a, endpoint_b = tuple(endpoint_a), tuple(endpoint_b)
        t1, id1, _ = endpoint_a
        t2, id2, _ = endpoint_b

        with self.database.write(touch="rack") as uow:
            cable_type, media_error = resolve_cable_type_from_db(uow, t1, id1, t2, id2)

            if media_error:
                raise ValidationError(media_error)

            for endpoint_type, endpoint_id, port in (endpoint_a, endpoint_b):
                if endpoint_type == "placeholder":
                    placeholder = uow.equipment.get_placeholder(endpoint_id)
                    if not 1 <= port <= int(placeholder["port_count"] or 0):
                        raise ValidationError(f"{placeholder['name']} has no port {port}")

            existing = {}
            for endpoint in (endpoint_a, endpoint_b):
                for peer, link in uow.connections.cords_at(endpoint):
                    if (link.get("connection_ref") or "").startswith("sp-"):
                        existing[link["connection_ref"]] = (endpoint, peer)

            for ref, (endpoint, peer) in existing.items():
                if {endpoint, peer} == {endpoint_a, endpoint_b}:
                    return int(ref[3:])          # already cabled exactly like this

            if existing and not replace:
                conflicts = [
                    f"{_port_name(uow, endpoint)} is connected to {_port_name(uow, peer)}"
                    for endpoint, peer in existing.values()
                ]
                raise ReplaceRequired(
                    "The port already has a cable: " + "; ".join(conflicts) + ". Replace it?",
                    conflicts,
                )

            uow.connections.delete_touching_ports(endpoint_a, endpoint_b)
            return uow.connections.create(endpoint_a, endpoint_b, cable_type, now_iso())

    def disconnect(self, connection_ref):
        table, connection_id = parse_connection_ref(connection_ref)

        with self.database.write(touch="rack") as uow:
            if table == "patch":
                uow.connections.delete_patch_connection(connection_id)
            else:
                uow.connections.delete_port_connection(connection_id)

    def set_port_description(self, endpoint_type, endpoint_id, port, description):
        """Free-text note on a switch/patch port; for servers it is the port label."""

        with self.database.write(touch="rack") as uow:
            if endpoint_type == "switch":
                uow.switches.set_port_description(endpoint_id, port, description)
            elif endpoint_type == "patch":
                uow.equipment.set_patch_port_description(endpoint_id, port, description)
            elif endpoint_type == "server":
                uow.equipment.set_server_port_label(endpoint_id, port, description)
            elif endpoint_type == "placeholder":
                uow.equipment.set_placeholder_port_description(endpoint_id, port, description)

    # --------------------------------------------------------
    # Trunk cables between ODF panels
    # --------------------------------------------------------

    def add_trunk(self, panel_a_id, port_a_start, panel_b_id, port_b_start, port_count, name=""):
        """Splice ports port_a_start.. of panel A to port_b_start.. of panel B."""

        try:
            panel_a_id, port_a_start, panel_b_id, port_b_start, port_count = (
                int(value) for value in (panel_a_id, port_a_start, panel_b_id, port_b_start, port_count)
            )
        except (TypeError, ValueError):
            raise ValidationError("Panels, ports and fibre count must be numbers")
        name = " ".join(str(name or "").split())[:80]

        with self.database.write(touch="rack") as uow:
            panels = {panel["id"]: panel for panel in uow.trunks.odf_panels()}
            for panel_id in (panel_a_id, panel_b_id):
                if panel_id not in panels:
                    raise ValidationError("Both ends of a trunk must be ODF panels")
            if port_count < 1:
                raise ValidationError("A trunk needs at least one fibre")
            for panel_id, start in ((panel_a_id, port_a_start), (panel_b_id, port_b_start)):
                panel = panels[panel_id]
                if start < 1 or start + port_count - 1 > int(panel["port_count"]):
                    raise ValidationError(
                        f"{panel['name']} has ports 1-{panel['port_count']}; "
                        f"{start}-{start + port_count - 1} does not fit"
                    )
            if panel_a_id == panel_b_id and ranges_overlap(port_a_start, port_b_start, port_count, port_count):
                raise ValidationError("A trunk cannot connect a port range to itself")

            for trunk in uow.trunks.list_for_panels([panel_a_id, panel_b_id]):
                for side in ("a", "b"):
                    used_panel, used_start = trunk[f"panel_{side}_id"], trunk[f"port_{side}_start"]
                    for panel_id, start in ((panel_a_id, port_a_start), (panel_b_id, port_b_start)):
                        if used_panel == panel_id and ranges_overlap(start, used_start, port_count, trunk["port_count"]):
                            raise ValidationError(
                                f"Ports {start}-{start + port_count - 1} of {panels[panel_id]['name']} "
                                "already belong to another trunk"
                            )

            return uow.trunks.create(panel_a_id, port_a_start, panel_b_id, port_b_start, port_count, name, now_iso())

    def delete_trunk(self, trunk_id):
        with self.database.write(touch="rack") as uow:
            if uow.trunks.get(trunk_id) is None:
                raise NotFoundError("Trunk not found")
            uow.trunks.delete(trunk_id)

    def trace_path(self, endpoint):
        """Full path of the cable through one port (patch cords + ODF trunks).

        Two ODFs with the same name in different server rooms are joined by a
        trunk cable, port N to port N.
        """

        endpoint = tuple(endpoint)

        with self.database.read() as uow:
            if uow.equipment.endpoint_details(*endpoint) is None:
                raise NotFoundError("Port not found")

            graph = load_cable_graph(uow)
            path = graph.trace(endpoint)

            endpoints = []
            for endpoint_type, endpoint_id, port in path["endpoints"]:
                details = uow.equipment.endpoint_details(endpoint_type, endpoint_id, port) or {}
                endpoints.append(_describe(endpoint_type, endpoint_id, port, details))

        links = []
        for index, link in enumerate(path["links"]):
            a, b = endpoints[index], endpoints[index + 1]
            fiber = "odf" in {a.get("patch_type"), b.get("patch_type")}
            links.append({
                "kind": link["kind"],
                "cable_type": "fiber" if fiber or link["kind"] == "trunk" else "ethernet",
                "connection_ref": link.get("connection_ref"),
                "cable_label": link.get("cable_label"),
                "trunk_name": link.get("trunk_name"),
                "from_room": a["room"],
                "to_room": b["room"],
            })

        ends = path["ends"]
        complete = all(
            reason == END_DEVICE and endpoint["type"] in DEVICE_TYPES
            for reason, endpoint in zip(ends, (endpoints[0], endpoints[-1]))
        )

        return {
            "start": {"type": endpoint[0], "id": endpoint[1], "port": endpoint[2]},
            "endpoints": endpoints,
            "links": links,
            "ends": ends,
            "complete": complete,
        }


def _port_name(uow, endpoint):
    details = _describe(*endpoint, uow.equipment.endpoint_details(*endpoint) or {})
    return f"{details['name']} {details['port_label']}"


def load_cable_graph(uow):
    """Every cord, ODF panel and trunk of the site, for tracing many ports."""

    return CableGraph(
        uow.connections.list_port_connections(),
        uow.connections.list_patch_connections(),
        uow.equipment.odf_panels(),
        uow.trunks.list_all(),
    )


def _describe(endpoint_type, endpoint_id, port, details):
    if endpoint_type in ("server", "switch") and port == 0:
        port_label = "mng"
    else:
        port_label = details.get("port_name") or f"Port {port}"

    patch_type = normalize_patch_type(details.get("patch_type")) if endpoint_type == "patch" else None

    return {
        "type": endpoint_type,
        "id": endpoint_id,
        "port": port,
        "element_id": f"{endpoint_type}-{endpoint_id}-port-{port}",
        "name": details.get("name") or f"{endpoint_type.capitalize()} {endpoint_id}",
        "port_label": port_label,
        "patch_type": patch_type,
        "description": details.get("description") or "",
        "room": details.get("room") or "",
        "rack": details.get("rack") or "",
        "side": (details.get("side") or "").capitalize(),
    }
