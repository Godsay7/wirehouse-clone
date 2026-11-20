"""Rack change history: who changed what in Rack Change, and undo."""

from ..domain.rack_audit import Names, actor_label, describe_rows, entry_target, final_states
from ..errors import NotFoundError, ValidationError

PAGE_SIZE = 100


class RackHistoryService:

    def __init__(self, database):
        self.database = database

    def history(self, before=None, limit=PAGE_SIZE, filters=None):
        """One page of changes, newest first. filters (all optional): text
        (in what changed, who, the action, #id), room_id, user, since / until
        (dates, YYYY-MM-DD, inclusive). With filters every change is looked
        at (the history is small); "older" continues after the last match."""

        filters = {key: value for key, value in (filters or {}).items() if value not in (None, "")}
        with self.database.read() as uow:
            entries = uow.audit.entries(None if filters else limit, before)
            rows = uow.audit.rows(entry["id"] for entry in entries)
            current = _current_names(uow)
            users = uow.audit.actor_users()
            rack_ids, room_ids = set(current["racks"]), set(current["server_rooms"])
            names = Names(current)

        matches = []
        for entry in entries:
            entry_rows = rows.get(entry["id"], [])
            entry["lines"] = describe_rows(entry_rows, names)
            entry["row_count"] = len(entry_rows)
            entry["who"] = actor_label(entry)
            entry["can_undo"] = not entry.get("undone_by")
            entry["target"] = entry_target(entry_rows, names, rack_ids, room_ids)
            if not filters or _matches(entry, filters, current):
                matches.append(entry)
                if len(matches) > limit:
                    break

        more = len(matches) > limit if filters else len(entries) == limit
        matches = matches[:limit]
        rooms = sorted(current["server_rooms"].values(), key=lambda room: (room.get("name") or "").lower())
        return {
            "entries": matches,
            "older": matches[-1]["id"] if more and matches else None,
            "filters": filters,
            "rooms": [{"id": room["id"], "name": room.get("name") or f"#{room['id']}"} for room in rooms],
            "users": users,
        }

    def undo(self, audit_id):
        """Put every row of one change back as it was. Recorded as a new change
        (so it can be undone too). Refused if those rows changed since."""

        with self.database.write(touch="rack") as uow:
            entry = uow.audit.entry(audit_id)
            if entry is None:
                raise NotFoundError("Change not found")
            if entry.get("undone_by"):
                raise ValidationError(f"Change #{audit_id} is already undone (by #{entry['undone_by']})")

            rows = uow.audit.rows([audit_id])[audit_id]
            if not rows:
                raise ValidationError("Nothing to undo")

            changed_since = []
            for (table, row_id), expected in final_states(rows).items():
                sample = expected or next(r["old_row"] for r in rows if (r["tbl"], r["row_id"]) == (table, row_id) and r["old_row"])
                current = uow.audit.current_row(table, row_id, list(sample))
                if current != expected:
                    changed_since.append((table, row_id))
            if changed_since:
                names = Names(_current_names(uow))
                what = describe_rows([r for r in rows if (r["tbl"], r["row_id"]) in set(changed_since)], names)
                raise ValidationError(
                    f"Cannot undo #{audit_id}: this was changed again later ("
                    + "; ".join(what[:3]) + ("…" if len(what) > 3 else "")
                    + "). Undo the later changes first."
                )

            for row in reversed(rows):
                if row["op"] == "insert":
                    uow.audit.delete_row(row["tbl"], row["row_id"])
                elif row["op"] == "delete":
                    uow.audit.insert_row(row["tbl"], row["old_row"])
                elif row["tbl"] == "ports":
                    uow.audit.update_row("ports", row["row_id"], {"description": row["old_row"]["description"]})
                else:
                    uow.audit.update_row(row["tbl"], row["row_id"], row["old_row"])

            undo_id = uow.audit.current_audit_id()
            if undo_id is not None:
                uow.audit.set_action(undo_id, f"Undo #{audit_id}", undo_of=audit_id)
                uow.audit.mark_undone(audit_id, undo_id)
            return undo_id


def _matches(entry, filters, current):
    """Does a change pass the filters of history()?"""

    day = (entry.get("at") or "")[:10]
    if filters.get("since") and day < filters["since"]:
        return False
    if filters.get("until") and day > filters["until"]:
        return False
    if filters.get("user") and (entry.get("actor_user") or "") != filters["user"]:
        return False
    if filters.get("room_id"):
        target = entry.get("target") or {}
        room = target.get("room_id")
        if room is None and target.get("rack_id"):
            room = (current["racks"].get(target["rack_id"]) or {}).get("server_room_id")
        if room != filters["room_id"]:
            return False
    if filters.get("text"):
        words = filters["text"].lower().split()
        haystack = " ".join([f"#{entry['id']}", entry.get("actor_user") or "", entry.get("who") or "",
                             entry.get("action") or "", *entry["lines"]]).lower()
        if not all(word in haystack for word in words):
            return False
    return True


def _current_names(uow):
    data = {
        "switches": {row["id"]: row["host"] for row in uow.checks.switches()},
        "if_names": {(row["switch_id"], row["port"]): row["if_name"] for row in uow.checks.ports()},
    }
    for table in ("servers", "patch_panels", "rack_switch_placeholders", "cable_organizers", "racks", "server_rooms"):
        data[table] = {row["id"]: row for row in uow.audit.all_rows(table)}
    data["rack_switches"] = {row["switch_id"]: row for row in uow.audit.all_rows("rack_switches")}
    return data
