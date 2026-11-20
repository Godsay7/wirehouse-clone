"""UTC storage, Kyiv display and the one-time migration."""

import importlib.util
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from Project.core.text import format_datetime, now_iso, parse_timestamp

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "migrate_timestamps_to_utc",
        os.path.join(REPO, "scripts", "migrate_timestamps_to_utc.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TimeHelpersTest(unittest.TestCase):

    def test_now_iso_is_utc_with_offset(self):
        value = now_iso()
        self.assertRegex(value, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertLess(abs((datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds()), 5)

    def test_display_in_kyiv_summer_and_winter(self):
        self.assertEqual(format_datetime("2026-10-14T14:45:59+00:00"), "2026-10-14 17:45:59")  # EEST +3
        self.assertEqual(format_datetime("2026-12-01T10:00:00+00:00"), "2026-12-01 12:00:00")  # EET +2

    def test_repeated_hour_on_dst_end_keeps_order(self):
        # 25.10.2026: 04:00 EEST -> 03:00 EET, so 03:xx local happens twice.
        first = "2026-10-25T00:30:00+00:00"   # 03:30 EEST
        second = "2026-10-25T01:30:00+00:00"  # 03:30 EET
        self.assertEqual(format_datetime(first), format_datetime(second))
        self.assertLess(first, second)  # stored values still sort correctly

    def test_legacy_local_values_are_shown_unchanged(self):
        self.assertEqual(format_datetime("2026-10-14T17:45:59"), "2026-10-14 17:45:59")
        self.assertEqual(parse_timestamp("2026-10-14T17:45:59").utcoffset().total_seconds(), 3 * 3600)

    def test_empty_and_garbage(self):
        self.assertEqual(format_datetime(None), "-")
        self.assertEqual(format_datetime("garbageTvalue"), "garbage value")


class MigrationTest(unittest.TestCase):

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.path)
        connection = sqlite3.connect(self.path)
        connection.executescript(
            """
            CREATE TABLE port_history (id INTEGER PRIMARY KEY, collected_at TEXT);
            CREATE TABLE racks (id INTEGER PRIMARY KEY, created_at TEXT);
            INSERT INTO port_history (collected_at) VALUES
                ('2026-10-14T17:45:59'),           -- summer, local
                ('2026-02-01T12:00:00'),           -- winter, local
                ('2026-10-14T14:50:00+00:00');     -- already UTC (new collector)
            INSERT INTO racks (created_at) VALUES ('2026-08-27T13:26:56'), (NULL);
            """
        )
        connection.commit()
        connection.close()
        self.migration = load_migration()

    def values(self, table, column):
        connection = sqlite3.connect(self.path)
        try:
            return [row[0] for row in connection.execute(f"SELECT {column} FROM {table} ORDER BY id")]
        finally:
            connection.close()

    def run_migration(self, to_local=False):
        connection = sqlite3.connect(self.path)
        try:
            if to_local:
                return self.migration.migrate(connection, self.migration.utc_to_local, "{column} LIKE '%+00:00'")
            return self.migration.migrate(connection, self.migration.local_to_utc, "{column} NOT LIKE '%+%' AND {column} NOT LIKE '%Z'")
        finally:
            connection.close()

    def test_converts_only_local_values_and_is_idempotent(self):
        changed = self.run_migration()
        self.assertEqual(changed["port_history.collected_at"], 2)
        self.assertEqual(self.values("port_history", "collected_at"), [
            "2026-10-14T14:45:59+00:00",
            "2026-02-01T10:00:00+00:00",
            "2026-10-14T14:50:00+00:00",
        ])
        self.assertEqual(self.values("racks", "created_at"), ["2026-08-27T10:26:56+00:00", None])

        again = self.run_migration()
        self.assertEqual(sum(again.values()), 0)

    def test_undo(self):
        self.run_migration()
        self.run_migration(to_local=True)
        self.assertEqual(self.values("port_history", "collected_at"), [
            "2026-10-14T17:45:59",
            "2026-02-01T12:00:00",
            "2026-10-14T17:50:00",
        ])


class CollectorWritesUtcTest(unittest.TestCase):

    def test_saved_switch_uses_utc(self):
        from Project.collector import storage

        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, path)
        connection = storage.init_database(path)
        self.addCleanup(connection.close)

        port = {"Port": 1, "Device": "pc", "Speed": "1G", "Link": "UP", "MAC": "-", "_ifIndex": 1, "_ifName": "Gi1/0/1"}
        storage.save_switch_to_database(connection, "SW", [port])

        for (value,) in connection.execute("SELECT last_seen FROM switches UNION ALL SELECT collected_at FROM port_history"):
            self.assertTrue(re.search(r"\+00:00$", value), value)


if __name__ == "__main__":
    unittest.main()
