"""Rack unit geometry.

Conventions (kept from the original data):
  * switches and temporary switches: rack_unit is the TOP occupied U;
  * servers, patch panels and cable organizers: rack_unit is the BOTTOM U.
"""

from .vendors import get_switch_rack_height

SIDES = ("front", "rear")


def normalize_rack_side(value):
    return "rear" if str(value or "").lower() == "rear" else "front"


def units_from_top(top_unit, height):
    return set(range(top_unit - height + 1, top_unit + 1))


def units_from_bottom(bottom_unit, height):
    return set(range(bottom_unit, bottom_unit + height))


def occupied_units(
    switch_rows,
    placeholder_rows,
    panel_rows,
    organizer_rows,
    server_rows,
):
    """Collect every occupied U from placement rows of one rack side."""

    occupied = set()

    for row in switch_rows:
        # For switches rack_unit is the TOP occupied U.  This keeps existing
        # one-unit placements unchanged and lets the 2U 4900M at U42 occupy
        # U42 and U41, matching normal rack notation.
        height = max(
            1,
            int(row["height_units"] or 1),
            get_switch_rack_height(row["host"]),
        )
        occupied.update(units_from_top(int(row["rack_unit"]), height))

    for row in placeholder_rows:
        height = max(1, int(row["height_units"] or 1))
        occupied.update(units_from_top(int(row["rack_unit"]), height))

    occupied.update(int(row["rack_unit"]) for row in panel_rows)

    for row in organizer_rows:
        height = max(1, int(row["height_units"] or 1))
        occupied.update(units_from_bottom(int(row["rack_unit"]), height))

    for row in server_rows:
        height = max(1, int(row["height_units"] or 1))
        occupied.update(units_from_bottom(int(row["rack_unit"]), height))

    return occupied


def requested_units(rack_unit, height_units):
    """Units requested by a device whose lowest U is rack_unit, or None if invalid."""

    try:
        rack_unit = int(rack_unit)
        height_units = int(height_units)
    except (TypeError, ValueError):
        return None

    if height_units < 1:
        return None

    return units_from_bottom(rack_unit, height_units)


def segment_name(height, occupied_unit, top_unit):
    """'single' for 1U devices; 'top'/'bottom' rows of a multi-U device."""

    if height == 1:
        return "single"
    return "top" if occupied_unit == top_unit else "bottom"


def occupied_label(bottom_unit, top_unit, height_units):
    return f"U{top_unit}" if height_units == 1 else f"U{bottom_unit}-U{top_unit}"
