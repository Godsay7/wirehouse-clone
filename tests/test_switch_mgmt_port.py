"""The management port of a mounted switch: on by hand (not in SNMP), port 0, "mng"."""

import os
import sqlite3
import tempfile
import unittest

from Project.web import create_app
from tests.test_web import create_inventory_db


class SwitchMgmtPortTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.client = create_app(self.db_path).test_client()              # signed in as "tester"
        self.client.post("/rack/server-room/create", data={"name": "Room"})
        room_id = self.db().execute("SELECT id FROM server_rooms").fetchone()[0]
        self.client.post("/rack/create", data={"name": "R1", "server_room_id": room_id})
        self.rack_id = self.db().execute("SELECT id FROM racks").fetchone()[0]
        self.client.post(f"/rack/{self.rack_id}/switch/add", data={"switch_id": 1, "rack_unit": 42})
        self.client.post(f"/rack/{self.rack_id}/patch-panel/add", data={"name": "PP1", "rack_unit": 40, "port_count": 8})
        self.panel_id = self.db().execute("SELECT id FROM patch_panels").fetchone()[0]

    def db(self):
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        return connection

    def page(self):
        return self.client.get(f"/rack-change/{self.rack_id}").get_data(as_text=True)

    def set_mgmt(self, enabled):
        return self.client.post(f"/rack/{self.rack_id}/switch/1/mgmt-port", data={"enabled": "1" if enabled else "0"})

    def test_add_cable_and_remove(self):
        self.assertNotIn('id="switch-1-port-0"', self.page())
        self.assertIn("+ mng", self.page())

        self.assertEqual(self.set_mgmt(True).status_code, 302)
        page = self.page()
        self.assertIn('id="switch-1-port-0"', page)
        self.assertIn("switch-port-mng", page)
        self.assertIn("− mng", page)

        # A cable to it, described as "mng" in Rack History.
        response = self.client.post("/rack/connect", json={
            "first_endpoint": {"type": "switch", "switch_id": 1, "switch_port": 0},
            "second_endpoint": {"type": "patch", "patch_panel_id": self.panel_id, "patch_port": 3},
        })
        self.assertTrue(response.get_json()["ok"], response.get_json())
        self.assertIn("SW-A mng", self.client.get("/changes/racks").get_data(as_text=True))

        # Removed again: its cable goes too; both steps are in Rack History.
        self.set_mgmt(False)
        self.assertNotIn('id="switch-1-port-0"', self.page())
        cables = self.db().execute(
            "SELECT count(*) FROM port_connections WHERE endpoint_a_type = 'switch' AND endpoint_a_port = 0"
            " OR endpoint_b_type = 'switch' AND endpoint_b_port = 0").fetchone()[0]
        self.assertEqual(cables, 0)
        audited = self.db().execute(
            "SELECT count(*) FROM rack_audit_rows WHERE tbl = 'rack_switches' AND op = 'update'").fetchone()[0]
        self.assertEqual(audited, 2)

    def test_not_mounted(self):
        self.assertEqual(self.client.post("/rack/999/switch/1/mgmt-port", data={"enabled": "1"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
