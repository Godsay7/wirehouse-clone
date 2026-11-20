"""Backups: copy, verify, rotate, copy to a second place, restore."""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

from Project.ops import backup

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_database(path, rooms=("Room A",)):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE server_rooms (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0, updated_at TEXT)")
    connection.executemany("INSERT INTO server_rooms (name) VALUES (?)", [(room,) for room in rooms])
    connection.execute("INSERT INTO app_state (key, value) VALUES ('rack', 5), ('inventory', 40)")
    connection.commit()
    return connection


class RetentionTest(unittest.TestCase):

    def test_keeps_daily_weekly_monthly(self):
        start = datetime(2026, 1, 1, 2, 30)
        timestamps = [start + timedelta(days=day) for day in range(200)]
        # Two runs on the last day: only the newer one of that day is needed.
        timestamps.append(timestamps[-1] + timedelta(hours=3))

        keep = backup.backups_to_keep(timestamps, backup.RetentionPolicy(daily=3, weekly=2, monthly=2))
        newest = max(timestamps)

        self.assertIn(newest, keep)
        days = {ts.date() for ts in keep}
        self.assertTrue({(newest - timedelta(days=d)).date() for d in range(3)} <= days)
        self.assertLessEqual(len(keep), 3 + 2 + 2)
        self.assertNotIn(min(timestamps), keep)

    def test_rotate_deletes_only_backup_files(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        for day in range(1, 6):
            open(os.path.join(directory, f"switch_inventory-2026-10-0{day}_023000.db.zst"), "w").close()
        open(os.path.join(directory, "notes.txt"), "w").close()

        deleted = backup.rotate(directory, backup.RetentionPolicy(daily=2, weekly=0, monthly=0))

        self.assertEqual(len(deleted), 3)
        self.assertEqual(sorted(os.listdir(directory)), [
            "notes.txt",
            "switch_inventory-2026-10-04_023000.db.zst",
            "switch_inventory-2026-10-05_023000.db.zst",
        ])


class BackupRestoreTest(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work)
        self.db_path = os.path.join(self.work, "live.db")
        self.backup_dir = os.path.join(self.work, "backups")
        self.live = make_database(self.db_path)
        self.addCleanup(self.live.close)

    def test_backup_includes_uncheckpointed_wal_data(self):
        self.live.execute("INSERT INTO server_rooms (name) VALUES ('Only in WAL')")
        self.live.commit()

        path = backup.create_backup(self.db_path, self.backup_dir, now=datetime(2026, 10, 14, 2, 30))

        self.assertTrue(path.endswith("switch_inventory-2026-10-14_023000.db.zst") or path.endswith(".db.gz"))
        restored = os.path.join(self.work, "check.db")
        backup.decompress_to(path, restored)
        rooms = [row[0] for row in sqlite3.connect(restored).execute("SELECT name FROM server_rooms")]
        self.assertEqual(rooms, ["Room A", "Only in WAL"])
        self.assertEqual([name for name in os.listdir(self.backup_dir) if name.startswith(".tmp")], [])

    def test_same_second_does_not_overwrite(self):
        moment = datetime(2026, 10, 14, 2, 30)
        first = backup.create_backup(self.db_path, self.backup_dir, now=moment)
        second = backup.create_backup(self.db_path, self.backup_dir, now=moment)
        self.assertNotEqual(first, second)
        self.assertEqual(len(backup.list_backups(self.backup_dir)), 2)

    def test_copy_to_missing_target_fails(self):
        path = backup.create_backup(self.db_path, self.backup_dir)
        with self.assertRaises(backup.BackupError):
            backup.copy_to(path, os.path.join(self.work, "not-mounted"))

    def test_restore_while_connection_is_open(self):
        path = backup.create_backup(self.db_path, self.backup_dir)
        self.live.execute("DELETE FROM server_rooms")
        self.live.commit()

        backup.restore_backup(path, self.db_path)

        rooms = [row[0] for row in self.live.execute("SELECT name FROM server_rooms")]
        self.assertEqual(rooms, ["Room A"])
        self.assertEqual(self.live.execute("PRAGMA journal_mode").fetchone()[0], "wal")


class ScriptsTest(unittest.TestCase):

    def run_script(self, *args, env=None):
        return subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts", args[0]), *args[1:]],
            capture_output=True, text=True, env={**os.environ, **(env or {})},
        )

    def test_backup_and_restore_scripts(self):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work)
        db_path = os.path.join(work, "live.db")
        local_dir = os.path.join(work, "local")
        remote_dir = os.path.join(work, "remote")
        os.makedirs(remote_dir)
        make_database(db_path).close()

        result = self.run_script("backup_db.py", "--db", db_path, "--dir", local_dir, "--remote-dir", remote_dir)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(backup.list_backups(local_dir)), 1)
        self.assertEqual(len(backup.list_backups(remote_dir)), 1)

        # Share not mounted: local copy is still made, but the run fails.
        result = self.run_script("backup_db.py", "--db", db_path, "--dir", local_dir, "--remote-dir", os.path.join(work, "gone"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("copy to", result.stdout)

        backup_file = backup.list_backups(local_dir)[0][1]
        connection = sqlite3.connect(db_path)
        connection.execute("DELETE FROM server_rooms")
        connection.execute("UPDATE app_state SET value = 99 WHERE key = 'rack'")
        connection.commit()
        connection.close()

        result = self.run_script("restore_db.py", backup_file, "--db", db_path, "--dir", local_dir, "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        connection = sqlite3.connect(db_path)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM server_rooms").fetchone()[0], 1)
        # Versions only move forward, so open pages refresh after a restore.
        self.assertEqual(dict(connection.execute("SELECT key, value FROM app_state")), {"rack": 100, "inventory": 41})
        # The pre-restore state was saved as an extra backup.
        self.assertGreaterEqual(len(backup.list_backups(local_dir)), 2)


if __name__ == "__main__":
    unittest.main()
