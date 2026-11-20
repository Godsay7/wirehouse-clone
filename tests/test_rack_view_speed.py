"""Rack View loads fast: front pictures by URL (cached), text gzipped."""

import gzip
import os
import sqlite3
import tempfile
import unittest

from Project.web import create_app
from tests.test_web import create_inventory_db

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000100e221bc330000000049454e44ae426082"
)


class RackViewSpeedTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.app = create_app(self.db_path)
        self.client = self.app.test_client()
        services = self.app.extensions["services"]
        self.client.post("/rack/server-room/create", data={"name": "Room"})
        db = sqlite3.connect(self.db_path)
        self.room_id = db.execute("SELECT id FROM server_rooms").fetchone()[0]
        self.client.post("/rack/create", data={"name": "R1", "server_room_id": self.room_id})
        rack_id = db.execute("SELECT id FROM racks").fetchone()[0]
        services.rack_equipment.add_server(rack_id, "Srv", 40, 2, 1, "front", "full")
        self.server_id = db.execute("SELECT id FROM servers").fetchone()[0]
        db.close()
        services.rack_equipment.set_server_front_image(self.server_id, PNG, "image/png")

    def test_front_picture_is_a_cached_url(self):
        page = self.client.get(f"/rack?room_id={self.room_id}").get_data(as_text=True)
        self.assertNotIn("data:image", page)
        self.assertIn(f"/rack/server/{self.server_id}/front-image?v=", page)

        url = page.split(f'/rack/server/{self.server_id}/front-image?v=')[1].split('"')[0]
        response = self.client.get(f"/rack/server/{self.server_id}/front-image?v={url}")
        self.assertEqual((response.status_code, response.mimetype), (200, "image/png"))
        self.assertEqual(response.get_data(), PNG)
        self.assertIn("immutable", response.headers["Cache-Control"])

        # A new picture gets a new URL; no picture: no image, 404 for the URL.
        services = self.app.extensions["services"]
        services.rack_equipment.set_server_front_image(self.server_id, PNG + b"x", "image/png")
        self.assertNotIn(url, self.client.get(f"/rack?room_id={self.room_id}").get_data(as_text=True))
        services.rack_equipment.remove_server_front_image(self.server_id)
        self.assertNotIn("front-image", self.client.get(f"/rack?room_id={self.room_id}").get_data(as_text=True))
        self.assertEqual(self.client.get(f"/rack/server/{self.server_id}/front-image").status_code, 404)

    def test_text_is_gzipped_when_accepted(self):
        plain = self.client.get(f"/rack?room_id={self.room_id}")
        self.assertNotIn("Content-Encoding", plain.headers)
        packed = self.client.get(f"/rack?room_id={self.room_id}", headers={"Accept-Encoding": "gzip, deflate, br"})
        self.assertEqual(packed.headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", packed.headers["Vary"])
        self.assertEqual(gzip.decompress(packed.get_data()), plain.get_data())

        script = self.client.get("/static/js/rack_view.js", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(script.headers.get("Content-Encoding"), "gzip")
        picture = self.client.get(f"/rack/server/{self.server_id}/front-image", headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("Content-Encoding", picture.headers)


if __name__ == "__main__":
    unittest.main()
