"""Server rooms, racks and Rack View board order."""

import sqlite3

from ...core.text import now_iso
from ..domain.rack_board import (
    next_slot_position,
    normalize_custom_slots,
    normalize_rack_order,
    normalize_slot_map,
    place_cards,
)
from ..errors import NotFoundError, ValidationError

MAX_RACK_UNITS = 100
# Rack widths in percent of a normal rack (Rack Change offers these).
RACK_WIDTHS = (100, 66, 50, 33)


class RackAdminService:

    def __init__(self, database):
        self.database = database

    # --------------------------------------------------------
    # Server rooms
    # --------------------------------------------------------

    def create_room(self, name):
        """Create a room and return its id (or the id of the existing room)."""

        name = str(name or "").strip()

        if not name:
            raise ValidationError("Server room name is required")

        with self.database.write(touch="rack") as uow:
            try:
                return uow.racks.create_room(name, now_iso())
            except sqlite3.IntegrityError:
                uow.rollback()
                return uow.racks.find_room_id_by_name(name)

    def delete_room(self, room_id):
        """Delete a room with all its racks/equipment; return the next room id."""

        with self.database.write(touch="rack") as uow:
            if uow.racks.get_room(room_id) is None:
                raise NotFoundError("Server room not found")

            uow.racks.delete_room_with_contents(room_id)
            uow.commit()

            return uow.racks.first_room_id()

    # --------------------------------------------------------
    # Racks
    # --------------------------------------------------------

    def create_rack(self, server_room_id, name, units):
        name = str(name or "").strip()
        units = max(1, min(units, MAX_RACK_UNITS))

        with self.database.write(touch="rack") as uow:
            if not name or uow.racks.get_room(server_room_id) is None:
                raise ValidationError("Rack name and server room are required")

            try:
                return uow.racks.create(server_room_id, name, units, now_iso())
            except sqlite3.IntegrityError:
                raise ValidationError(
                    "Rack with this name already exists in this server room"
                )

    def set_rack_width(self, rack_id, width_percent):
        """A narrower rack (e.g. tower PCs standing by a wall): width in percent
        of a normal one. Its units keep the board scale; it is only narrower."""

        if width_percent not in RACK_WIDTHS:
            raise ValidationError("Unknown rack width")
        with self.database.write(touch="rack") as uow:
            if not uow.racks.set_width(rack_id, width_percent):
                raise NotFoundError("Rack not found")

    def delete_rack(self, rack_id):
        """Delete a rack with its equipment; return (server_room_id, next_rack_id)."""

        with self.database.write(touch="rack") as uow:
            rack = uow.racks.get(rack_id)

            if rack is None:
                raise NotFoundError("Rack not found")

            server_room_id = rack["server_room_id"]
            uow.racks.delete_with_contents(rack_id)
            uow.commit()

            return server_room_id, uow.racks.first_rack_id_in_room(server_room_id)

    # --------------------------------------------------------
    # Rack View board order
    # --------------------------------------------------------

    def save_board_slots(self, server_room_id, raw_slots, raw_positions=None):
        """Persist exact Rack View slot positions; return the normalized slot map.

        A custom board sends the position of every slot it shows
        (raw_positions, parallel to raw_slots); the grid board does not.
        """

        with self.database.write(touch="rack") as uow:
            valid_ids = uow.racks.list_room_rack_ids(server_room_id)
            layout, _ = uow.racks.board_layout(server_room_id)

            if layout == "custom" and isinstance(raw_positions, list) and len(raw_positions) == len(raw_slots):
                rack_positions, slot_positions = normalize_custom_slots(zip(raw_positions, raw_slots), valid_ids)
                rack_at = {position: rack_id for rack_id, position in rack_positions.items()}
                self._replace_order(uow, server_room_id, rack_at.items())
                uow.racks.set_board_layout(server_room_id, "custom", slot_positions)
                return [rack_at.get(position) for position in sorted(slot_positions)]

            slots = normalize_slot_map(raw_slots, valid_ids)
            self._replace_order(uow, server_room_id, enumerate(slots))

        return slots

    # --------------------------------------------------------
    # Custom board: remove / add empty positions
    # --------------------------------------------------------

    def remove_empty_slots(self, server_room_id):
        """Keep only positions with a rack; every rack stays in its row."""

        with self.database.write(touch="rack") as uow:
            self._materialize_board(uow, server_room_id)
            uow.racks.set_board_layout(server_room_id, "custom", ())

    def add_empty_slot(self, server_room_id):
        """One more empty position after the last one; returns its position."""

        with self.database.write(touch="rack") as uow:
            visible = self._materialize_board(uow, server_room_id)
            position = next_slot_position(visible)
            uow.racks.set_board_layout(server_room_id, "custom", set(visible) | {position})
            return position

    def remove_slot(self, server_room_id, position):
        """Remove one empty position from the board."""

        with self.database.write(touch="rack") as uow:
            visible = self._materialize_board(uow, server_room_id)
            occupied = {
                int(rack["view_position"])
                for rack in uow.racks.list_room_racks(server_room_id)
                if rack.get("view_position") is not None
            }
            if position in occupied:
                raise ValidationError("This position holds a rack; move the rack first")
            if position not in visible:
                raise NotFoundError("No such position on the board")
            uow.racks.set_board_layout(server_room_id, "custom", set(visible) - {position})

    def _materialize_board(self, uow, server_room_id):
        """Save the positions the board shows right now (racks without a saved
        position get the one they are displayed at); return all shown positions."""

        if uow.racks.get_room(server_room_id) is None:
            raise NotFoundError("Server room not found")

        racks = uow.racks.list_room_racks(server_room_id)
        layout, slot_positions = uow.racks.board_layout(server_room_id)
        placed = place_cards(racks, layout, slot_positions)

        self._replace_order(
            uow,
            server_room_id,
            ((slot["index"], slot["card"]["id"]) for slot in placed if slot["card"]),
        )
        return [slot["index"] for slot in placed]

    def save_board_order(self, server_room_id, raw_rack_ids):
        """Backward compatibility with the old v16/v19 order-only payload."""

        with self.database.write(touch="rack") as uow:
            valid_ids = uow.racks.list_room_rack_ids(server_room_id)
            rack_ids = normalize_rack_order(raw_rack_ids, valid_ids)
            self._replace_order(uow, server_room_id, enumerate(rack_ids))

        return rack_ids

    def reset_board_order(self, server_room_id):
        """Back to the classic 2 x 6 grid in the default order."""

        with self.database.write(touch="rack") as uow:
            uow.racks.clear_view_order(server_room_id)
            uow.racks.set_board_layout(server_room_id, "grid", ())

    @staticmethod
    def _replace_order(uow, server_room_id, positions):
        uow.racks.clear_view_order(server_room_id)
        now = now_iso()

        for position_index, rack_id in positions:
            if rack_id is None:
                continue
            uow.racks.add_view_position(server_room_id, rack_id, position_index, now)
