"""VLANs and port errors on the switch page and the dashboard."""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from Project.web import create_app
from tests.test_web import create_inventory_db


class VlanErrorsWebTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
        connection = sqlite3.connect(self.db_path)
        connection.executescript(f"""
            UPDATE ports SET vlan_mode = 'access', vlan = 140 WHERE switch_id = 1 AND port = 1;
            UPDATE ports SET vlan_mode = 'trunk', vlan = 1, vlan_tagged = '140-142' WHERE switch_id = 2 AND port = 1;
            INSERT INTO port_error_events (switch_id, port, detected_at, in_errors, out_errors, fcs_errors)
            VALUES (1, 1, '{recent}', 2, 0, 30), (1, 2, '{old}', 5, 0, 0);
        """)
        connection.commit()
        connection.close()
        self.client = create_app(self.db_path).test_client()

    def test_switch_page_shows_vlan_and_recent_errors(self):
        page = self.client.get("/switch/1").get_data(as_text=True)
        self.assertIn('<td class="vlan-cell">', page)
        self.assertIn("140", page)
        self.assertIn("errors 32", page)              # only the recent event counts
        self.assertIn("CRC 30", page)
        self.assertEqual(page.count('class="port-errors-badge"'), 1)
        self.assertIn("compact-port-errors", page)

    def test_switch_page_vlan_search(self):
        page = self.client.get("/switch/2?search=vlan 141").get_data(as_text=True)
        self.assertIn("Te1/1", page)
        page = self.client.get("/switch/1?search=vlan 141").get_data(as_text=True)
        self.assertNotIn("Gi1/0/1", page.split("port-details-table")[1])

    def test_dashboard_vlan_search_and_error_counts(self):
        page = self.client.get("/dashboard?search=vlan 140").get_data(as_text=True)
        self.assertIn("Gi1/0/1", page)                # access port in VLAN 140
        self.assertIn("trunk 1 + 140-142", page)     # trunk carrying it
        self.assertNotIn("Gi1/0/2", page.split("switches-table")[0])
        page = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("Ports with errors", page)


if __name__ == "__main__":
    unittest.main()
