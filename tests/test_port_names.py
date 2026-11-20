"""Names typed in for switch ports, last known data of down ports, another device on a port."""

import os
import sqlite3
import tempfile
import unittest

from Project.collector import storage
from Project.web import create_app
from tests.test_web import create_inventory_db

PC = "aa:bb:cc:00:00:07"


class PortNamesTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.app = create_app(self.db_path)
        self.client = self.app.test_client()

    def poll(self, link, mac):
        """One collector run for SW-A port 2."""
        connection = sqlite3.connect(self.db_path)
        try:
            storage.save_switch_to_database(connection, "SW-A", [{
                "Port": 2, "Device": "-", "Speed": "1G", "Link": link, "MAC": mac,
                "_ifIndex": 10102, "_ifName": "Gi1/0/2",
            }])
        finally:
            connection.close()

    def port_cell(self):
        page = self.client.get("/switch/1").get_data(as_text=True)
        table = page.split("port-details-table")[1]
        row = table.split('href="/switch/1/port/2"')[1].split("</tr>")[0]
        return row

    def test_written_name_from_unverified_to_confirmed_and_last_known(self):
        # A name for the PC on SW-A port 2 (down, the PC is off): not verified yet.
        connection = sqlite3.connect(self.db_path)
        connection.execute("INSERT INTO port_names (switch_id, port, mac, name, confirmed_at, created_at) "
                           "VALUES (1, 2, ?, 'NH-JOURN207', NULL, '2026-11-01T00:00:00')", (PC,))
        connection.commit()
        connection.close()
        row = self.port_cell()
        self.assertIn("NH-JOURN207", row)
        self.assertIn("not verified", row)

        # The PC is switched on: seen on the port -> confirmed.
        self.poll("UP", PC)
        row = self.port_cell()
        self.assertIn("confirmed", row)
        self.assertNotIn("not verified", row)
        self.assertNotIn("Last known data", row)

        # Link down, no MAC: name and MAC stay, as last known data.
        self.poll("DOWN", "-")
        row = self.port_cell()
        self.assertIn("Last known data", row)
        self.assertIn(PC, row)
        self.assertIn("NH-JOURN207", row)

        # Up again with another device: live data, no "last known".
        self.poll("UP", "aa:bb:cc:00:00:99")
        row = self.port_cell()
        self.assertNotIn("Last known data", row)
        self.assertIn("aa:bb:cc:00:00:99", row)

    def test_any_port_can_be_named_on_the_switch_page(self):
        # Port 2 had PC on it and is down now: the name is tied to that last MAC.
        self.poll("UP", PC)
        self.poll("DOWN", "-")
        page = self.client.get("/switch/1").get_data(as_text=True)
        self.assertIn('data-port-edit data-requires-login data-switch-id="1" data-port="2"', page)
        saved = self.client.post("/ports/name", json={"switch_id": 1, "port": 2, "name": "Reception PC"}).get_json()
        self.assertEqual((saved["ok"], saved["mac"]), (True, PC))
        self.assertIn("not verified", self.port_cell())
        self.assertIn("Name on", self.client.get("/changes/racks").get_data(as_text=True))
        self.poll("UP", PC)
        self.assertIn("confirmed", self.port_cell())

        # Renamed and removed.
        self.client.post("/ports/name", json={"switch_id": 1, "port": 2, "name": "Front desk"})
        self.assertIn("Front desk", self.port_cell())
        self.client.post("/ports/name", json={"switch_id": 1, "port": 2, "name": ""})
        self.assertNotIn("Front desk", self.port_cell())
        self.assertEqual(self.client.post("/ports/name", json={"switch_id": 1, "port": 99, "name": "x"}).status_code, 404)

    def test_uplink_name_is_typed_in_by_hand(self):
        macs = ", ".join(f"aa:bb:cc:00:01:{i:02x}" for i in range(5))
        self.poll("UP", macs)
        saved = self.client.post("/ports/name", json={"switch_id": 1, "port": 2, "name": "Uplink to SW-B"}).get_json()
        self.assertEqual(saved["mac"], "")
        row = self.port_cell()
        self.assertIn("Uplink to SW-B", row)
        self.assertIn("typed in by hand", row)

    def test_another_device_on_the_port(self):
        """The collector saw one device on SW-A port 2 and later another one."""

        report = lambda: self.app.extensions["services"].cabling_check.report()
        old, new, third = "00:bb:cc:00:00:07", "00:bb:cc:00:00:99", "00:bb:cc:00:00:55"

        self.poll("UP", old)
        self.poll("DOWN", "-")                                # switched off ...
        self.poll("UP", old)                                  # ... and back: the same device
        self.assertEqual(report()["device_changes"], [])

        self.poll("DOWN", "-")
        self.poll("UP", new)                                  # another device on the port
        changes = report()["device_changes"]
        self.assertEqual(len(changes), 1)
        item = changes[0]
        self.assertEqual((item["local"]["port"], [d["mac"] for d in item["old"]], [d["mac"] for d in item["new"]]),
                         (2, [old], [new]))
        self.assertEqual(item["changes"], 1)
        self.assertTrue(item["new_is_there"])
        self.assertEqual(report()["summary"]["device_changed"], 1)

        page = self.client.get("/checks").get_data(as_text=True)
        self.assertIn("Another device on the port", page)
        self.assertIn(old, page)
        self.assertIn(new, page)
        self.assertNotIn("Remove cable", page)

        # Replaced again: still one row for the port, with its latest change.
        self.poll("UP", third)
        self.poll("DOWN", "-")
        item = report()["device_changes"][0]
        self.assertEqual(([d["mac"] for d in item["old"]], [d["mac"] for d in item["new"]], item["changes"]),
                         ([new], [third], 2))
        self.assertFalse(item["new_is_there"])                # the port is down now
        self.assertIn("2 changes", self.client.get("/checks").get_data(as_text=True))

if __name__ == "__main__":
    unittest.main()
