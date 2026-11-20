"""Rack change history: entries, their row changes, and undo."""

import json

from .base import Repository


class AuditRepository(Repository):

    # --------------------------------------------------------
    # Recording (Database.write(touch="rack") calls begin / finish)
    # --------------------------------------------------------

    def begin(self, now, actor):
        """Open an entry and switch the triggers on. Returns its id, or None
        when the history tables do not exist yet."""

        try:
            name = actor.get("name") or ""
            if not name and actor.get("ip"):
                row = self._one(
                    "SELECT hostname FROM arp_entries WHERE ip = ? AND hostname NOT IN ('', '-') "
                    "ORDER BY last_seen DESC LIMIT 1",
                    (actor["ip"],),
                )
                name = row[0] if row else ""
            cursor = self._execute(
                "INSERT INTO rack_audit (at, actor_ip, actor_name, actor_user, action) VALUES (?, ?, ?, ?, ?)",
                (now, actor.get("ip") or "", name, actor.get("user") or "", actor.get("action") or ""),
            )
            self._execute("UPDATE rack_audit_context SET audit_id = ? WHERE id = 1", (cursor.lastrowid,))
            return cursor.lastrowid
        except Exception as exc:              # noqa: BLE001 — history must never block a change
            if "no such table" in str(exc):
                return None
            raise

    def finish(self, audit_id):
        """Switch the triggers off; drop the entry if nothing changed."""

        if audit_id is None:
            return False
        self._execute("UPDATE rack_audit_context SET audit_id = NULL WHERE id = 1")
        if self._one("SELECT 1 FROM rack_audit_rows WHERE audit_id = ? LIMIT 1", (audit_id,)) is None:
            self._execute("DELETE FROM rack_audit WHERE id = ?", (audit_id,))
            return False
        return True

    # --------------------------------------------------------
    # Reading
    # --------------------------------------------------------

    def entries(self, limit=100, before=None):
        """Newest first; limit None = all."""

        where, params = ("WHERE id < ?", [before]) if before else ("", [])
        if limit is None:
            return self._dicts(f"SELECT * FROM rack_audit {where} ORDER BY id DESC", params)
        return self._dicts(f"SELECT * FROM rack_audit {where} ORDER BY id DESC LIMIT ?", params + [limit])

    def actor_users(self):
        """Signed-in users who made changes, by name."""

        rows = self._all("SELECT DISTINCT actor_user FROM rack_audit WHERE COALESCE(actor_user, '') <> '' ORDER BY actor_user")
        return [row[0] for row in rows]

    def entry(self, audit_id):
        row = self._one("SELECT * FROM rack_audit WHERE id = ?", (audit_id,))
        return dict(row) if row else None

    def port_entries(self, switch_id, port, macs=(), before=None, since=None, limit=200):
        """Rack History entries that touched one switch port: its cables,
        note, name and documented devices, and hostnames typed in for the
        MACs seen on it. Newest first: [(entry, [its rows of this port])];
        since <= at < before (either may be None); limit None = all."""

        value = "json_extract(COALESCE(r.new_row, r.old_row), '$.{}')".format
        at_port = f"({value('switch_id')} = ? AND {value('port')} = ?)"
        cable_end = "({t} = 'switch' AND {i} = ? AND {p} = ?)"
        cable = " OR ".join(
            cable_end.format(t=value(f"endpoint_{side}_type"), i=value(f"endpoint_{side}_id"), p=value(f"endpoint_{side}_port"))
            for side in ("a", "b")
        )
        macs = list(macs)
        mac_marks = ", ".join("?" for _ in macs) or "NULL"
        rows = self._dicts(
            f"""
            SELECT r.*, a.at, a.actor_ip, a.actor_name, a.actor_user, a.action, a.undo_of, a.undone_by
            FROM rack_audit_rows r
            JOIN rack_audit a ON a.id = r.audit_id
            WHERE ((r.tbl IN ('ports', 'port_names', 'port_expected_devices') AND {at_port})
                   OR (r.tbl = 'port_connections' AND ({cable}))
                   OR (r.tbl = 'host_names' AND {value('mac')} IN ({mac_marks})))
              AND (? IS NULL OR a.at < ?) AND (? IS NULL OR a.at >= ?)
            ORDER BY r.audit_id DESC, r.id
            """,
            [switch_id, port, switch_id, port, switch_id, port, *macs, before, before, since, since],
        )
        entries = {}
        for row in rows:
            row["old_row"] = json.loads(row["old_row"]) if row["old_row"] else None
            row["new_row"] = json.loads(row["new_row"]) if row["new_row"] else None
            if row["audit_id"] not in entries:
                if limit is not None and len(entries) == limit:
                    break
                entry = {key: row[key] for key in ("at", "actor_ip", "actor_name", "actor_user", "action", "undo_of", "undone_by")}
                entry["id"] = row["audit_id"]
                entries[row["audit_id"]] = (entry, [])
            entries[row["audit_id"]][1].append(row)
        return list(entries.values())

    def rows(self, audit_ids):
        """{audit_id: [row change, ...]} in the order they happened; JSON decoded."""

        audit_ids = list(audit_ids)
        result = {audit_id: [] for audit_id in audit_ids}
        if not audit_ids:
            return result
        marks = ", ".join("?" for _ in audit_ids)
        for row in self._dicts(f"SELECT * FROM rack_audit_rows WHERE audit_id IN ({marks}) ORDER BY id", audit_ids):
            row["old_row"] = json.loads(row["old_row"]) if row["old_row"] else None
            row["new_row"] = json.loads(row["new_row"]) if row["new_row"] else None
            result[row["audit_id"]].append(row)
        return result

    def set_action(self, audit_id, action, undo_of=None):
        self._execute("UPDATE rack_audit SET action = ?, undo_of = ? WHERE id = ?", (action, undo_of, audit_id))

    def mark_undone(self, audit_id, undone_by):
        self._execute("UPDATE rack_audit SET undone_by = ? WHERE id = ?", (undone_by, audit_id))

    def current_audit_id(self):
        row = self._one("SELECT audit_id FROM rack_audit_context WHERE id = 1")
        return row[0] if row else None

    # --------------------------------------------------------
    # Undo: put rows back as they were
    # --------------------------------------------------------

    def all_rows(self, table):
        """Every row of a small rack table, for names (no images)."""

        columns = [row[1] for row in self._all(f"PRAGMA table_info({_q(table)})") if row[1] != "front_image"]
        return self._dicts(f"SELECT {', '.join(_q(c) for c in columns)} FROM {_q(table)}")

    def current_row(self, table, row_id, columns):
        row = self._one(f"SELECT {', '.join(_q(c) for c in columns)} FROM {_q(table)} WHERE rowid = ?", (row_id,))
        return dict(zip(columns, row)) if row else None

    def delete_row(self, table, row_id):
        self._execute(f"DELETE FROM {_q(table)} WHERE rowid = ?", (row_id,))

    def insert_row(self, table, values):
        columns = list(values)
        self._execute(
            f"INSERT INTO {_q(table)} ({', '.join(_q(c) for c in columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [values[c] for c in columns],
        )

    def update_row(self, table, row_id, values):
        columns = list(values)
        self._execute(
            f"UPDATE {_q(table)} SET {', '.join(_q(c) + ' = ?' for c in columns)} WHERE rowid = ?",
            [values[c] for c in columns] + [row_id],
        )


def _q(name):
    return '"' + str(name).replace('"', '""') + '"'
