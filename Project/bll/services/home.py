"""Home page: search, the state of everything at a glance and the sections,
from the other services."""

from datetime import datetime, timezone

from ...core.text import parse_timestamp
from ..domain.freshness import freshness, minutes_ago
from .inventory import errors_since

# A switch not polled for this long is shown as a warning (the collector runs every 5 minutes).
STALE_AFTER_MINUTES = 20
# Ports whose error counters grew within this window need attention.
ERROR_WINDOW_HOURS = 24


class HomeService:

    def __init__(self, database, services):
        self.database = database
        self.services = services

    def overview(self, now=None):
        now = now or datetime.now(timezone.utc)
        services = self.services

        dashboard = services.inventory.dashboard("")
        switches = dashboard["switches"]
        stale = []
        newest = None
        for switch in switches:
            try:
                seen = parse_timestamp(switch.get("last_seen"))
            except (TypeError, ValueError):
                stale.append({"host": switch["host"], "id": switch["id"], "minutes": None})
                continue
            newest = seen if newest is None or seen > newest else newest
            minutes = int((now - seen).total_seconds() // 60)
            if minutes >= STALE_AFTER_MINUTES:
                stale.append({"host": switch["host"], "id": switch["id"], "minutes": minutes})

        rooms = services.rack_view.list_rooms()
        rack_count = sum(len(services.rack_view.list_room_racks(room["id"])) for room in rooms)
        check = services.cabling_check.report()["summary"]

        with self.database.read() as uow:
            error_port_count = len(uow.switches.error_growth_since(errors_since(ERROR_WINDOW_HOURS)))

        last_poll_minutes = minutes_ago(newest.isoformat(), now) if newest else None

        maps = services.floor_maps.list_maps()
        return {
            "switch_count": len(switches),
            "statistics": dashboard["statistics"],
            "last_poll": newest.isoformat() if newest else None,
            "last_poll_minutes": last_poll_minutes,
            "freshness": freshness(last_poll_minutes),
            "stale_switches": stale,
            "stale_minutes": STALE_AFTER_MINUTES,
            "room_count": len(rooms),
            "rack_count": rack_count,
            "map_count": len(maps),
            "maps": [{"id": m["id"], "name": m["name"]} for m in maps],
            "check": check,
            "check_problems": check["neighbor_mismatch"] + check["neighbor_missing"] + check["alias"],
            "error_port_count": error_port_count,
            "error_window_hours": ERROR_WINDOW_HOURS,
        }
