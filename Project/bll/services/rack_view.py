"""Read side of racks: Rack View board and the Rack Change editor page."""

from ..domain.ports import port_is_expected, switch_port_label
from ..domain.cabling import endpoint_media, patch_link_cable_type, resolve_cable_type
from ..domain.rack_board import place_cards
from ..domain.rack_units import normalize_rack_side, segment_name
from ..domain.vendors import (
    build_cisco_4900m_panel,
    get_port_panel_layout,
    get_switch_rack_height,
    optical_port_labels,
)
from ..errors import NotFoundError


def select_room(rooms, preferred_room_id):
    """Preferred room if it exists, else the first room, else None."""

    selected_room = None

    if preferred_room_id:
        selected_room = next(
            (room for room in rooms if room["id"] == preferred_room_id),
            None,
        )

    if selected_room is None and rooms:
        selected_room = rooms[0]

    return selected_room


def endpoint_media_from_db(uow, endpoint_type, endpoint_id):
    if endpoint_type == "placeholder":
        if uow.equipment.get_placeholder(endpoint_id) is None:
            return None
        return endpoint_media("placeholder")

    if endpoint_type == "patch":
        row = uow.equipment.find_patch_type(endpoint_id)
        return endpoint_media(
            "patch",
            row["patch_type"] if row is not None else None,
            patch_exists=row is not None,
        )

    return endpoint_media(endpoint_type)


def resolve_cable_type_from_db(uow, t1, id1, t2, id2):
    """Validate endpoint media and return (cable_type, error)."""

    return resolve_cable_type(
        t1,
        endpoint_media_from_db(uow, t1, id1),
        t2,
        endpoint_media_from_db(uow, t2, id2),
    )


class RackViewService:

    def __init__(self, database):
        self.database = database

    # --------------------------------------------------------
    # Rooms
    # --------------------------------------------------------

    def list_rooms(self):
        with self.database.read() as uow:
            return uow.racks.list_rooms()

    def list_room_racks(self, server_room_id):
        if not server_room_id:
            return []

        with self.database.read() as uow:
            return uow.racks.list_room_racks(server_room_id)

    def rack_room_id(self, rack_id):
        """The server room of a rack, or None when there is no such rack."""

        with self.database.read() as uow:
            rack = uow.racks.get(rack_id)
        return rack["server_room_id"] if rack else None

    def rooms_and_selection(self, preferred_room_id):
        """(rooms, selected_room, racks of the selected room)."""

        with self.database.read() as uow:
            rooms = uow.racks.list_rooms()
            selected_room = select_room(rooms, preferred_room_id)
            racks = (
                uow.racks.list_room_racks(selected_room["id"])
                if selected_room
                else []
            )

        return rooms, selected_room, racks

    # --------------------------------------------------------
    # Rack View board (read-only dashboard of one room)
    # --------------------------------------------------------

    def board(self, preferred_room_id):
        with self.database.read() as uow:
            rooms = uow.racks.list_rooms()
            selected_room = select_room(rooms, preferred_room_id)
            room_racks = (
                uow.racks.list_room_racks(selected_room["id"])
                if selected_room
                else []
            )
            layout, slot_positions = (
                uow.racks.board_layout(selected_room["id"])
                if selected_room
                else ("grid", set())
            )

            rack_cards = []

            for rack_row in room_racks:
                front = self._load_rack(uow, rack_row["id"], "front", include_edit_data=False)
                rear = self._load_rack(uow, rack_row["id"], "rear", include_edit_data=False)

                rack_cards.append(
                    {
                        "rack": front["rack"],
                        "front": front,
                        "rear": rear,
                        "view_position": rack_row.get("view_position"),
                    }
                )

        return {
            "server_rooms": rooms,
            "selected_room": selected_room,
            "rack_cards": rack_cards,
            "rack_slots": place_cards(rack_cards, layout, slot_positions),
            "board_layout": layout,
        }

    # --------------------------------------------------------
    # Rack Change editor page
    # --------------------------------------------------------

    def editor(self, rack_id, side):
        with self.database.read() as uow:
            data = self._load_rack(uow, rack_id, side)
            server_room_id = data["rack"]["server_room_id"]

            data["server_rooms"] = uow.racks.list_rooms()
            data["selected_room"] = {
                "id": server_room_id,
                "name": data["rack"]["server_room_name"],
            }
            data["racks"] = uow.racks.list_room_racks(server_room_id)
            data.update(self._trunk_data(uow, rack_id))

        return data

    @staticmethod
    def _trunk_data(uow, rack_id):
        """Trunk cables of this rack's ODF panels, plus every ODF for the picker."""

        odf_panels = uow.trunks.odf_panels()
        by_id = {panel["id"]: panel for panel in odf_panels}
        local = [panel for panel in odf_panels if panel["rack_id"] == rack_id]
        local_ids = {panel["id"] for panel in local}

        trunks = []
        for trunk in uow.trunks.list_for_panels(local_ids):
            # Show this rack's end first.
            here, there = ("a", "b") if trunk["panel_a_id"] in local_ids else ("b", "a")
            near, far = by_id.get(trunk[f"panel_{here}_id"]), by_id.get(trunk[f"panel_{there}_id"])
            if not near or not far:
                continue
            count = trunk["port_count"]
            near_start, far_start = trunk[f"port_{here}_start"], trunk[f"port_{there}_start"]
            trunks.append({
                "id": trunk["id"],
                "name": trunk["name"],
                "near": near["name"],
                "near_ports": f"{near_start}-{near_start + count - 1}" if count > 1 else str(near_start),
                "far": far["name"],
                "far_where": f"{far['room']} / {far['rack']}",
                "far_ports": f"{far_start}-{far_start + count - 1}" if count > 1 else str(far_start),
                "count": count,
            })

        return {"trunks": trunks, "local_odf_panels": local, "odf_panels": odf_panels}

    def load_rack(self, rack_id, side="front", include_edit_data=True):
        with self.database.read() as uow:
            return self._load_rack(uow, rack_id, side, include_edit_data)

    # --------------------------------------------------------
    # One rack side
    # --------------------------------------------------------

    def _load_rack(self, uow, rack_id, side="front", include_edit_data=True):
        """Build one rack/side for Rack View or Rack Change."""

        side = normalize_rack_side(side)

        rack = uow.racks.get_with_room(rack_id)

        if rack is None:
            raise NotFoundError(f"Rack {rack_id} not found")

        rack = dict(rack)
        device_by_unit = {}

        servers = self._load_servers(uow, rack_id, side, device_by_unit)
        rack_switches = self._load_switches(uow, rack_id, side, device_by_unit)
        placeholder_switches = self._load_placeholders(uow, rack_id, side, device_by_unit)
        patch_panels = self._load_patch_panels(uow, rack_id, side, device_by_unit)
        cable_organizers = self._load_organizers(uow, rack_id, side, device_by_unit)

        connections = self._load_connections(
            uow,
            rack_id,
            side,
            visible_switches={s["switch_id"] for s in rack_switches},
            visible_patches={p["id"] for p in patch_panels},
            visible_servers={s["id"] for s in servers if len(s.get("ports", [])) > 0},
            visible_placeholders={p["id"] for p in placeholder_switches if p["port_count"] > 0},
        )

        rack_rows = [
            {"unit": rack_unit, "device": device_by_unit.get(rack_unit)}
            for rack_unit in range(rack["units"], 0, -1)
        ]

        available_switches = []
        if include_edit_data:
            mounted_switch_ids = uow.equipment.mounted_switch_ids()
            available_switches = [
                switch
                for switch in uow.switches.list_for_rack_picker()
                if switch["id"] not in mounted_switch_ids
            ]

        return {
            "rack": rack,
            "rack_rows": rack_rows,
            "rack_switches": rack_switches,
            "placeholder_switches": placeholder_switches,
            "patch_panels": patch_panels,
            "cable_organizers": cable_organizers,
            "connections": connections,
            "available_switches": available_switches,
            "current_side": side,
        }

    @staticmethod
    def _place_from_bottom(device_by_unit, device_type, device, height):
        base_unit = int(device["rack_unit"])
        top_unit = base_unit + height - 1

        for occupied_unit in range(base_unit, base_unit + height):
            segment = dict(device)
            segment["segment"] = segment_name(height, occupied_unit, top_unit)
            segment["is_primary"] = (occupied_unit == top_unit)
            device_by_unit[occupied_unit] = {
                "type": device_type,
                "data": segment,
            }

    @staticmethod
    def _place_from_top(device_by_unit, device_type, device, height):
        top_unit = int(device["rack_unit"])
        bottom_unit = top_unit - height + 1

        for occupied_unit in range(max(1, bottom_unit), top_unit + 1):
            segment = dict(device)
            segment["segment"] = segment_name(height, occupied_unit, top_unit)
            segment["is_primary"] = (occupied_unit == top_unit)
            device_by_unit[occupied_unit] = {
                "type": device_type,
                "data": segment,
            }

    def _load_servers(self, uow, rack_id, side, device_by_unit):
        servers = []

        for server in uow.equipment.list_servers(rack_id, side):
            # Full-depth servers show on both sides with ports on the rear;
            # a half-depth one shows only on its own side, ports included.
            if server.get("depth") == "half" or side == "rear":
                server["ports"] = uow.equipment.list_server_ports(server["id"])
            else:
                server["ports"] = []

            servers.append(server)

        for server in servers:
            height = max(1, int(server.get("height_units") or 1))
            self._place_from_bottom(device_by_unit, "server", server, height)

        return servers

    def _load_switches(self, uow, rack_id, side, device_by_unit):
        rack_switches = []

        for switch in uow.equipment.list_rack_switches(rack_id, side):
            switch["ports"] = uow.switches.list_ports_with_description(switch["switch_id"])
            # Down ports are red only where something is expected (as on the
            # switch page, domain/ports.port_is_expected); free ones are quiet.
            cabled = uow.connections.cabled_switch_ports(switch["switch_id"])
            names = uow.checks.port_names(switch["switch_id"])
            for port in switch["ports"]:
                port["cabled"] = port["port"] in cabled
                port["written"] = (names.get((switch["switch_id"], port["port"])) or {}).get("name")
                port["expected"] = port_is_expected(port)
            switch["rack_port_layout"] = get_port_panel_layout(
                switch,
                switch["ports"],
            )

            physical_height = get_switch_rack_height(switch["host"])
            switch["height_units"] = max(
                physical_height,
                int(switch.get("height_units") or 1),
            )

            if switch["rack_port_layout"] == "cisco_4900m":
                switch["cisco_4900m_panel"] = build_cisco_4900m_panel(
                    switch["ports"]
                )
                switch["optical_labels"] = {}
            else:
                # Optical ports after a gap with their own numbers (Te1, Gi1,
                # SFP1 …), as on the switch page.
                switch["optical_labels"] = optical_port_labels(switch, switch["ports"])

            rack_switches.append(switch)
            self._place_from_top(device_by_unit, "switch", switch, int(switch["height_units"]))

        return rack_switches

    def _load_placeholders(self, uow, rack_id, side, device_by_unit):
        placeholder_switches = []

        for placeholder in uow.equipment.list_placeholders(rack_id, side):
            placeholder["height_units"] = max(1, int(placeholder.get("height_units") or 1))
            placeholder["port_count"] = max(0, int(placeholder.get("port_count") or 0))
            placeholder["port_notes"] = uow.equipment.placeholder_port_notes(placeholder["id"])
            placeholder_switches.append(placeholder)

            self._place_from_top(
                device_by_unit,
                "switch_placeholder",
                placeholder,
                int(placeholder["height_units"]),
            )

        return placeholder_switches

    def _load_patch_panels(self, uow, rack_id, side, device_by_unit):
        patch_panels = []

        for panel in uow.equipment.list_patch_panels(rack_id, side):
            panel["ports"] = uow.equipment.list_patch_ports(panel["id"])
            patch_panels.append(panel)
            device_by_unit[panel["rack_unit"]] = {"type": "patch_panel", "data": panel}

        return patch_panels

    def _load_organizers(self, uow, rack_id, side, device_by_unit):
        cable_organizers = uow.equipment.list_organizers(rack_id, side)

        for organizer in cable_organizers:
            height_units = 2 if int(organizer.get("height_units") or 1) == 2 else 1
            self._place_from_bottom(device_by_unit, "cable_organizer", organizer, height_units)

        return cable_organizers

    # --------------------------------------------------------
    # Connections drawn on one rack side
    # --------------------------------------------------------

    def _load_connections(self, uow, rack_id, side, visible_switches, visible_patches, visible_servers,
                          visible_placeholders=()):
        visible = {
            "switch": visible_switches,
            "patch": visible_patches,
            "server": visible_servers,
            "placeholder": visible_placeholders,
        }

        def is_visible(endpoint_type, endpoint_id):
            return endpoint_id in visible.get(endpoint_type, ())

        connections = []

        for conn in uow.connections.list_port_connections():
            a_visible = is_visible(conn["endpoint_a_type"], conn["endpoint_a_id"])
            b_visible = is_visible(conn["endpoint_b_type"], conn["endpoint_b_id"])

            if not (a_visible or b_visible):
                continue

            ep_a = self._describe_endpoint(uow, conn["endpoint_a_type"], conn["endpoint_a_id"], conn["endpoint_a_port"])
            ep_b = self._describe_endpoint(uow, conn["endpoint_b_type"], conn["endpoint_b_id"], conn["endpoint_b_port"])

            inferred_cable_type, _ = resolve_cable_type_from_db(
                uow,
                conn["endpoint_a_type"],
                conn["endpoint_a_id"],
                conn["endpoint_b_type"],
                conn["endpoint_b_id"],
            )

            conn["id"] = f"sp-{conn['id']}"
            conn["connection_ref"] = conn["id"]
            # Re-infer from current patch types so existing ODF links also
            # turn purple even if they were created before cable_type existed.
            conn["cable_type"] = inferred_cable_type or conn.get("cable_type") or "ethernet"
            conn["endpoint_a_element_id"] = ep_a["element_id"]
            conn["endpoint_a_label"] = ep_a["label"]
            conn["endpoint_a_location"] = ep_a["location"]

            conn["endpoint_b_element_id"] = ep_b["element_id"]
            conn["endpoint_b_label"] = ep_b["label"]
            conn["endpoint_b_location"] = ep_b["location"]
            connections.append(conn)

        for conn in uow.connections.list_patch_connections_for_rack_side(rack_id, side):
            conn["id"] = f"pp-{conn['id']}"
            conn["connection_ref"] = conn["id"]
            conn["cable_type"] = patch_link_cable_type(
                conn.get("patch_a_type"),
                conn.get("patch_b_type"),
                conn.get("cable_type"),
            )
            conn["endpoint_a_element_id"] = f"patch-{conn['patch_panel_a_id']}-port-{conn['patch_port_a']}"
            conn["endpoint_b_element_id"] = f"patch-{conn['patch_panel_b_id']}-port-{conn['patch_port_b']}"
            conn["endpoint_a_label"] = f"{conn['patch_a_name']} / Port {conn['patch_port_a']}"
            conn["endpoint_b_label"] = f"{conn['patch_b_name']} / Port {conn['patch_port_b']}"
            conn["endpoint_a_location"] = f"{conn['patch_a_server_room_name']} / {conn['patch_a_rack_name']} / {'Rear' if conn['patch_a_side'] == 'rear' else 'Front'}"
            conn["endpoint_b_location"] = f"{conn['patch_b_server_room_name']} / {conn['patch_b_rack_name']} / {'Rear' if conn['patch_b_side'] == 'rear' else 'Front'}"
            connections.append(conn)

        return connections

    @staticmethod
    def _describe_endpoint(uow, ep_type, ep_id, ep_port):
        label = f"{ep_type.capitalize()} {ep_id}"
        location = "Unknown"

        if ep_type == "switch":
            switch, placement = uow.equipment.switch_endpoint_info(ep_id)
            if switch:
                label = f"{switch['host']} / Port {switch_port_label(ep_port)}"
            if placement:
                location = f"{placement['room']} / {placement['name']} / {placement['side'].capitalize()}"

        elif ep_type == "patch":
            panel, rack = uow.equipment.patch_endpoint_info(ep_id)
            if panel:
                label = f"{panel['name']} / Port {ep_port}"
                if rack:
                    location = f"{rack['room']} / {rack['name']} / {panel['side'].capitalize()}"

        elif ep_type == "placeholder":
            placeholder, rack = uow.equipment.placeholder_endpoint_info(ep_id)
            if placeholder:
                label = f"{placeholder['name']} (temporary) / Port {ep_port}"
                if rack:
                    location = f"{rack['room']} / {rack['name']} / {placeholder['side'].capitalize()}"

        elif ep_type == "server":
            server, rack = uow.equipment.server_endpoint_info(ep_id)
            if server:
                port_label = "mng" if ep_port == 0 else str(ep_port)
                label = f"{server['name']} / Port {port_label}"
                if rack:
                    location = f"{rack['room']} / {rack['name']} / {server['side'].capitalize()}"

        return {
            "element_id": f"{ep_type}-{ep_id}-port-{ep_port}",
            "label": label,
            "location": location,
        }
