"""Database backups: consistent copy, verification, compression, rotation.

A backup is taken with SQLite's online backup API, so the web app and the
collector keep working and changes still in the WAL file are included.
Every copy is checked with ``PRAGMA integrity_check`` before it is kept.

File names: switch_inventory-YYYY-MM-DD_HHMMSS.db.zst (or .db.gz when the
zstd command is not installed).
"""

import gzip
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta

BACKUP_PREFIX = "switch_inventory-"
NAME_PATTERN = re.compile(
    r"^switch_inventory-(\d{4}-\d{2}-\d{2}_\d{6})\.db\.(zst|gz)$"
)
TIMESTAMP_FORMAT = "%Y-%m-%d_%H%M%S"

ZSTD_LEVEL = "10"


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetentionPolicy:
    """Keep the newest backup of each of the last N days / weeks / months."""

    daily: int = 14
    weekly: int = 8
    monthly: int = 6


# ------------------------------------------------------------
# Creating a backup
# ------------------------------------------------------------

def create_backup(database_path, backup_dir, now=None):
    """Write a verified, compressed copy of the database into backup_dir.

    Returns the path of the new file.
    """

    now = now or datetime.now()
    os.makedirs(backup_dir, exist_ok=True)

    # Never overwrite an existing backup (two runs within one second).
    taken = {timestamp for timestamp, _ in list_backups(backup_dir)}
    now = now.replace(microsecond=0)
    while now in taken:
        now += timedelta(seconds=1)

    name = f"{BACKUP_PREFIX}{now.strftime(TIMESTAMP_FORMAT)}.db"
    final_db_path = os.path.join(backup_dir, name)

    # Work in a hidden temporary file next to the destination, so a crash
    # never leaves a half-written file with a valid backup name.
    handle, temp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".db", dir=backup_dir)
    os.close(handle)

    try:
        _copy_database(database_path, temp_path)
        _verify(temp_path)
        compressed_temp = _compress(temp_path)
        extension = compressed_temp.rsplit(".", 1)[-1]
        final_path = f"{final_db_path}.{extension}"
        os.replace(compressed_temp, final_path)
        return final_path
    finally:
        for leftover in (temp_path, temp_path + ".zst", temp_path + ".gz"):
            if os.path.exists(leftover):
                os.remove(leftover)


def _copy_database(source_path, destination_path):
    if not os.path.exists(source_path):
        raise BackupError(f"Database not found: {source_path}")

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=60)
    destination = sqlite3.connect(destination_path)

    try:
        source.backup(destination)
        # A standalone file: no WAL sidecar files next to the backup.
        destination.execute("PRAGMA journal_mode=DELETE")
    finally:
        destination.close()
        source.close()


def _verify(path):
    connection = sqlite3.connect(path)

    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()

    if result != "ok":
        raise BackupError(f"Integrity check failed for the backup copy: {result}")


def _compress(path):
    """Compress path into path.zst (or .gz); return the compressed file."""

    if shutil.which("zstd"):
        target = path + ".zst"
        subprocess.run(
            ["zstd", "-q", f"-{ZSTD_LEVEL}", "-T0", path, "-o", target],
            check=True,
        )
        return target

    target = path + ".gz"
    with open(path, "rb") as source, gzip.open(target, "wb", compresslevel=6) as destination:
        shutil.copyfileobj(source, destination)
    return target


# ------------------------------------------------------------
# Copying to a second location (network share)
# ------------------------------------------------------------

def copy_to(backup_path, target_dir):
    """Copy a finished backup into target_dir (e.g. an SMB mount)."""

    if not os.path.isdir(target_dir):
        raise BackupError(f"Backup target is not available: {target_dir}")

    name = os.path.basename(backup_path)
    final_path = os.path.join(target_dir, name)
    temp_path = os.path.join(target_dir, f".tmp-{name}")

    try:
        shutil.copyfile(backup_path, temp_path)

        if os.path.getsize(temp_path) != os.path.getsize(backup_path):
            raise BackupError(f"Incomplete copy in {target_dir}")

        os.replace(temp_path, final_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return final_path


# ------------------------------------------------------------
# Rotation
# ------------------------------------------------------------

def list_backups(directory):
    """[(timestamp, path)] of backup files in directory, newest first."""

    if not os.path.isdir(directory):
        return []

    result = []

    for name in os.listdir(directory):
        match = NAME_PATTERN.match(name)
        if not match:
            continue
        timestamp = datetime.strptime(match.group(1), TIMESTAMP_FORMAT)
        result.append((timestamp, os.path.join(directory, name)))

    return sorted(result, reverse=True)


def backups_to_keep(timestamps, policy):
    """Grandfather-father-son selection; returns the set of kept timestamps.

    The newest backup is always kept. For daily/weekly/monthly the newest
    backup of each of the most recent N days/weeks/months is kept.
    """

    ordered = sorted(timestamps, reverse=True)
    keep = set(ordered[:1])

    buckets = (
        (policy.daily, lambda ts: ts.date()),
        (policy.weekly, lambda ts: ts.isocalendar()[:2]),
        (policy.monthly, lambda ts: (ts.year, ts.month)),
    )

    for limit, bucket_of in buckets:
        seen = []
        for timestamp in ordered:
            bucket = bucket_of(timestamp)
            if bucket in seen:
                continue
            if len(seen) >= limit:
                break
            seen.append(bucket)
            keep.add(timestamp)

    return keep


def rotate(directory, policy):
    """Delete backups that the policy does not keep; return deleted paths."""

    backups = list_backups(directory)
    keep = backups_to_keep([timestamp for timestamp, _ in backups], policy)
    deleted = []

    for timestamp, path in backups:
        if timestamp not in keep:
            os.remove(path)
            deleted.append(path)

    return deleted


# ------------------------------------------------------------
# Restoring
# ------------------------------------------------------------

def decompress_to(backup_path, destination_path):
    if backup_path.endswith(".zst"):
        subprocess.run(
            ["zstd", "-q", "-d", "-f", backup_path, "-o", destination_path],
            check=True,
        )
    elif backup_path.endswith(".gz"):
        with gzip.open(backup_path, "rb") as source, open(destination_path, "wb") as destination:
            shutil.copyfileobj(source, destination)
    else:
        raise BackupError(f"Unknown backup format: {backup_path}")


def restore_backup(backup_path, database_path):
    """Replace the content of database_path with the backup.

    Uses the SQLite backup API in the opposite direction, so the running web
    app and collector simply see the restored data on their next query.
    """

    work_dir = tempfile.mkdtemp(prefix="switch-inventory-restore-")
    restored_path = os.path.join(work_dir, "restore.db")

    try:
        decompress_to(backup_path, restored_path)
        _verify(restored_path)

        source = sqlite3.connect(restored_path)
        destination = sqlite3.connect(database_path, timeout=60)

        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
