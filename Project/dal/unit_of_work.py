"""All repositories bound to one SQLite connection."""

from .repositories.arp import ArpRepository
from .repositories.audit import AuditRepository
from .repositories.checks import CheckRepository
from .repositories.checklist import ChecklistRepository
from .repositories.connections import ConnectionRepository
from .repositories.equipment import EquipmentRepository
from .repositories.floor_maps import FloorMapRepository
from .repositories.history import HistoryRepository
from .repositories.racks import RackRepository
from .repositories.state import StateRepository
from .repositories.switches import SwitchRepository
from .repositories.trunks import TrunkRepository


class UnitOfWork:
    def __init__(self, connection):
        self.connection = connection

        self.switches = SwitchRepository(connection)
        self.history = HistoryRepository(connection)
        self.arp = ArpRepository(connection)
        self.racks = RackRepository(connection)
        self.equipment = EquipmentRepository(connection)
        self.connections = ConnectionRepository(connection)
        self.state = StateRepository(connection)
        self.floor_maps = FloorMapRepository(connection)
        self.trunks = TrunkRepository(connection)
        self.checks = CheckRepository(connection)
        self.checklist = ChecklistRepository(connection)
        self.audit = AuditRepository(connection)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()
