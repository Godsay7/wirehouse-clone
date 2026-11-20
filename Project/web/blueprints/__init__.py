"""Flask blueprints, one per page/area of the UI."""

from . import api, auth, cabling, changes, checklist, checks, home, language, dashboard, floor_maps, health, rack_change, rack_equipment, rack_view, switches

BLUEPRINTS = [
    api.bp,
    auth.bp,
    dashboard.bp,
    switches.bp,
    changes.bp,
    health.bp,
    rack_view.bp,
    rack_change.bp,
    rack_equipment.bp,
    cabling.bp,
    floor_maps.bp,
    checks.bp,
    checklist.bp,
    home.bp,
    language.bp,
]
