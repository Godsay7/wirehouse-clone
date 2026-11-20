"""Mounting and removing equipment in a rack."""

import base64
import sqlite3

from ...core.text import now_iso
from ..domain.cabling import normalize_patch_type
from ..domain.rack_units import (
    normalize_rack_side,
    occupied_label,
    occupied_units,
    requested_units,
)
from ..domain.ports import SWITCH_MGMT_PORT as MGMT_PORT
from ..domain.vendors import get_switch_rack_height
from ..errors import NotFoundError, ValidationError

PATCH_PANEL_PORT_COUNTS = (8, 12, 24, 48, 96)
PATCH_PORT_LAYOUTS = ("row", "odd_even")
MAX_PLACEHOLDER_HEIGHT = 10
MAX_PLACEHOLDER_PORTS = 192


class RackEquipmentService:

    def __init__(self, database):
        self.database = database

    # --------------------------------------------------------
    # Rack unit availability
    # --------------------------------------------------------

    @staticmethod
    def units_are_free(uow, rack_id, rack_unit, height_units=1, side="front", ignore=None):
        """Return True when every requested rack unit is free on the selected side.

        rack_unit is the lowest U occupied by the device. For a 2U organizer placed
        at U10, U10 and U11 are reserved. ignore: ("switch", switch_id),
        ("placeholder", id), ("server", id), ("patch", id) or ("organizer", id)
        — a device being moved does not block its own units.
        """

        side = normalize_rack_side(side)
        requested = requested_units(rack_unit, height_units)

        if not requested:
            return False

        rack = uow.racks.get_units(rack_id)
        if rack is None:
            return False

        if min(requested) < 1 or max(requested) > int(rack["units"]):
            return False

        switch_rows = uow.equipment.switch_placements(rack_id, side)
        placeholder_rows = uow.equipment.placeholder_placements(rack_id, side)
        if ignore and ignore[0] == "switch":
            switch_rows = [row for row in switch_rows if row["switch_id"] != ignore[1]]
        if ignore and ignore[0] == "placeholder":
            placeholder_rows = [row for row in placeholder_rows if row["id"] != ignore[1]]
        panel_rows = uow.equipment.patch_panel_placements(rack_id, side)
        if ignore and ignore[0] == "patch":
            panel_rows = [row for row in panel_rows if row["id"] != ignore[1]]
        server_rows = uow.equipment.server_placements(rack_id, side)
        if ignore and ignore[0] == "server":
            server_rows = [row for row in server_rows if row["id"] != ignore[1]]
        organizer_rows = uow.equipment.organizer_placements(rack_id, side)
        if ignore and ignore[0] == "organizer":
            organizer_rows = [row for row in organizer_rows if row["id"] != ignore[1]]

        occupied = occupied_units(
            switch_rows=switch_rows,
            placeholder_rows=placeholder_rows,
            panel_rows=panel_rows,
            organizer_rows=organizer_rows,
            server_rows=server_rows,
        )

        return requested.isdisjoint(occupied)

    @staticmethod
    def _require_rack(uow, rack_id):
        rack = uow.racks.get_units(rack_id)

        if rack is None:
            raise NotFoundError(f"Rack {rack_id} not found")

        return rack

    # --------------------------------------------------------
    # Servers (occupy both rack sides)
    # --------------------------------------------------------

    def add_server(self, rack_id, name, top_unit, height_units, port_count, side, depth="full"):
        """depth 'full' takes the units on both sides, 'half' only on `side`."""

        name = str(name or "").strip()
        depth = "half" if depth == "half" else "full"

        if port_count < 1:
            raise ValidationError("Minimum 1 port (mng) is required.")

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            bottom_unit = top_unit - height_units + 1

            if not name or bottom_unit < 1 or top_unit > int(rack["units"]):
                raise ValidationError(f"Invalid dimensions. Must fit within 1-{rack['units']}U.")

            check_sides = ("front", "rear") if depth == "full" else (normalize_rack_side(side),)
            for check_side in check_sides:
                if not self.units_are_free(uow, rack_id, bottom_unit, height_units, check_side):
                    raise ValidationError(
                        f"U{bottom_unit}-U{top_unit} is occupied on the {check_side.upper()} side"
                    )

            try:
                uow.equipment.create_server(
                    rack_id, name, bottom_unit, height_units, side, now_iso(), port_count, depth
                )
            except sqlite3.IntegrityError:
                raise ValidationError("Server with this name already exists in this rack")

    def set_server_depth(self, rack_id, server_id, depth):
        """Switch a server between full depth and its own side only."""

        depth = "half" if depth == "half" else "full"
        with self.database.write(touch="rack") as uow:
            server = uow.equipment.get_server(rack_id, server_id)
            if server is None:
                raise NotFoundError("Server not found")
            if server["depth"] == depth:
                return
            if depth == "full":
                other = "rear" if server["side"] == "front" else "front"
                height = max(1, int(server["height_units"] or 1))
                if not self.units_are_free(uow, rack_id, server["rack_unit"], height, other):
                    top = server["rack_unit"] + height - 1
                    raise ValidationError(
                        f"Cannot span the full depth: {occupied_label(server['rack_unit'], top, height)} is occupied on the {other.upper()} side"
                    )
            uow.equipment.set_server_depth(server_id, depth)

    def set_server_front_image(self, server_id, content, mime_type):
        encoded = base64.b64encode(content).decode("utf-8")

        with self.database.write(touch="rack") as uow:
            uow.equipment.set_server_front_image(server_id, f"data:{mime_type};base64,{encoded}")

    def server_front_image(self, server_id):
        """(mime type, bytes) of a server's front picture."""

        with self.database.read() as uow:
            data_url = uow.equipment.front_image(server_id)
        if not data_url or not data_url.startswith("data:") or ";base64," not in data_url:
            raise NotFoundError("No front picture")
        header, encoded = data_url[5:].split(";base64,", 1)
        return header or "application/octet-stream", base64.b64decode(encoded)

    def remove_server_front_image(self, server_id):
        with self.database.write(touch="rack") as uow:
            uow.equipment.set_server_front_image(server_id, None)

    def delete_server(self, rack_id, server_id):
        with self.database.write(touch="rack") as uow:
            uow.connections.delete_for_endpoint("server", server_id)
            uow.equipment.delete_server(rack_id, server_id)

    def add_server_port(self, server_id):
        with self.database.write(touch="rack") as uow:
            uow.equipment.add_server_port(server_id)

    def delete_server_port(self, server_id, port_number):
        with self.database.write(touch="rack") as uow:
            uow.connections.delete_for_endpoint_port("server", server_id, port_number)
            uow.equipment.delete_server_port(server_id, port_number)

    # --------------------------------------------------------
    # SNMP switches (rack_unit = TOP occupied U)
    # --------------------------------------------------------

    def mount_switch(self, rack_id, switch_id, rack_unit, side):
        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            switch_row = uow.switches.get_host(switch_id) if switch_id > 0 else None

            if switch_row is None or not (1 <= rack_unit <= rack["units"]):
                raise ValidationError("Invalid switch or rack unit")

            height_units = get_switch_rack_height(switch_row["host"])
            bottom_unit = rack_unit - height_units + 1

            if bottom_unit < 1:
                raise ValidationError(
                    f"{switch_row['host']} is {height_units}U. "
                    f"Top rack unit U{rack_unit} does not leave enough space."
                )

            if not self.units_are_free(uow, rack_id, bottom_unit, height_units, side):
                raise ValidationError(
                    f"{occupied_label(bottom_unit, rack_unit, height_units)} is already occupied on the {side} side"
                )

            if uow.equipment.is_switch_mounted(switch_id):
                raise ValidationError("This switch is already mounted in a rack")

            try:
                uow.equipment.mount_switch(rack_id, switch_id, rack_unit, height_units, side)
            except sqlite3.IntegrityError:
                raise ValidationError("This switch is already mounted in the rack")

    def move_switch(self, rack_id, switch_id, top_unit):
        """Drag a mounted switch to another unit of the same rack side (Rack Change).
        Its cables stay: they are tied to the switch and port, not to the unit."""

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            placed = uow.equipment.get_rack_switch(rack_id, switch_id)
            if placed is None:
                raise NotFoundError("The switch is not mounted in this rack")
            height = max(1, int(placed["height_units"] or 1), get_switch_rack_height(placed["host"]))
            self._check_move(uow, rack, top_unit, height, placed["side"], ("switch", switch_id))
            uow.equipment.move_switch(rack_id, switch_id, top_unit)

    def move_placeholder(self, rack_id, placeholder_id, top_unit):
        """The same for a temporary switch."""

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            placed = uow.equipment.get_placeholder(placeholder_id)
            if placed is None or placed["rack_id"] != rack_id:
                raise NotFoundError("The temporary switch is not in this rack")
            height = max(1, int(placed["height_units"] or 1))
            self._check_move(uow, rack, top_unit, height, placed["side"], ("placeholder", placeholder_id))
            uow.equipment.move_placeholder(rack_id, placeholder_id, top_unit)

    def move_server(self, rack_id, server_id, top_unit):
        """Drag a server to another unit (top_unit: its new top U). A full-depth
        server needs the units free on both sides. Its cables stay."""

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            server = uow.equipment.get_server(rack_id, server_id)
            if server is None:
                raise NotFoundError("Server not found")
            height = max(1, int(server["height_units"] or 1))
            sides = ("front", "rear") if server["depth"] != "half" else (normalize_rack_side(server["side"]),)
            self._check_move(uow, rack, top_unit, height, sides, ("server", server_id))
            uow.equipment.move_server(rack_id, server_id, top_unit - height + 1)

    def move_patch_panel(self, rack_id, panel_id, top_unit):
        """Drag a patch panel (1U) to another unit. Its cables and trunks stay."""

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            panel = uow.equipment.get_patch_panel(rack_id, panel_id)
            if panel is None:
                raise NotFoundError("Patch panel not found")
            self._check_move(uow, rack, top_unit, 1, panel["side"], ("patch", panel_id))
            uow.equipment.move_patch_panel(rack_id, panel_id, top_unit)

    def move_organizer(self, rack_id, organizer_id, top_unit):
        """Drag a cable organizer (1U / 2U) to another unit; stored by its BOTTOM U."""

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            organizer = uow.equipment.get_organizer(rack_id, organizer_id)
            if organizer is None:
                raise NotFoundError("Cable organizer not found")
            height = max(1, int(organizer["height_units"] or 1))
            self._check_move(uow, rack, top_unit, height, organizer["side"], ("organizer", organizer_id))
            uow.equipment.move_organizer(rack_id, organizer_id, top_unit - height + 1)

    def _check_move(self, uow, rack, top_unit, height, sides, ignore):
        """The units a moved device would take are inside the rack and free
        (on every side in ``sides``, a single side may be given as a string)."""

        bottom_unit = top_unit - height + 1
        if top_unit > int(rack["units"]) or bottom_unit < 1:
            raise ValidationError(f"{occupied_label(bottom_unit, top_unit, height)} is outside the rack")
        for side in ((sides,) if isinstance(sides, str) else sides):
            if not self.units_are_free(uow, rack["id"], bottom_unit, height, side, ignore=ignore):
                raise ValidationError(
                    f"{occupied_label(bottom_unit, top_unit, height)} is already occupied on the {side} side"
                )

    def set_switch_mgmt_port(self, rack_id, switch_id, enabled):
        """Show (or remove) the management port of a mounted switch: port 0,
        "mng", after its SNMP ports. Removing it removes its cable too."""

        with self.database.write(touch="rack") as uow:
            if uow.equipment.get_rack_switch(rack_id, switch_id) is None:
                raise NotFoundError("The switch is not mounted in this rack")
            if not enabled:
                uow.connections.delete_for_endpoint_port("switch", switch_id, MGMT_PORT)
            uow.equipment.set_switch_mgmt_port(rack_id, switch_id, enabled)

    def unmount_switch(self, rack_id, switch_id):
        with self.database.write(touch="rack") as uow:
            uow.connections.delete_for_endpoint("switch", switch_id)
            uow.equipment.unmount_switch(rack_id, switch_id)

    # --------------------------------------------------------
    # Temporary switches not present in SNMP inventory yet
    # --------------------------------------------------------

    def add_placeholder(self, rack_id, name, model, rack_unit, height_units, port_count, side):
        name = str(name or "").strip()
        model = str(model or "").strip()
        height_units = max(1, min(height_units, MAX_PLACEHOLDER_HEIGHT))
        port_count = max(0, min(port_count, MAX_PLACEHOLDER_PORTS))

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            bottom_unit = rack_unit - height_units + 1

            if not name or rack_unit < 1 or rack_unit > int(rack["units"]) or bottom_unit < 1:
                raise ValidationError("Temporary switch name and valid rack position are required")

            if not self.units_are_free(uow, rack_id, bottom_unit, height_units, side):
                raise ValidationError(
                    f"{occupied_label(bottom_unit, rack_unit, height_units)} is already occupied on the {side} side"
                )

            try:
                uow.equipment.create_placeholder(
                    rack_id, name, model or None, rack_unit, height_units, port_count, side, now_iso()
                )
            except sqlite3.IntegrityError:
                raise ValidationError("A temporary switch with this name already exists on this rack side")

    def delete_placeholder(self, rack_id, placeholder_id):
        with self.database.write(touch="rack") as uow:
            uow.connections.delete_for_endpoint("placeholder", placeholder_id)
            uow.equipment.delete_placeholder(rack_id, placeholder_id)

    # --------------------------------------------------------
    # Patch panels (1U)
    # --------------------------------------------------------

    def add_patch_panel(self, rack_id, name, rack_unit, port_count, patch_type, side):
        name = str(name or "").strip()
        patch_type = normalize_patch_type(patch_type)

        if port_count not in PATCH_PANEL_PORT_COUNTS:
            port_count = 24

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)

            if not name or not (1 <= rack_unit <= rack["units"]):
                raise ValidationError("Patch panel name and valid rack unit are required")

            if not self.units_are_free(uow, rack_id, rack_unit, 1, side):
                raise ValidationError(f"U{rack_unit} is already occupied on the {side} side")

            try:
                uow.equipment.create_patch_panel(
                    rack_id, name, rack_unit, port_count, patch_type, side, now_iso()
                )
            except sqlite3.IntegrityError:
                raise ValidationError("Patch panel with this name already exists in this rack")

    def set_patch_panel_layout(self, rack_id, panel_id, port_layout):
        """'row' (1, 2, 3 … in a row) or 'odd_even' (odd ports on top, even below)."""

        if port_layout not in PATCH_PORT_LAYOUTS:
            raise ValidationError("Unknown port layout")
        with self.database.write(touch="rack") as uow:
            if not uow.equipment.set_patch_panel_layout(rack_id, panel_id, port_layout):
                raise NotFoundError("Patch panel not found")

    def delete_patch_panel(self, rack_id, panel_id):
        with self.database.write(touch="rack") as uow:
            uow.connections.delete_for_endpoint("patch", panel_id)
            uow.equipment.delete_patch_panel(rack_id, panel_id)

    # --------------------------------------------------------
    # Cable organizers (1U or 2U, rack_unit = BOTTOM U)
    # --------------------------------------------------------

    def add_organizer(self, rack_id, name, rack_unit, height_units, side):
        name = str(name or "Cable Organizer").strip() or "Cable Organizer"

        if height_units not in (1, 2):
            height_units = 1

        with self.database.write(touch="rack") as uow:
            rack = self._require_rack(uow, rack_id)
            top_unit = rack_unit + height_units - 1

            if rack_unit < 1 or top_unit > int(rack["units"]):
                raise ValidationError(f"{height_units}U organizer does not fit starting at U{rack_unit}")

            if not self.units_are_free(uow, rack_id, rack_unit, height_units, side):
                raise ValidationError(
                    f"{occupied_label(rack_unit, top_unit, height_units)} is already occupied on the {side} side"
                )

            uow.equipment.create_organizer(rack_id, name, rack_unit, height_units, side, now_iso())

    def delete_organizer(self, rack_id, organizer_id):
        with self.database.write(touch="rack") as uow:
            uow.equipment.delete_organizer(rack_id, organizer_id)
