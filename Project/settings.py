"""Paths and runtime settings shared by the web UI and the collector.

Every value can be overridden with an environment variable so the same code
can run against a test database or a different config file.
"""

import os


COLLECTOR_BUILD = "2026-10-12-layered-architecture-v6.0"

# Repository root: /opt/switch-inventory
BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

DB_PATH = os.environ.get(
    "SWITCH_INVENTORY_DB",
    os.path.join(BASE_DIR, "scripts", "switch_inventory.db"),
)

CONFIG_PATH = os.environ.get(
    "SWITCH_INVENTORY_CONFIG",
    os.path.join(BASE_DIR, "config", "switches.yaml"),
)

# Timestamps are stored in UTC ("2026-10-14T14:45:59+00:00") and shown in
# this time zone.
TIMEZONE = os.environ.get("SWITCH_INVENTORY_TIMEZONE", "Europe/Kyiv")

# Interface language when the browser has not chosen one (uk / en).
DEFAULT_LANGUAGE = os.environ.get("SWITCH_INVENTORY_LANG", "uk")

# Sign-in (web/auth.py). Without signing in the site is read-only.
# USERS_FILE: "name:password-hash" lines, written by scripts/set_password.py.
USERS_FILE = os.environ.get(
    "SWITCH_INVENTORY_USERS_FILE",
    os.path.join(BASE_DIR, "config", "web_users"),
)
# Signs the session cookie. If the variable is empty, the key is kept in
# SECRET_KEY_FILE (created on the first start).
SECRET_KEY = os.environ.get("SWITCH_INVENTORY_SECRET_KEY", "")
SECRET_KEY_FILE = os.environ.get(
    "SWITCH_INVENTORY_SECRET_KEY_FILE",
    os.path.join(BASE_DIR, "config", "secret_key"),
)
# A signed-in browser stays signed in this long after the last sign-in.
SESSION_HOURS = int(os.environ.get("SWITCH_INVENTORY_SESSION_HOURS", "12"))


HOST = os.environ.get("SWITCH_INVENTORY_HOST", "0.0.0.0")
PORT = int(os.environ.get("SWITCH_INVENTORY_PORT", "8080"))

# port_history snapshots and port_changes older than this are deleted after
# every collector run.
RETENTION_DAYS = int(os.environ.get("SWITCH_INVENTORY_RETENTION_DAYS", "30"))

# Nightly backups (scripts/backup_db.py). BACKUP_REMOTE_DIR is the mount
# point of the network share; leave it empty to keep only local copies.
BACKUP_DIR = os.environ.get(
    "SWITCH_INVENTORY_BACKUP_DIR",
    "/var/backups/switch-inventory",
)
BACKUP_REMOTE_DIR = os.environ.get("SWITCH_INVENTORY_BACKUP_REMOTE_DIR", "")
BACKUP_KEEP_DAILY = int(os.environ.get("SWITCH_INVENTORY_BACKUP_KEEP_DAILY", "14"))
BACKUP_KEEP_WEEKLY = int(os.environ.get("SWITCH_INVENTORY_BACKUP_KEEP_WEEKLY", "8"))
BACKUP_KEEP_MONTHLY = int(os.environ.get("SWITCH_INVENTORY_BACKUP_KEEP_MONTHLY", "6"))
