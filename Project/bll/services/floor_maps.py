"""Floor Maps: schematic plans with rooms and workplaces (PC role, name, IP)."""

import re

from ...core.text import now_iso
from ..domain.floor_maps import (
    DEFAULT_MAP_HEIGHT,
    DEFAULT_MAP_WIDTH,
    clean_device_type,
    clean_ip,
    clean_map_name,
    clean_map_size,
    clean_note,
    clean_point,
    clean_room_points,
    clean_room_type,
    clean_text,
)
from ..domain.ports import locate_ips, locate_macs
from ..domain.floor_maps import clean_socket, socket_key, sockets_of_patch_port
from .cabling import load_cable_graph
from ..errors import NotFoundError, ValidationError

TOUCH = "maps"


class FloorMapService:

    def __init__(self, database):
        self.database = database

    # --------------------------------------------------------
    # Read
    # --------------------------------------------------------

    def list_maps(self):
        with self.database.read() as uow:
            return uow.floor_maps.list_maps()

    def map_data(self, map_id):
        """Map with its rooms and workplaces, plus every role used so far.

        Each workplace with an IP gets ``network``: the switch port where that
        IP is seen now (see domain.ports.locate_ips).
        """

        with self.database.read() as uow:
            floor_map = uow.floor_maps.get_map(map_id)
            if floor_map is None:
                raise NotFoundError("Map not found")

            workplaces = uow.floor_maps.list_workplaces(map_id)
            self._add_network(uow, workplaces)
            self._add_socket_cabling(uow, workplaces)

            return {
                "map": floor_map,
                "rooms": uow.floor_maps.list_rooms(map_id),
                "workplaces": workplaces,
                "roles": uow.floor_maps.list_roles(),
            }

    # --------------------------------------------------------
    # Maps
    # --------------------------------------------------------

    def create_map(self, name):
        name = clean_map_name(name)

        with self.database.write(touch=TOUCH) as uow:
            if uow.floor_maps.map_name_taken(name):
                raise ValidationError(f"Map '{name}' already exists")
            return uow.floor_maps.create_map(name, DEFAULT_MAP_WIDTH, DEFAULT_MAP_HEIGHT, now_iso())

    def update_map(self, map_id, values):
        with self.database.write(touch=TOUCH) as uow:
            floor_map = self._map(uow, map_id)

            name = clean_map_name(values.get("name", floor_map["name"]))
            width = clean_map_size(values.get("width"), floor_map["width"])
            height = clean_map_size(values.get("height"), floor_map["height"])

            if uow.floor_maps.map_name_taken(name, except_id=map_id):
                raise ValidationError(f"Map '{name}' already exists")

            if width < floor_map["width"] or height < floor_map["height"]:
                self._check_fits(uow, map_id, width, height)

            uow.floor_maps.update_map(map_id, name, width, height, now_iso())

    def reorder_maps(self, map_ids):
        """Save the tab order; map_ids must list every map exactly once."""

        if not isinstance(map_ids, list):
            raise ValidationError("map_ids must be a list")
        try:
            map_ids = [int(map_id) for map_id in map_ids]
        except (TypeError, ValueError):
            raise ValidationError("Invalid map id")

        with self.database.write(touch=TOUCH) as uow:
            existing = [floor_map["id"] for floor_map in uow.floor_maps.list_maps()]
            if sorted(map_ids) != sorted(existing):
                raise ValidationError("The list of maps has changed; reload the page and try again")
            uow.floor_maps.set_map_positions(map_ids)

    def delete_map(self, map_id):
        with self.database.write(touch=TOUCH) as uow:
            self._map(uow, map_id)
            uow.floor_maps.delete_map(map_id)

    # --------------------------------------------------------
    # Rooms
    # --------------------------------------------------------

    def create_room(self, map_id, values):
        with self.database.write(touch=TOUCH) as uow:
            floor_map = self._map(uow, map_id)
            points = clean_room_points(values.get("points"), floor_map["width"], floor_map["height"])
            name = clean_text(values.get("name"), field="Room name")
            room_type = clean_room_type(values.get("room_type"))
            return uow.floor_maps.create_room(map_id, room_type, name, points, now_iso())

    def update_room(self, room_id, values):
        with self.database.write(touch=TOUCH) as uow:
            room = self._room(uow, room_id)
            floor_map = self._map(uow, room["map_id"])

            name = clean_text(values.get("name", room["name"]), field="Room name")
            room_type = clean_room_type(values.get("room_type", room["room_type"]))
            points = room["points"]
            if "points" in values:
                points = clean_room_points(values["points"], floor_map["width"], floor_map["height"])

            uow.floor_maps.update_room(room_id, room_type, name, points, now_iso())

    def delete_room(self, room_id):
        with self.database.write(touch=TOUCH) as uow:
            self._room(uow, room_id)
            uow.floor_maps.delete_room(room_id)

    # --------------------------------------------------------
    # Workplaces
    # --------------------------------------------------------

    def create_workplace(self, map_id, values):
        with self.database.write(touch=TOUCH) as uow:
            floor_map = self._map(uow, map_id)
            cleaned = self._workplace_values(values, {}, floor_map)
            return uow.floor_maps.create_workplace(map_id, cleaned, now_iso())

    def update_workplace(self, workplace_id, values):
        with self.database.write(touch=TOUCH) as uow:
            workplace = self._workplace(uow, workplace_id)
            floor_map = self._map(uow, workplace["map_id"])
            cleaned = self._workplace_values(values, workplace, floor_map)
            uow.floor_maps.update_workplace(workplace_id, cleaned, now_iso())

    def fill_sockets(self, map_id):
        """Set every suggested socket on the map (workplaces without one).
        Returns how many were set."""

        data = self.map_data(map_id)
        suggestions = {w["id"]: w["suggested_socket"] for w in data["workplaces"] if w.get("suggested_socket")}
        if not suggestions:
            return 0
        with self.database.write(touch=TOUCH) as uow:
            now = now_iso()
            for workplace_id, socket in suggestions.items():
                workplace = self._workplace(uow, workplace_id)
                if (workplace.get("socket") or "").strip():
                    continue
                floor_map = self._map(uow, workplace["map_id"])
                values = self._workplace_values({"socket": socket}, workplace, floor_map)
                uow.floor_maps.update_workplace(workplace_id, values, now)
        return len(suggestions)

    def delete_workplace(self, workplace_id):
        with self.database.write(touch=TOUCH) as uow:
            self._workplace(uow, workplace_id)
            uow.floor_maps.delete_workplace(workplace_id)

    # --------------------------------------------------------
    # Moves
    # --------------------------------------------------------

    def move(self, map_id, rooms, workplaces):
        """Save new geometry of several items at once (dragging a room moves
        the workplaces inside it too). rooms: [{id, points}], workplaces: [{id, x, y}]."""

        if not isinstance(rooms, list) or not isinstance(workplaces, list):
            raise ValidationError("rooms and workplaces must be lists")

        with self.database.write(touch=TOUCH) as uow:
            floor_map = self._map(uow, map_id)
            now = now_iso()

            for item in rooms:
                room = self._room(uow, _item_id(item))
                if room["map_id"] != map_id:
                    raise ValidationError("Room belongs to another map")
                points = clean_room_points(item.get("points"), floor_map["width"], floor_map["height"])
                uow.floor_maps.update_room(room["id"], room["room_type"], room["name"], points, now)

            for item in workplaces:
                workplace = self._workplace(uow, _item_id(item))
                if workplace["map_id"] != map_id:
                    raise ValidationError("Workplace belongs to another map")
                cleaned = self._workplace_values({"x": item.get("x"), "y": item.get("y")}, workplace, floor_map)
                uow.floor_maps.update_workplace(workplace["id"], cleaned, now)

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    @staticmethod
    def _add_network(uow, workplaces):
        """``network``: the switch port where each PC is seen now. By its IP
        (ARP -> MAC -> port); without an IP, by the MAC documented for a
        device of the same name (cable journal)."""

        port_rows = None
        ips = [ip for workplace in workplaces for ip in (workplace["ip"], workplace.get("dante_ip")) if ip]
        located = {}
        if ips:
            port_rows = uow.switches.list_all_ports_with_switch()
            located = locate_ips(ips, uow.arp.list_newest_first(), port_rows)

        documented = {}
        for row in uow.checks.expected_devices():
            if row["name"]:
                documented.setdefault(row["name"].strip().lower(), set()).add(row["mac"])
        by_name = {
            workplace["id"]: documented[workplace["pc_name"].strip().lower()]
            for workplace in workplaces
            if not workplace["ip"] and workplace["pc_name"] and workplace["pc_name"].strip().lower() in documented
        }
        found_by_mac = {}
        if by_name:
            port_rows = port_rows if port_rows is not None else uow.switches.list_all_ports_with_switch()
            found_by_mac = locate_macs(set().union(*by_name.values()), port_rows)

        for workplace in workplaces:
            workplace["dante_network"] = located.get(workplace["dante_ip"]) if workplace.get("dante_ip") else None
            if workplace["ip"]:
                workplace["network"] = located.get(workplace["ip"])
            else:
                hits = [found_by_mac[mac] for mac in sorted(by_name.get(workplace["id"], ())) if mac in found_by_mac]
                workplace["network"] = hits[0] if hits else None

    @staticmethod
    def _add_socket_cabling(uow, workplaces):
        """For each workplace: ``cabling`` — its wall socket -> patch port ->
        switch port as documented, and whether the PC is really there now;
        ``suggested_socket`` — the socket of the patch port cabled to the
        switch port where the PC is seen, when no socket is set yet."""

        sockets = {}            # socket key -> [patch port row]
        socket_of = {}          # (panel id, port) -> socket name
        notes_by_port = {}      # (panel id, port) -> note, lower case
        for row in uow.checks.patch_port_notes():
            notes_by_port[(row["patch_panel_id"], row["port"])] = row["description"].lower()
            for name in sockets_of_patch_port(row["label"], row["description"]):
                if row not in sockets.setdefault(socket_key(name), []):
                    sockets[socket_key(name)].append(row)
                socket_of.setdefault((row["patch_panel_id"], row["port"]), name)
        if not any(w.get("socket") or w.get("dante_socket") for w in workplaces) and not socket_of:
            return

        graph = load_cable_graph(uow)
        switch_names = {row["id"]: row["host"] for row in uow.checks.switches()}
        if_names = {(row["switch_id"], row["port"]): row["if_name"] for row in uow.checks.ports()}

        for workplace in workplaces:
            network = workplace.get("network") or {}
            seen = {(port["switch_id"], port["port"]) for port in network.get("ports", [])}
            # The socket may carry the PC's other card (Dante): either one counts.
            dante = workplace.get("dante_network") or {}
            seen_any = seen | {(port["switch_id"], port["port"]) for port in dante.get("ports", [])}

            def cabling_of(socket, seen_ports):
                rows = sockets.get(socket_key(socket), [])
                cabling = {"socket": socket, "found": bool(rows), "ambiguous": len(rows) > 1}
                if rows:
                    row = rows[0]
                    cabling["patch"] = f"{row['panel']} p{row['port']}"
                    cabling["where"] = f"{row['room']} / {row['rack']}"
                    far = graph.far_end(("patch", row["patch_panel_id"], row["port"]))
                    if far is not None and far[0][0] == "switch":
                        switch_id, port = far[0][1], far[0][2]
                        cabling["switch"] = {
                            "switch_id": switch_id, "port": port,
                            "switch": switch_names.get(switch_id, f"switch {switch_id}"),
                            "port_name": if_names.get((switch_id, port)) or f"p{port}",
                        }
                        # None when the PC is not seen right now.
                        cabling["matches_network"] = (switch_id, port) in seen_ports if seen_ports else None
                return cabling

            # The Dante card's own socket: checked against where the Dante card is seen.
            dante_socket = (workplace.get("dante_socket") or "").strip()
            if dante_socket:
                dante_seen = {(port["switch_id"], port["port"]) for port in dante.get("ports", [])}
                workplace["dante_cabling"] = cabling_of(dante_socket, dante_seen)

            socket = (workplace.get("socket") or "").strip()
            if socket:
                workplace["cabling"] = cabling_of(socket, seen_any)
            else:
                suggestion = None
                if len(seen) == 1:
                    switch_id, port = next(iter(seen))
                    for peer, _ in graph.cord_peers(("switch", switch_id, port)):
                        if peer[0] == "patch" and (peer[1], peer[2]) in socket_of:
                            suggestion = socket_of[(peer[1], peer[2])]
                            break
                if suggestion is None and workplace.get("pc_name"):
                    # The cable journal wrote "NH-JOURN210 (socket 2-19)" on patch ports.
                    name = re.compile(r"(?<![\w-])" + re.escape(workplace["pc_name"].strip().lower()) + r"(?![\w-])")
                    hits = {socket_of[key] for key, note in notes_by_port.items() if key in socket_of and name.search(note)}
                    if len(hits) == 1:
                        suggestion = hits.pop()
                if suggestion:
                    workplace["suggested_socket"] = suggestion

    @staticmethod
    def _workplace_values(values, current, floor_map):
        x, y = clean_point(
            values.get("x", current.get("x")),
            values.get("y", current.get("y")),
            floor_map["width"],
            floor_map["height"],
        )

        def text(field, label):
            return clean_text(values.get(field, current.get(field, "")), field=label)

        device_type = clean_device_type(values.get("device_type", current.get("device_type", "pc")))

        return {
            "x": x,
            "y": y,
            "device_type": device_type,
            # Phones and Wi-Fi points have no PC role.
            "role": text("role", "PC role") if device_type == "pc" else "",
            "pc_name": text("pc_name", "PC name"),
            "ip": clean_ip(values.get("ip", current.get("ip", ""))),
            "note": clean_note(values.get("note", current.get("note", ""))),
            "socket": clean_socket(values.get("socket", current.get("socket", ""))),
            # A PC can have a second network card in the Dante audio network,
            # often in a wall socket of its own.
            "dante_ip": clean_ip(values.get("dante_ip", current.get("dante_ip", ""))) if device_type == "pc" else "",
            "dante_socket": clean_socket(values.get("dante_socket", current.get("dante_socket", ""))) if device_type == "pc" else "",
        }

    @staticmethod
    def _check_fits(uow, map_id, width, height):
        for room in uow.floor_maps.list_rooms(map_id):
            if any(x > width or y > height for x, y in room["points"]):
                raise ValidationError(f"Room '{room['name'] or room['id']}' does not fit into {width} x {height}")
        for workplace in uow.floor_maps.list_workplaces(map_id):
            if workplace["x"] > width or workplace["y"] > height:
                raise ValidationError(f"Workplace '{workplace['pc_name'] or workplace['id']}' does not fit into {width} x {height}")

    @staticmethod
    def _map(uow, map_id):
        floor_map = uow.floor_maps.get_map(map_id)
        if floor_map is None:
            raise NotFoundError("Map not found")
        return floor_map

    @staticmethod
    def _room(uow, room_id):
        room = uow.floor_maps.get_room(room_id)
        if room is None:
            raise NotFoundError("Room not found")
        return room

    @staticmethod
    def _workplace(uow, workplace_id):
        workplace = uow.floor_maps.get_workplace(workplace_id)
        if workplace is None:
            raise NotFoundError("Workplace not found")
        return workplace


def _item_id(item):
    try:
        return int(item.get("id"))
    except (AttributeError, TypeError, ValueError):
        raise ValidationError("Invalid item id")
