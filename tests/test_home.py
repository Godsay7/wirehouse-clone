"""Home page: freshness, the errors tile, search suggestions."""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from Project.bll.domain.freshness import freshness
from Project.web import create_app
from tests.test_web import create_inventory_db

class FreshnessTest(unittest.TestCase):

    def test_freshness(self):
        self.assertEqual([freshness(m) for m in (3, 12, 45, None)], ["fresh", "late", "stale", "unknown"])


class HomeWebTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "INSERT INTO port_error_events (switch_id, port, detected_at, in_errors, out_errors, fcs_errors) VALUES (1, 1, ?, 0, 0, 40)",
            (recent,))
        connection.commit()
        connection.close()
        self.client = create_app(self.db_path).test_client()

    def test_home_is_search_tiles_and_sections_only(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('href="/dashboard?errors=1"', page)          # the "Ports with errors" tile
        self.assertIn("errors grew in the last 24 h", page)
        for gone in ("Needs attention", "Choose a rack", "Cable journal", "Recent rack changes", "Recent port changes"):
            self.assertNotIn(gone, page)
        # Every page of a section is a button with its description as a tooltip
        # (signed in: Rack Change and the cable checklist among them).
        self.assertEqual(page.count('class="home-sub"'), 8)
        self.assertIn('role="tooltip"', page)

    def test_errors_list_on_the_dashboard(self):
        page = self.client.get("/dashboard?errors=1").get_data(as_text=True)
        self.assertIn("Ports whose error counters grew", page)
        self.assertIn("Gi1/0/1", page)

    def test_suggestions(self):
        data = self.client.get("/search/suggest?q=pc-1").get_json()
        labels = [item["label"] for item in data["items"]]
        self.assertIn("SW-A Gi1/0/1", labels)
        self.assertTrue(data["items"][0]["href"].startswith("/switch/1"))
        self.assertTrue(data["all"].startswith("/dashboard?search="))
        self.assertEqual(self.client.get("/search/suggest?q=p").get_json()["items"], [])


if __name__ == "__main__":
    unittest.main()
