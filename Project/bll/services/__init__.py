"""Use-case services. Each method opens one unit of work (one connection)."""

from dataclasses import dataclass

from ...dal import Database
from ...core.text import now_iso
from ...dal.schema import ensure_floor_map_schema, ensure_inventory_schema, ensure_rack_schema
from ..domain.vendors import SPECIAL_CISCO_4900M_SWITCHES
from .cabling import CablingService
from .cabling_check import CablingCheckService
from .checklist import ChecklistService
from .floor_maps import FloorMapService
from .home import HomeService
from .inventory import InventoryService
from .port_history import PortHistoryService
from .rack_admin import RackAdminService
from .rack_equipment import RackEquipmentService
from .rack_history import RackHistoryService
from .rack_view import RackViewService


@dataclass
class Services:
    database: Database
    inventory: InventoryService
    rack_view: RackViewService
    rack_admin: RackAdminService
    rack_equipment: RackEquipmentService
    rack_history: RackHistoryService
    cabling: CablingService
    cabling_check: CablingCheckService
    floor_maps: FloorMapService
    home: HomeService = None
    port_history: PortHistoryService = None
    checklist: ChecklistService = None

    @classmethod
    def create(cls, database):
        services = cls(
            database=database,
            inventory=InventoryService(database),
            rack_view=RackViewService(database),
            rack_admin=RackAdminService(database),
            rack_equipment=RackEquipmentService(database),
            rack_history=RackHistoryService(database),
            cabling=CablingService(database),
            cabling_check=CablingCheckService(database),
            floor_maps=FloorMapService(database),
        )
        # The home page reads the other services.
        services.home = HomeService(database, services)
        services.port_history = PortHistoryService(database, services.inventory)
        services.checklist = ChecklistService(database)
        return services

    def ensure_schema(self):
        """Create/migrate every table the web app reads or writes."""

        connection = self.database.connect()

        try:
            ensure_inventory_schema(connection)
            ensure_rack_schema(
                connection,
                two_unit_switch_hosts=sorted(SPECIAL_CISCO_4900M_SWITCHES),
            )
            ensure_floor_map_schema(connection, now=now_iso())
        finally:
            connection.close()

    def data_versions(self):
        """Data version counters; zeros when the database is not available."""

        try:
            with self.database.read() as uow:
                return uow.state.versions()
        except Exception:
            return {"inventory": 0, "rack": 0, "maps": 0}
