"""Validation rules for floor maps: sizes, room outlines, workplace fields.

Coordinates are in grid cells; the map is ``width`` x ``height`` cells.
"""

import ipaddress

import re
from ..errors import ValidationError

MIN_MAP_SIZE = 10
MAX_MAP_SIZE = 400
DEFAULT_MAP_WIDTH = 80
DEFAULT_MAP_HEIGHT = 50

MAX_NAME_LENGTH = 80
MAX_NOTE_LENGTH = 500
MAX_ROOM_POINTS = 200

# Outlines: a room (walls) or a work area inside it (dashed, see-through).
ROOM_TYPES = ("room", "area")

# What stands at a place on the map. Only PCs have a role.
DEVICE_TYPES = ("pc", "phone", "wifi")

# Room corners snap to half a cell, workplaces to a quarter.
ROOM_STEP = 0.5
WORKPLACE_STEP = 0.25


def clean_text(value, max_length=MAX_NAME_LENGTH, field="Value"):
    text = " ".join(str(value or "").split())
    if len(text) > max_length:
        raise ValidationError(f"{field} is longer than {max_length} characters")
    return text


def clean_note(value):
    text = str(value or "").strip()
    if len(text) > MAX_NOTE_LENGTH:
        raise ValidationError(f"Note is longer than {MAX_NOTE_LENGTH} characters")
    return text


def clean_map_name(value):
    name = clean_text(value, field="Map name")
    if not name:
        raise ValidationError("Map name is required")
    return name


def clean_map_size(value, default):
    if value in (None, ""):
        return default
    try:
        size = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Map size must be a whole number")
    if not MIN_MAP_SIZE <= size <= MAX_MAP_SIZE:
        raise ValidationError(f"Map size must be between {MIN_MAP_SIZE} and {MAX_MAP_SIZE} cells")
    return size


def clean_room_type(value):
    room_type = str(value or "room").strip().lower()
    if room_type not in ROOM_TYPES:
        raise ValidationError(f"Unknown room type '{room_type}'")
    return room_type


def clean_device_type(value):
    device_type = str(value or "pc").strip().lower()
    if device_type not in DEVICE_TYPES:
        raise ValidationError(f"Unknown device type '{device_type}'")
    return device_type


def clean_ip(value):
    """'' or a valid IPv4/IPv6 address in canonical form."""

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        raise ValidationError(f"'{text}' is not a valid IP address")


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError("Coordinates must be numbers")
    if number != number or number in (float("inf"), float("-inf")):
        raise ValidationError("Coordinates must be numbers")
    return number


def snap(value, step, limit):
    """Round to the grid step and keep inside 0..limit."""

    snapped = round(_number(value) / step) * step
    return min(max(snapped, 0.0), float(limit))


def clean_point(x, y, width, height, step=WORKPLACE_STEP):
    return snap(x, step, width), snap(y, step, height)


def clean_room_points(points, width, height):
    """At least three distinct corners, snapped to the grid, inside the map."""

    if not isinstance(points, (list, tuple)):
        raise ValidationError("Room outline must be a list of points")
    if len(points) > MAX_ROOM_POINTS:
        raise ValidationError(f"Room outline has more than {MAX_ROOM_POINTS} corners")

    cleaned = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValidationError("Each room corner must be [x, y]")
        corner = [snap(point[0], ROOM_STEP, width), snap(point[1], ROOM_STEP, height)]
        if not cleaned or cleaned[-1] != corner:
            cleaned.append(corner)

    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()

    if len({tuple(corner) for corner in cleaned}) < 3:
        raise ValidationError("A room needs at least three different corners")

    return cleaned


# ------------------------------------------------------------
# Wall sockets: a workplace's socket is found on the patch port whose label
# is that socket, or whose note says "socket 2-19" (the cable journal import).
# ------------------------------------------------------------

MAX_SOCKET_LENGTH = 40
_SOCKET_IN_NOTE = re.compile(r"\bsocket\s+([^\s(),;]+)", re.IGNORECASE)


def clean_socket(value):
    return clean_text(value, max_length=MAX_SOCKET_LENGTH, field="Socket")


def socket_key(text):
    """'2-07', ' 2-7 ', '2 - 7' -> '2-7': how sockets are compared."""

    text = re.sub(r"\s+", "", str(text or "")).lower()
    parts = re.split(r"([-./])", text)
    return "".join(str(int(part)) if part.isdigit() else part for part in parts)


def sockets_of_patch_port(label, description):
    """Socket names a patch port carries: its label and 'socket X' in its note."""

    names = []
    if str(label or "").strip():
        names.append(str(label).strip())
    names.extend(match.group(1) for match in _SOCKET_IN_NOTE.finditer(str(description or "")))
    return names

