"""Sign-in: visitors may look but not change; signed-in users may change."""

import os
import sqlite3
import tempfile
import unittest

from flask.testing import FlaskClient

from Project import settings
from Project.bll.services.auth import LocalUsers, LoginThrottle, write_user
from Project.web import create_app
from tests import TEST_PASSWORD, TEST_USER, USERS_FILE
from tests.test_web import create_inventory_db


class AuthTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.app = create_app(self.db_path)
        # A visitor who has not signed in.
        self.app.test_client_class = FlaskClient
        self.client = self.app.test_client()
        self.client.get("/rack-change")             # tables exist

    def sign_in(self, client=None, password=TEST_PASSWORD):
        return (client or self.client).post("/login", data={
            "username": TEST_USER, "password": password, "next": "/rack-change",
        })

    def test_tests_use_their_own_files(self):
        self.assertEqual(settings.USERS_FILE, USERS_FILE)
        self.assertNotIn("config", settings.USERS_FILE)

    def test_visitor_can_view_every_page(self):
        for url in ("/", "/dashboard", "/switch/1", "/changes", "/changes/racks", "/checks",
                    "/rack", "/rack-change", "/floor-maps", "/login", "/api/version"):
            response = self.client.get(url, follow_redirects=True)
            self.assertEqual(response.status_code, 200, url)

    def test_visitor_never_gets_rack_change(self):
        signed_in = self.app.test_client()
        self.sign_in(signed_in)
        signed_in.post("/rack/server-room/create", data={"name": "Room X"})
        with sqlite3.connect(self.db_path) as connection:
            room_id = connection.execute("SELECT id FROM server_rooms WHERE name = 'Room X'").fetchone()[0]
        signed_in.post("/rack/create", data={"server_room_id": room_id, "name": "R1", "units": "42"})
        with sqlite3.connect(self.db_path) as connection:
            rack_id = connection.execute("SELECT id FROM racks WHERE name = 'R1'").fetchone()[0]

        # The editor's start page asks to sign in.
        response = self.client.get("/rack-change")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/rack-change", response.headers["Location"])

        # A rack in the editor opens in Rack View instead, at the same port.
        response = self.client.get(f"/rack-change/{rack_id}?side=rear&focus=switch-1-port-2")
        self.assertTrue(response.headers["Location"].endswith(f"/rack/{rack_id}?side=rear&focus=switch-1-port-2"))
        response = self.client.get(f"/rack/{rack_id}?side=rear&focus=switch-1-port-2")
        location = response.headers["Location"]
        self.assertIn("/rack?", location)
        for part in (f"room_id={room_id}", f"open={rack_id}", "side=rear", "focus=switch-1-port-2"):
            self.assertIn(part, location)
        page = self.client.get(f"/rack-change/{rack_id}", follow_redirects=True).get_data(as_text=True)
        self.assertIn("rack-dashboard-page", page)               # Rack View
        self.assertNotIn("Add Server Room", page)

        # A signed-in user gets the editor from the same link.
        response = signed_in.get(f"/rack/{rack_id}?side=rear&focus=switch-1-port-2")
        self.assertIn(f"/rack-change/{rack_id}?side=rear&focus=switch-1-port-2", response.headers["Location"])
        self.assertEqual(signed_in.get(f"/rack-change/{rack_id}").status_code, 200)

        # History rows: no Undo column for a visitor, the row opens Rack View.
        history = self.client.get("/changes/racks").get_data(as_text=True)
        self.assertNotIn("rack-history-undo", history)
        self.assertNotIn("<th></th>", history)
        self.assertNotIn("/rack-change", history)

    def test_editors_are_not_offered_to_visitors(self):
        # A change in the history, made by a signed-in user.
        signed_in = self.app.test_client()
        self.sign_in(signed_in)
        signed_in.post("/rack/server-room/create", data={"name": "Room X"})

        for client, can_edit in ((self.client, False), (signed_in, True)):
            home = client.get("/").get_data(as_text=True)
            history = client.get("/changes/racks").get_data(as_text=True)
            change = client.get("/rack-change", follow_redirects=True).get_data(as_text=True)
            rack_view = client.get("/rack", follow_redirects=True).get_data(as_text=True)
            checks = [
                ('href="/rack-change"' in home, "Rack Change in the menu / home page"),
                ("rack-history-undo" in history, "Undo in Rack History"),
                ("Add Server Room" in change, "Add Server Room"),
            ]
            for present, what in checks:
                self.assertEqual(present, can_edit, f"{what}: signed in = {can_edit}")
            self.assertEqual("Sign in to make changes" in rack_view or "sign in" in rack_view, not can_edit)

    def test_visitor_cannot_download_the_cable_journal(self):
        for url in ("/export/cable-journal.xlsx", "/export/cable-journal.csv", "/export/cable-journal.xlsx?switch_id=1"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login?next=/export/cable-journal", response.headers["Location"])
        for url in ("/checks", "/switch/1", "/"):
            self.assertNotIn("/export/cable-journal", self.client.get(url).get_data(as_text=True), url)

        signed_in = self.app.test_client()
        self.sign_in(signed_in)
        response = signed_in.get("/export/cable-journal.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
        self.assertIn("/export/cable-journal", signed_in.get("/checks").get_data(as_text=True))
        self.assertIn("/export/cable-journal", signed_in.get("/switch/1").get_data(as_text=True))

    def test_visitor_cannot_change_anything(self):
        requests = [
            ("post", "/rack/server-room/create", {"data": {"name": "Room X"}}),
            ("post", "/rack/connect", {"json": {}}),
            ("post", "/hosts/name", {"json": {"mac": "00:11:22:33:44:55", "name": "x"}}),
            ("post", "/ports/name", {"json": {"switch_id": 1, "port": 1, "name": "x"}}),
            ("post", "/changes/racks/1/undo", {}),
            ("post", "/floor-maps/api/maps", {"json": {"name": "M"}}),
            ("patch", "/floor-maps/api/maps/1", {"json": {"name": "M"}}),
            ("delete", "/floor-maps/api/maps/1", {}),
            ("post", "/rack/layout/reset", {"json": {}}),
        ]
        for method, url, kwargs in requests:
            response = getattr(self.client, method)(url, headers={"Accept": "application/json"}, **kwargs)
            self.assertEqual(response.status_code, 401, f"{method} {url}")
            self.assertEqual(response.headers.get("X-Login-Required"), "1")
            self.assertTrue(response.get_json()["login_required"])

        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM server_rooms WHERE name = 'Room X'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM host_names").fetchone()[0], 0)

    def test_plain_form_goes_to_the_login_page(self):
        response = self.client.post("/rack/server-room/create", data={"name": "Room X"},
                                    headers={"Referer": "http://localhost/rack-change?room_id=1"})
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login?next=/rack-change?room_id%3D1", response.headers["Location"])

    def test_htmx_gets_401(self):
        response = self.client.post("/rack/server-room/create", data={"name": "Room X"}, headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 401)

    def test_sign_in_and_change(self):
        response = self.sign_in()
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/rack-change"))

        page = self.client.get("/rack-change").get_data(as_text=True)
        self.assertIn('data-auth="1"', page)
        self.assertIn(TEST_USER, page)
        self.assertIn("Sign out", page)

        response = self.client.post("/rack/server-room/create", data={"name": "Room X"})
        self.assertIn(response.status_code, (200, 302, 303))
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM server_rooms WHERE name = 'Room X'").fetchone()[0], 1)
            who = connection.execute("SELECT actor_user FROM rack_audit ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(who, TEST_USER)
        self.assertIn(f'<b class="rack-history-user">{TEST_USER}</b>', self.client.get("/changes/racks").get_data(as_text=True))

        response = self.client.post("/logout", data={"next": "/rack"})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/rack"))
        self.assertEqual(self.client.post("/rack/connect", json={}).status_code, 401)

    def test_wrong_password(self):
        response = self.sign_in(password="nope")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Wrong user name or password", response.get_data(as_text=True))
        self.assertEqual(self.client.post("/rack/connect", json={}).status_code, 401)

    def test_too_many_failures_are_refused(self):
        for _ in range(LoginThrottle.LIMIT):
            self.sign_in(password="nope")
        response = self.sign_in()                    # even the right password
        self.assertEqual(response.status_code, 429)

    def test_next_stays_on_this_site(self):
        for target in ("https://evil.example/", "//evil.example/", "/\\evil.example", "javascript:alert(1)"):
            response = self.client.post("/login", data={"username": TEST_USER, "password": TEST_PASSWORD, "next": target})
            self.assertEqual(response.status_code, 303, target)
            self.assertNotIn("evil", response.headers["Location"])
            self.assertNotIn("javascript", response.headers["Location"])
            self.client.post("/logout")

    def test_changes_from_another_site_are_refused(self):
        self.sign_in()
        response = self.client.post("/rack/connect", json={}, headers={"Origin": "http://evil.example"})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/login", data={"username": TEST_USER, "password": TEST_PASSWORD},
                                    headers={"Origin": "http://evil.example"})
        self.assertEqual(response.status_code, 403)

    def test_new_password_ends_the_session(self):
        self.sign_in()
        self.assertIn('data-auth="1"', self.client.get("/").get_data(as_text=True))
        self.addCleanup(write_user, USERS_FILE, TEST_USER, TEST_PASSWORD)
        write_user(USERS_FILE, TEST_USER, "another-password")
        self.assertIn('data-auth="0"', self.client.get("/").get_data(as_text=True))


class LocalUsersTest(unittest.TestCase):

    def test_file_and_passwords(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "users")
        self.addCleanup(lambda: (os.path.exists(path) and os.unlink(path), os.rmdir(directory)))
        users = LocalUsers(path)
        self.assertIsNone(users.authenticate("admin", "admin"))      # no file: nobody

        write_user(path, "admin", "admin")
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o640")
        self.assertEqual(users.authenticate("admin", "admin"), "admin")
        self.assertIsNone(users.authenticate("admin", "wrong"))
        self.assertIsNone(users.authenticate("admin", ""))
        self.assertIsNone(users.authenticate("other", "admin"))
        def text():
            with open(path, encoding="utf-8") as handle:
                return handle.read()

        self.assertNotIn("admin:admin", text())                        # only the hash

        before = users.fingerprint("admin")
        write_user(path, "admin", "new")
        self.assertNotEqual(users.fingerprint("admin"), before)
        self.assertEqual(len([line for line in text().splitlines() if line.startswith("admin:")]), 1)
        with self.assertRaises(ValueError):
            write_user(path, "a:b", "x")

    def test_throttle(self):
        now = [0.0]
        throttle = LoginThrottle(clock=lambda: now[0])
        for _ in range(LoginThrottle.LIMIT):
            throttle.failed("ip")
        self.assertTrue(throttle.blocked("ip"))
        self.assertFalse(throttle.blocked("other"))
        now[0] += LoginThrottle.WINDOW
        self.assertFalse(throttle.blocked("ip"))


if __name__ == "__main__":
    unittest.main()
