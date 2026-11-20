"""Cable checklist marks (services/checklist.py)."""

from .base import Repository

FIELDS = ("confirmed_target", "confirmed_at", "confirmed_by", "shorter", "tidy", "note", "actual", "mismatch_target", "label")


class ChecklistRepository(Repository):

    def all(self):
        """(switch_id, port) -> its marks."""

        return {
            (row["switch_id"], row["port"]): row
            for row in self._dicts("SELECT * FROM cable_checklist")
        }

    def get(self, switch_id, port):
        row = self._one("SELECT * FROM cable_checklist WHERE switch_id = ? AND port = ?", (switch_id, port))
        return dict(row) if row else None

    def save(self, switch_id, port, values, user, now):
        """values: the FIELDS to set; the others keep what they were."""

        current = self.get(switch_id, port) or {}
        merged = {field: values.get(field, current.get(field)) for field in FIELDS}
        merged["shorter"] = int(bool(merged["shorter"]))
        merged["tidy"] = int(bool(merged["tidy"]))
        merged["note"] = merged["note"] or ""
        merged["actual"] = merged["actual"] or ""
        merged["label"] = None if merged["label"] is None else int(bool(merged["label"]))
        self._execute(
            """
            INSERT INTO cable_checklist (switch_id, port, confirmed_target, confirmed_at, confirmed_by,
                                         shorter, tidy, note, actual, mismatch_target, label, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (switch_id, port) DO UPDATE SET
                confirmed_target = excluded.confirmed_target, confirmed_at = excluded.confirmed_at,
                confirmed_by = excluded.confirmed_by, shorter = excluded.shorter, tidy = excluded.tidy,
                note = excluded.note, actual = excluded.actual, mismatch_target = excluded.mismatch_target,
                label = excluded.label,
                updated_at = excluded.updated_at, updated_by = excluded.updated_by
            """,
            (switch_id, port, *(merged[field] for field in FIELDS), now, user),
        )
        return self.get(switch_id, port)
