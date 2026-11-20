"""Table definitions and in-place migrations."""

from .floor_maps import ensure_floor_map_schema
from .inventory import ensure_inventory_schema
from .rack import ensure_rack_schema
from .state import ensure_state_schema

__all__ = ["ensure_floor_map_schema", "ensure_inventory_schema", "ensure_rack_schema", "ensure_state_schema"]
