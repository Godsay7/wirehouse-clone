"""Rack change history (who / what / undo) and the confirmation before replacing a cable."""

import os
import sqlite3
import tempfile
import unittest

from Project.web import create_app
from tests.test_web import create_inventory_db


class RackHistoryTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.app = create_app(self.db_path)
        # A browser on a PC whose name the core ARP table knows.
        self.client = self.app.test_client()
        self.client.environ_base["REMOTE_ADDR"] = "10.0.0.55"
        self.history = self.app.extensions["services"].rack_history

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

    def connect(self, switch_port, patch_port, replace=None):
        body = {
            "first_endpoint": {"type": "switch", "switch_id": 1, "switch_port": switch_port},
            "second_endpoint": {"type": "patch", "patch_panel_id": self.panel_id, "patch_port": patch_port},
        }
        if replace is not None:
            body["replace"] = replace
        return self.client.post("/rack/connect", json=body)

    def cables(self):
        return self.db().execute(
            "SELECT endpoint_a_port, endpoint_b_port FROM port_connections ORDER BY id").fetchall()

    # ---------------- rack width ----------------

    def test_narrow_rack(self):
        page = lambda: self.client.get(f"/rack-change/{self.rack_id}").get_data(as_text=True)
        self.assertNotIn("data-rack-width", page())
        self.client.post(f"/rack/{self.rack_id}/width", data={"width_percent": "33", "side": "front"})
        html = page()
        self.assertIn('data-rack-width="33"', html)
        self.assertIn("--rack-width: 0.33", html)
        self.assertEqual(self.db().execute("SELECT width_percent FROM racks").fetchone()[0], 33)
        self.assertIn('data-rack-width="33"', self.client.get("/rack").get_data(as_text=True))   # Rack View too

        # Only the offered widths; the change is in Rack History and can be undone.
        self.client.post(f"/rack/{self.rack_id}/width", data={"width_percent": "40", "side": "front"})
        self.assertEqual(self.db().execute("SELECT width_percent FROM racks").fetchone()[0], 33)
        entry = self.history.history()["entries"][0]
        self.history.undo(entry["id"])
        self.assertEqual(self.db().execute("SELECT width_percent FROM racks").fetchone()[0], 100)

    # ---------------- optical ports of a switch ----------------

    def test_switch_optical_ports_after_a_gap_with_own_numbers(self):
        connection = self.db()
        connection.executescript("""
            INSERT INTO ports (switch_id, port, device, speed, link, mac, if_index, if_name, last_seen)
            VALUES (1, 3, '-', '1G', 'UP', '-', 10103, 'Gi1/0/3', '2026-10-12T10:00:00'),
                   (1, 4, '-', '1G', 'UP', '-', 10104, 'Gi1/0/4', '2026-10-12T10:00:00'),
                   (1, 5, '-', '10G', 'UP', '-', 10105, 'Te1/1/1', '2026-10-12T10:00:00'),
                   (1, 6, '-', '10G', 'DOWN', '-', 10106, 'Te1/1/2', '2026-10-12T10:00:00');
        """)
        connection.commit()
        html = self.client.get(f"/rack-change/{self.rack_id}").get_data(as_text=True)
        self.assertIn("rack-switch-port-gap", html)
        # The id stays the port number (cables find it); the label is Te1 / Te2.
        self.assertRegex(html, r'id="switch-1-port-5"\s+class="[^"]*switch-port-optical[^"]*"[\s\S]*?>Te1</div>')
        self.assertRegex(html, r'id="switch-1-port-6"\s+class="[^"]*switch-port-optical[^"]*"[\s\S]*?>Te2</div>')
        self.assertRegex(html, r'id="switch-1-port-3"\s+class="rack-port switch-port link-up"[\s\S]*?>3</div>')

    # ---------------- port layout of a patch panel ----------------

    def test_patch_panel_ports_odd_on_top_even_below(self):
        page = lambda: self.client.get(f"/rack-change/{self.rack_id}").get_data(as_text=True)
        self.assertNotIn("rack-patch-ports-odd-even", page())
        self.client.post(f"/rack/{self.rack_id}/patch-panel/{self.panel_id}/layout?side=front",
                         data={"port_layout": "odd_even"})
        html = page()
        self.assertIn("rack-patch-ports-odd-even", html)
        # Odd ports are the top row (their cables leave upwards), even ones are not.
        self.assertRegex(html, r'id="patch-%d-port-1"\s+class="[^"]*patch-port-top' % self.panel_id)
        self.assertNotRegex(html, r'id="patch-%d-port-2"\s+class="[^"]*patch-port-top' % self.panel_id)
        entry = self.history.history()["entries"][0]
        self.assertTrue(any("port layout row → odd_even" in line for line in entry["lines"]))

        # Unknown layouts are refused; undo brings the row back.
        self.client.post(f"/rack/{self.rack_id}/patch-panel/{self.panel_id}/layout?side=front", data={"port_layout": "x"})
        self.assertEqual(self.db().execute("SELECT port_layout FROM patch_panels").fetchone()[0], "odd_even")
        self.history.undo(entry["id"])
        self.assertEqual(self.db().execute("SELECT port_layout FROM patch_panels").fetchone()[0], "row")

    # ---------------- item 3: no silent cable replacement ----------------

    def test_replacing_a_cable_needs_confirmation(self):
        self.assertTrue(self.connect(1, 3).get_json()["ok"])
        self.assertTrue(self.connect(1, 3).get_json()["ok"])            # the same cable again: no-op
        self.assertEqual(self.cables(), [(1, 3)])

        response = self.connect(1, 4)
        self.assertEqual(response.status_code, 409)
        body = response.get_json()
        self.assertTrue(body["needs_confirm"])
        self.assertEqual(body["conflicts"], ["SW-A Gi1/0/1 is connected to PP1 Port 3"])
        self.assertEqual(self.cables(), [(1, 3)])                         # nothing changed

        self.assertTrue(self.connect(1, 4, replace=True).get_json()["ok"])
        self.assertEqual(self.cables(), [(1, 4)])

    # ---------------- item 2: history and undo ----------------

    def test_history_says_who_and_what(self):
        self.connect(1, 3)
        self.client.post("/rack/port/description", json={
            "endpoint": {"type": "patch", "patch_panel_id": self.panel_id, "patch_port": 3}, "description": "socket 2-19"})

        entries = self.history.history()["entries"]
        self.assertEqual(entries[0]["lines"], ["Note on PP1 p3: (empty) → “socket 2-19”"])
        self.assertEqual(entries[1]["lines"], ["Cable added: SW-A Gi1/0/1 — PP1 p3"])
        self.assertEqual(entries[2]["lines"], ["Patch panel added: PP1 (Room / R1, U40 front)"])   # not 8 port lines
        self.assertEqual(entries[0]["who"], "pc-1.local (10.0.0.55)")
        self.assertEqual(entries[0]["action"], "POST /rack/port/description")

        page = self.client.get("/changes/racks").get_data(as_text=True)
        self.assertIn("Cable added: SW-A Gi1/0/1 — PP1 p3", page)
        self.assertIn("pc-1.local (10.0.0.55)", page)

    def test_undo_removed_panel_brings_back_ports_cables_and_notes(self):
        self.connect(1, 3)
        self.client.post("/rack/port/description", json={
            "endpoint": {"type": "patch", "patch_panel_id": self.panel_id, "patch_port": 3}, "description": "socket 2-19"})
        before = [self.db().execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
                  for t in ("patch_panels", "patch_ports", "port_connections")]

        self.client.post(f"/rack/{self.rack_id}/patch-panel/{self.panel_id}/delete?side=front")
        entry = self.history.history()["entries"][0]
        self.assertIn("Cable removed: SW-A Gi1/0/1 — PP1 p3", entry["lines"])

        response = self.client.post(f"/changes/racks/{entry['id']}/undo")
        self.assertIn("undone", response.headers["Location"])
        after = [self.db().execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
                 for t in ("patch_panels", "patch_ports", "port_connections")]
        self.assertEqual(before, after)                                   # same rows, same ids

        entries = self.history.history()["entries"]
        self.assertEqual(entries[0]["action"], f"Undo #{entry['id']}")
        self.assertEqual(entries[1]["undone_by"], entries[0]["id"])
        self.assertFalse(entries[1]["can_undo"])

        # Undo of the undo removes the panel again.
        self.history.undo(entries[0]["id"])
        self.assertEqual(self.db().execute("SELECT COUNT(*) FROM patch_panels").fetchone()[0], 0)

    def test_undo_is_refused_when_changed_later(self):
        self.connect(1, 3)
        cable_entry = self.history.history()["entries"][0]["id"]
        self.connect(1, 5, replace=True)                                  # the cable was changed again

        response = self.client.post(f"/changes/racks/{cable_entry}/undo")
        self.assertIn("Cannot+undo", response.headers["Location"])
        self.assertEqual(self.cables(), [(1, 5)])

    def test_note_undo_and_collector_writes_are_not_recorded(self):
        self.client.post("/rack/port/description", json={
            "endpoint": {"type": "switch", "switch_id": 1, "switch_port": 2}, "description": "uplink"})
        entry = self.history.history()["entries"][0]
        self.assertEqual(entry["lines"], ["Note on SW-A Gi1/0/2: (empty) → “uplink”"])

        # The collector updating the same port must not show up nor block the undo.
        connection = self.db()
        connection.execute("UPDATE ports SET link = 'UP', device = 'x' WHERE switch_id = 1 AND port = 2")
        connection.commit()
        count = len(self.history.history()["entries"])

        self.history.undo(entry["id"])
        self.assertIsNone(self.db().execute("SELECT description FROM ports WHERE switch_id = 1 AND port = 2").fetchone()[0])
        self.assertEqual(len(self.history.history()["entries"]), count + 1)

    def test_failed_change_leaves_no_entry(self):
        count = len(self.history.history()["entries"])
        self.client.post(f"/rack/{self.rack_id}/patch-panel/add", data={"name": "PP2", "rack_unit": 40})   # U40 taken
        self.assertEqual(len(self.history.history()["entries"]), count)

    def test_history_rows_open_where_the_change_was_made(self):
        self.connect(1, 3)
        page = self.client.get("/changes/racks").get_data(as_text=True)
        # Cable: Rack Change of that rack, at the switch port.
        self.assertIn(f'data-href="/rack-change/{self.rack_id}?side=front&amp;focus=switch-1-port-1"', page)
        # Rack added: the rack itself; server room added: its Rack View board.
        self.assertIn(f'data-href="/rack-change/{self.rack_id}?side=front"', page)
        room_id = self.db().execute("SELECT id FROM server_rooms").fetchone()[0]
        self.assertIn(f'data-href="/rack?room_id={room_id}"', page)
        # The Undo button stays a button inside a clickable row.
        self.assertIn('class="button secondary rack-history-undo"', page)

    def test_client_address_behind_the_local_nginx(self):
        def who_after_note(remote, header):
            client = self.app.test_client()
            client.environ_base["REMOTE_ADDR"] = remote
            headers = {"X-Real-IP": header} if header else {}
            client.post("/rack/port/description", headers=headers, json={
                "endpoint": {"type": "switch", "switch_id": 1, "switch_port": 2}, "description": f"{remote}-{header}"})
            return self.history.history()["entries"][0]["who"]

        # Through nginx on this server: the real browser address.
        self.assertEqual(who_after_note("127.0.0.1", "10.0.0.55"), "pc-1.local (10.0.0.55)")
        # A script on the server itself, without nginx.
        self.assertEqual(who_after_note("127.0.0.1", None), "this server (script)")
        # Another machine cannot pretend to be someone else.
        self.assertEqual(who_after_note("10.9.9.9", "10.0.0.55"), "10.9.9.9")

