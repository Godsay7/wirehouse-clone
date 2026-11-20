"""Delete port history and port changes older than the retention period."""

from datetime import datetime, timedelta, timezone

from ..dal.repositories.history import HistoryRepository

# One collector run deletes about this many port_history rows (in batches),
# so a large first cleanup is spread over several runs instead of holding the
# database (and the 300 s systemd timeout) for a long time.
DELETE_BATCH_SIZE = 50000
MAX_ROWS_PER_RUN = 1000000


def prune_old_records(connection, retention_days, now=None):
    """Return (history_rows_deleted, changes_deleted)."""

    if retention_days <= 0:
        return 0, 0

    # Stored timestamps are UTC with "+00:00", so the cutoff is too.
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = (now - timedelta(days=retention_days)).isoformat(timespec="seconds")

    history = HistoryRepository(connection)

    changes_deleted = history.delete_changes_before(cutoff)
    error_events_deleted = history.delete_error_events_before(cutoff)
    device_changes_deleted = history.delete_device_changes_before(cutoff)

    last_id = history.last_history_id_before(cutoff)
    history_deleted = 0

    if last_id is not None:
        history_deleted = history.delete_history_up_to(
            last_id,
            batch_size=DELETE_BATCH_SIZE,
            max_rows=MAX_ROWS_PER_RUN,
        )

    print(
        f"Retention ({retention_days} days, before {cutoff}): "
        f"deleted {history_deleted} port_history rows, "
        f"{changes_deleted} port_changes rows, "
        f"{error_events_deleted} port_error_events rows, "
        f"{device_changes_deleted} port_device_changes rows."
    )

    return history_deleted, changes_deleted
