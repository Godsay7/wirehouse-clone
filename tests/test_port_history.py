"""Port history: one switch port's link, devices, errors and Rack History."""

import os
import sqlite3
import tempfile
import unittest

from Project.collector import storage
from Project.web import create_app
from tests.test_web import create_inventory_db

PC, OTHER = "00:bb:cc:00:00:07", "00:bb:cc:00:00:99"


class PortHistoryTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.app = create_app(self.db_path)
        self.client = self.app.test_client()

    def poll(self, link, mac, speed="1G"):
        """One collector run for SW-A port 2."""
        connection = sqlite3.connect(self.db_path)
        try:
            storage.save_switch_to_database(connection, "SW-A", [{
                "Port": 2, "Device": "-", "Speed": speed, "Link": link, "MAC": mac,
                "_ifIndex": 10102, "_ifName": "Gi1/0/2",
            }])
        finally:
            connection.close()

    def history(self, **args):
        return self.app.extensions["services"].port_history.history(1, 2, **args)

    def test_what_happened_on_the_port(self):
        self.poll("UP", PC)
        self.poll("DOWN", "-")
        self.poll("UP", OTHER, speed="100M")
        self.client.post("/ports/name", json={"switch_id": 1, "port": 2, "name": "Front desk"})
        connection = sqlite3.connect(self.db_path)
        connection.execute("INSERT INTO port_error_events (switch_id, port, detected_at, in_errors, out_errors, fcs_errors) "
                           "VALUES (1, 2, '2099-01-01T00:00:00+00:00', 0, 0, 12)")
        connection.execute("INSERT INTO port_changes (switch_id, port, change_type, old_value, new_value, detected_at) "
                           "VALUES (1, 1, 'Link', 'UP', 'DOWN', '2099-01-01T00:00:00+00:00')")   # another port
        connection.commit()
        connection.close()

        data = self.history()
        kinds = [event["kind"] for event in data["events"]]
        self.assertEqual(kinds[0], "errors")                              # newest first
        self.assertIn("doc", kinds)
        # 1G -> 100M came with the link going up: shown in that row.
        self.assertNotIn("speed", kinds)
        self.assertIn({"old": "1G", "new": "100M"}, [e.get("speed") for e in data["events"] if e["kind"] == "link"])
        self.assertEqual([e["up"] for e in data["events"] if e["kind"] == "link"], [True, False, True])
        self.assertNotIn(1, {e.get("port") for e in data["events"]})
        devices = [e for e in data["events"] if e["kind"] == "devices"]
        self.assertTrue(any([d["mac"] for d in e["appeared"]] == [OTHER] for e in devices))
        self.assertTrue(any([d["mac"] for d in e["left"]] == [PC] for e in devices))
        doc = next(e for e in data["events"] if e["kind"] == "doc")
        self.assertTrue(any("Front desk" in line for line in doc["lines"]))
        self.assertEqual(data["port"]["written"]["name"], "Front desk")

        page = self.client.get("/switch/1/port/2").get_data(as_text=True)
        for text in ("Port history", "Link went down", "Link came up", "Errors grew", "CRC 12", OTHER, "Front desk"):
            self.assertIn(text, page)
        self.assertEqual(self.client.get("/switch/1/port/99").status_code, 404)
        self.assertEqual(self.client.get("/switch/99/port/2").status_code, 404)

    def test_paging_keeps_one_moment_together(self):
        connection = sqlite3.connect(self.db_path)
        connection.executemany(
            "INSERT INTO port_changes (switch_id, port, change_type, old_value, new_value, detected_at) VALUES (1, 2, ?, ?, ?, ?)",
            [("Link", "DOWN", "UP", "2026-11-01T10:00:00+00:00"),
             ("Link", "UP", "DOWN", "2026-11-02T10:00:00+00:00"),
             ("MAC", PC, "-", "2026-11-02T10:00:00+00:00"),          # the same moment as the link going down
             ("Link", "DOWN", "UP", "2026-11-03T10:00:00+00:00")])
        connection.commit()
        connection.close()

        first = self.history(limit=2)
        # The second event's moment has two events: both are on the first page.
        self.assertEqual([e["at"][:10] for e in first["events"]], ["2026-11-03", "2026-11-02", "2026-11-02"])
        self.assertEqual(first["older"], "2026-11-02T10:00:00+00:00")
        rest = self.history(before=first["older"], limit=2)
        self.assertEqual([e["at"][:10] for e in rest["events"]], ["2026-11-01"])
        self.assertIsNone(rest["older"])

    def test_uplink_devices_are_counts(self):
        many = ", ".join(f"00:bb:cc:00:01:{i:02x}" for i in range(6))
        self.poll("UP", PC)
        self.poll("UP", many)
        event = next(e for e in self.history()["events"] if e["kind"] == "devices")
        self.assertEqual((event["many"], event["old_count"], event["new_count"]), (True, 1, 6))

    def test_links_to_the_port_history(self):
        self.poll("UP", PC)
        self.poll("DOWN", "-")
        page = self.client.get("/switch/1").get_data(as_text=True)
        self.assertIn('href="/switch/1/port/2"', page)                       # the tile and the table
        self.assertIn('<a class="compact-port', page)
        self.assertIn('href="/switch/1/port/2"', self.client.get("/changes").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
