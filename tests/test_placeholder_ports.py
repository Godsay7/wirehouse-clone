"""Temporary switches have real ports: cables, notes, path, history, cleanup."""

import os
import sqlite3
import tempfile
import unittest

from Project.web import create_app
from tests.test_web import create_inventory_db


class PlaceholderPortsTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.app = create_app(self.db_path)
        self.client = self.app.test_client()
        self.services = self.app.extensions["services"]

        self.client.post("/rack/server-room/create", data={"name": "Room"})
        room_id = self.db().execute("SELECT id FROM server_rooms").fetchone()[0]
        self.client.post("/rack/create", data={"name": "R1", "server_room_id": room_id})
        self.rack_id = self.db().execute("SELECT id FROM racks").fetchone()[0]
        self.client.post(f"/rack/{self.rack_id}/switch-placeholder/add", data={
            "name": "DEMON1", "model": "", "rack_unit": 30, "height_units": 1, "port_count": 24, "side": "front"})
        self.placeholder_id = self.db().execute("SELECT id FROM rack_switch_placeholders").fetchone()[0]
        self.client.post(f"/rack/{self.rack_id}/patch-panel/add", data={"name": "ODF", "rack_unit": 40, "port_count": 24, "patch_type": "odf"})
        self.panel_id = self.db().execute("SELECT id FROM patch_panels").fetchone()[0]

    def db(self):
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        return connection

    def connect(self, port, patch_port=21):
        return self.client.post("/rack/connect", json={
            "first_endpoint": {"type": "placeholder", "placeholder_id": self.placeholder_id, "placeholder_port": port},
            "second_endpoint": {"type": "patch", "patch_panel_id": self.panel_id, "patch_port": patch_port},
        })

    def test_ports_take_cables_and_notes(self):
        page = self.client.get(f"/rack-change/{self.rack_id}?side=front").get_data(as_text=True)
        self.assertIn(f'id="placeholder-{self.placeholder_id}-port-24"', page)
        self.assertIn('data-endpoint-type="placeholder"', page)

        self.assertEqual(self.connect(25).status_code, 400)                  # no such port
        body = self.connect(1).get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(self.db().execute("SELECT cable_type FROM port_connections").fetchone()[0], "fiber")

        self.client.post("/rack/port/description", json={
            "endpoint": {"type": "placeholder", "placeholder_id": self.placeholder_id, "placeholder_port": 1},
            "description": "uplink to office"})
        page = self.client.get(f"/rack-change/{self.rack_id}?side=front").get_data(as_text=True)
        self.assertIn("Note: uplink to office", page)
        self.assertIn(f"placeholder-{self.placeholder_id}-port-1", page)           # the cable is drawn

        path = self.client.get(f"/rack/path?type=patch&id={self.panel_id}&port=21").get_json()
        self.assertEqual(path["endpoints"][0]["name"], "DEMON1")
        self.assertEqual(path["ends"][0], "device")

        lines = [line for e in self.services.rack_history.history()["entries"] for line in e["lines"]]
        self.assertIn("Cable added: DEMON1 p1 — ODF p21", lines)
        self.assertIn("Note on DEMON1 p1: (empty) → “uplink to office”", lines)

    def test_removing_the_temporary_switch_removes_its_cables(self):
        self.connect(1)
        self.client.post(f"/rack/{self.rack_id}/switch-placeholder/{self.placeholder_id}/delete", data={"side": "front"})
        self.assertEqual(self.db().execute("SELECT COUNT(*) FROM port_connections").fetchone()[0], 0)
        # ... and undo brings both back.
        entry = self.services.rack_history.history()["entries"][0]
        self.services.rack_history.undo(entry["id"])
        self.assertEqual(self.db().execute("SELECT COUNT(*) FROM port_connections").fetchone()[0], 1)
        self.assertEqual(self.db().execute("SELECT COUNT(*) FROM rack_switch_placeholders").fetchone()[0], 1)

    def test_removing_the_rack_removes_placeholder_cables(self):
        self.connect(1)
        self.client.post(f"/rack/{self.rack_id}/delete")
        self.assertEqual(self.db().execute("SELECT COUNT(*) FROM port_connections").fetchone()[0], 0)
