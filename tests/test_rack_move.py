"""Rack Change: drag a switch (or a temporary switch) to another unit; its cables stay."""

import os
import sqlite3
import tempfile
import unittest

from flask.testing import FlaskClient

from Project.web import create_app
from tests.test_web import create_inventory_db


class RackMoveTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.app = create_app(self.db_path)
        self.client = self.app.test_client()

        self.client.post("/rack/server-room/create", data={"name": "Room"})
        room_id = self.one("SELECT id FROM server_rooms")
        self.client.post("/rack/create", data={"name": "R1", "server_room_id": room_id, "units": 42})
        self.rack_id = self.one("SELECT id FROM racks")
        # SW-A (1U) at U40, a patch panel at U38, a cable SW-A p1 <-> PP p3.
        self.client.post(f"/rack/{self.rack_id}/switch/add", data={"switch_id": 1, "rack_unit": 40})
        self.client.post(f"/rack/{self.rack_id}/patch-panel/add", data={"name": "PP1", "rack_unit": 38, "port_count": 24})
        panel_id = self.one("SELECT id FROM patch_panels")
        response = self.client.post("/rack/connect", json={
            "first_endpoint": {"type": "switch", "switch_id": 1, "switch_port": 1},
            "second_endpoint": {"type": "patch", "patch_panel_id": panel_id, "patch_port": 3},
        })
        self.assertTrue(response.get_json()["ok"], response.get_json())

    def one(self, query, params=()):
        with sqlite3.connect(self.db_path) as connection:
            return connection.execute(query, params).fetchone()[0]

    def move(self, top, client=None, url=None):
        return (client or self.client).post(url or f"/rack/{self.rack_id}/switch/1/move", json={"rack_unit": top})

    def test_switch_moves_and_keeps_its_cables(self):
        cables_before = self.one("SELECT COUNT(*) FROM port_connections")
        response = self.move(30)
        self.assertEqual(response.get_json(), {"ok": True})
        self.assertEqual(self.one("SELECT rack_unit FROM rack_switches WHERE switch_id = 1"), 30)
        self.assertEqual(self.one("SELECT COUNT(*) FROM port_connections"), cables_before)

        # The editor draws it at U30 with its cable, and marks the units for dragging.
        page = self.client.get(f"/rack-change/{self.rack_id}").get_data(as_text=True)
        self.assertIn('data-unit="30" data-device="switch-1"', page)
        self.assertIn(f'data-move-url="/rack/{self.rack_id}/switch/1/move"', page)
        self.assertIn("js/rack_move.js", page)

        # Rack History: "moved", and Undo puts it back.
        history = self.app.extensions["services"].rack_history.history()["entries"]
        self.assertIn("moved", " ".join(history[0]["lines"]))
        self.client.post(f"/changes/racks/{history[0]['id']}/undo")
        self.assertEqual(self.one("SELECT rack_unit FROM rack_switches WHERE switch_id = 1"), 40)

    def test_refused_places(self):
        # Onto the patch panel, outside the rack, to its own place (allowed: nothing changes).
        response = self.move(38)
        self.assertEqual(response.status_code, 400)
        self.assertIn("U38 is already occupied on the front side", response.get_json()["error"])
        self.assertEqual(self.move(43).status_code, 400)
        self.assertIn("outside the rack", self.move(0).get_json()["error"])
        self.assertEqual(self.move(40).get_json(), {"ok": True})
        self.assertEqual(self.one("SELECT rack_unit FROM rack_switches WHERE switch_id = 1"), 40)
        # A switch that is not in this rack; a bad unit.
        self.assertEqual(self.move(20, url=f"/rack/{self.rack_id}/switch/2/move").status_code, 404)
        self.assertEqual(self.client.post(f"/rack/{self.rack_id}/switch/1/move", json={"rack_unit": "x"}).status_code, 400)

    def test_two_unit_switch(self):
        # The 4900M is 2U: at top U37 it would take U36-U37; U38 holds the panel.
        self.client.post(f"/rack/{self.rack_id}/switch/add", data={"switch_id": 2, "rack_unit": 20})
        url = f"/rack/{self.rack_id}/switch/2/move"
        self.assertEqual(self.move(39, url=url).status_code, 400)       # U38-U39: the panel is at U38
        self.assertEqual(self.move(1, url=url).status_code, 400)        # U0-U1: outside the rack
        self.assertEqual(self.move(21, url=url).get_json(), {"ok": True})  # overlaps its own U20: fine
        self.assertEqual(self.one("SELECT rack_unit FROM rack_switches WHERE switch_id = 2"), 21)

    def test_temporary_switch(self):
        self.client.post(f"/rack/{self.rack_id}/switch-placeholder/add",
                         data={"name": "Temp", "rack_unit": 10, "height_units": 1, "port_count": 8})
        placeholder_id = self.one("SELECT id FROM rack_switch_placeholders")
        url = f"/rack/{self.rack_id}/switch-placeholder/{placeholder_id}/move"
        self.assertEqual(self.move(12, url=url).get_json(), {"ok": True})
        self.assertEqual(self.one("SELECT rack_unit FROM rack_switch_placeholders"), 12)
        self.assertEqual(self.move(40, url=url).status_code, 400)       # SW-A is there

    def add_server(self, name, top, height, side="front", depth="full"):
        self.client.post(f"/rack/{self.rack_id}/server/add", data={
            "name": name, "rack_unit": top, "height_units": height, "port_count": 2, "side": side, "depth": depth})
        return self.one("SELECT id FROM servers WHERE name = ?", (name,))

    def test_patch_panel_moves_with_its_cable(self):
        panel_id = self.one("SELECT id FROM patch_panels")
        url = f"/rack/{self.rack_id}/patch-panel/{panel_id}/move"
        self.assertEqual(self.move(20, url=url).get_json(), {"ok": True})
        self.assertEqual(self.one("SELECT rack_unit FROM patch_panels"), 20)
        self.assertEqual(self.one("SELECT COUNT(*) FROM port_connections"), 1)     # SW-A p1 <-> PP1 p3 stays
        self.assertEqual(self.move(40, url=url).status_code, 400)                  # SW-A is at U40
        page = self.client.get(f"/rack-change/{self.rack_id}").get_data(as_text=True)
        self.assertIn(f'data-unit="20" data-device="patch_panel-{panel_id}"', page)
        self.assertIn(f'data-move-url="{url}"', page)
        lines = " ".join(self.app.extensions["services"].rack_history.history()["entries"][0]["lines"])
        self.assertIn("unit 38", lines)

    def test_server_moves_by_its_top_unit(self):
        server_id = self.add_server("SRV", top=12, height=2)          # U11-U12
        self.assertEqual(self.one("SELECT rack_unit FROM servers"), 11)  # stored by its bottom U
        url = f"/rack/{self.rack_id}/server/{server_id}/move"
        self.assertEqual(self.move(13, url=url).get_json(), {"ok": True})   # U12-U13, overlaps itself
        self.assertEqual(self.one("SELECT rack_unit FROM servers"), 12)
        self.assertEqual(self.move(1, url=url).status_code, 400)           # U0-U1: outside
        page = self.client.get(f"/rack-change/{self.rack_id}").get_data(as_text=True)
        self.assertIn('data-move-top="13" data-move-height="2" data-move-name="SRV"', page)

    def test_full_depth_server_needs_both_sides(self):
        server_id = self.add_server("FULL", top=10, height=1)
        rear_id = self.add_server("REAR", top=5, height=1, side="rear", depth="half")
        url = f"/rack/{self.rack_id}/server/{server_id}/move"
        response = self.move(5, url=url)                                    # front is free, rear is not
        self.assertEqual(response.status_code, 400)
        self.assertIn("rear side", response.get_json()["error"])
        # A half-depth server only needs its own side: the rear one can go under SW-A's U40 on the rear.
        self.assertEqual(self.move(40, url=f"/rack/{self.rack_id}/server/{rear_id}/move").get_json(), {"ok": True})

    def test_cable_organizer(self):
        self.client.post(f"/rack/{self.rack_id}/cable-organizer/add",
                         data={"name": "ORG", "rack_unit": 20, "height_units": 2})      # U20-U21
        organizer_id = self.one("SELECT id FROM cable_organizers")
        self.assertEqual(self.one("SELECT rack_unit FROM cable_organizers"), 20)       # stored by its bottom U
        url = f"/rack/{self.rack_id}/cable-organizer/{organizer_id}/move"
        page = self.client.get(f"/rack-change/{self.rack_id}").get_data(as_text=True)
        self.assertIn(f'data-move-key="cable_organizer-{organizer_id}" data-move-top="21" data-move-height="2"', page)
        self.assertEqual(page.count(f'data-move-key="cable_organizer-{organizer_id}"'), 1)   # only the top block

        self.assertEqual(self.move(22, url=url).get_json(), {"ok": True})              # U21-U22: overlaps itself
        self.assertEqual(self.one("SELECT rack_unit FROM cable_organizers"), 21)
        self.assertEqual(self.move(39, url=url).status_code, 400)                      # U38 holds the patch panel
        self.assertEqual(self.move(1, url=url).status_code, 400)                       # U0-U1: outside
        self.assertIn("unit 20", " ".join(self.app.extensions["services"].rack_history.history()["entries"][0]["lines"]))

    def test_visitor_cannot_move(self):
        self.app.test_client_class = FlaskClient
        visitor = self.app.test_client()
        response = self.move(30, client=visitor)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.one("SELECT rack_unit FROM rack_switches WHERE switch_id = 1"), 40)


if __name__ == "__main__":
    unittest.main()
