"""Cable checklist: one user's walk through the racks, port by port.

Every port of every switch with its documented cable; the user confirms that
the port and the patch panel / device port match the documentation, and marks
cables to be replaced by shorter ones or laid neatly. The marks live only in
cable_checklist and only on this page (no Rack History, nowhere else).

A confirmation keeps what was confirmed (the "target"): if the documented
cabling changes later, the port shows "changed since confirmed". "Not as
documented" keeps where the cable really goes ("mismatch"), until the port
is confirmed or the note is cleared.

Rows come in the order of a walk through the racks: server room, rack,
switches from the top unit down, ports in order. NH Server Room first, then
Digital, the other rooms, switches not in a rack, the bunker last
(FIRST_ROOMS / LAST_ROOMS).
"""

import re

from ...core.text import now_iso
from ..errors import NotFoundError, ValidationError
from .cabling_check import _in_place, cable_journal_entries, journal_device

NOTE_MAX = 300
# The walk: these server rooms first, in this order (NH, then Digital); then
# the other rooms by name and the switches in no rack; the bunker last
# (a room whose name contains one of LAST_ROOMS).
FIRST_ROOMS = ("nh server room", "digital")
LAST_ROOMS = ("bunker", "бункер")


def _room_rank(entry):
    room = entry["room"].lower()
    if any(word in room for word in LAST_ROOMS):
        return len(FIRST_ROOMS) + 2
    if room in FIRST_ROOMS:
        return FIRST_ROOMS.index(room)
    return len(FIRST_ROOMS) + (0 if entry["rack"] else 1)


def _natural(text):
    """'Rack 10' after 'Rack 9'."""

    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text or "")]


def target_of(entry):
    """What a confirmation confirms: the documented cable of the port (to the
    patch / device port, and where it leads); without a cable, the device seen."""

    cabled = _in_place(entry["cabled_to"], entry["room"], entry["rack"])
    leads = _in_place(entry["leads_to"], entry["room"], entry["rack"])
    if cabled:
        return cabled + (f" → {leads}" if leads else "")
    device = journal_device(entry)[0]
    return f"(no cable) {device}" if device else "(no cable)"


def _marked(mark):
    """Anything set on the port (a cleared mark leaves its row behind)."""

    return bool(mark) and (mark.get("confirmed_target") is not None or bool(mark.get("shorter")) or bool(mark.get("tidy"))
                           or bool(mark.get("note")) or bool(mark.get("actual")) or mark.get("label") is not None)


class ChecklistService:

    def __init__(self, database):
        self.database = database

    def rows(self):
        with self.database.read() as uow:
            entries = cable_journal_entries(uow)
            marks = uow.checklist.all()
        entries.sort(key=lambda e: (
            _room_rank(e), e["room"].lower(), _natural(e["rack"]), -int(e["unit"] or 0), e["host"].lower(), e["port"],
        ))
        return [self._row(entry, marks.get((entry["switch_id"], entry["port"]))) for entry in entries]

    @staticmethod
    def _row(entry, mark):
        mark = mark or {}
        target = target_of(entry)
        confirmed = mark.get("confirmed_target")
        status = "open" if confirmed is None else ("confirmed" if confirmed == target else "changed")
        actual = mark.get("actual") or ""
        if actual:
            status = "mismatch"
        device, ip_text, _ = journal_device(entry)
        place = " / ".join(x for x in (entry["room"], entry["rack"]) if x)
        location = place + (f" · U{entry['unit']}" if place and entry["unit"] else "")
        link = (entry["link"] or "-").upper()
        if link == "UP" and entry["speed"] and entry["speed"] != "-":
            link += f" · {entry['speed']}"
        return {
            "switch_id": entry["switch_id"], "switch": entry["host"], "location": location, "place": place,
            "rack_id": entry["rack_id"], "side": entry["side"],
            "port": entry["port"], "if_name": entry["if_name"] or f"p{entry['port']}", "link": link,
            "up": (entry["link"] or "").upper() == "UP",
            "note": entry["note"] or entry["alias"],
            "cabled_to": _in_place(entry["cabled_to"], entry["room"], entry["rack"]),
            "leads_to": _in_place(entry["leads_to"], entry["room"], entry["rack"]),
            "device": " · ".join(x for x in (device, ip_text) if x),
            "status": status, "confirmed_target": confirmed, "confirmed_at": mark.get("confirmed_at"),
            "confirmed_by": mark.get("confirmed_by"),
            "shorter": bool(mark.get("shorter")), "tidy": bool(mark.get("tidy")), "mark_note": mark.get("note") or "",
            "actual": actual,
            # The sticker on the cable: "yes", "no" or "" (not checked yet).
            "label": {1: "yes", 0: "no"}.get(mark.get("label"), ""),
            # Something to do on the cable: shorter, lay neatly, put a label on it.
            "needs_work": bool(mark.get("shorter") or mark.get("tidy") or mark.get("label") == 0),
            # A port to check (counted in the progress, shown by default): one
            # with a documented cable, one where something is plugged in (link
            # up), or one marked anyway. Free ports with the link down are not:
            # they would keep a switch below 100%.
            "to_check": bool(entry["cabled_to"]) or (entry["link"] or "").upper() == "UP" or _marked(mark),
            # The documentation changed after the mismatch was noted (maybe already fixed).
            "mismatch_changed": bool(actual) and mark.get("mismatch_target") not in (None, target),
        }

    def mark(self, switch_id, port, field, value, user):
        """field: "confirmed" (True / False), "shorter", "tidy" (True / False),
        "note" (text), "actual" (where the cable really goes; empty clears
        it) or "label" ("yes" / "no" / "" — the sticker on the cable).
        Returns the row as rows() shows it."""

        if field not in ("confirmed", "shorter", "tidy", "note", "actual", "label"):
            raise ValidationError("Unknown checklist field")
        now = now_iso()
        with self.database.write() as uow:
            entry = next((e for e in cable_journal_entries(uow, switch_id) if e["port"] == port), None)
            if entry is None:
                raise NotFoundError("Switch port not found")
            if field == "confirmed":
                # Confirming settles a mismatch noted before.
                values = ({"confirmed_target": target_of(entry), "confirmed_at": now, "confirmed_by": user,
                           "actual": "", "mismatch_target": None}
                          if value else {"confirmed_target": None, "confirmed_at": None, "confirmed_by": None})
            elif field == "actual":
                actual = " ".join(str(value or "").split())[:NOTE_MAX]
                values = ({"actual": actual, "mismatch_target": target_of(entry),
                           "confirmed_target": None, "confirmed_at": None, "confirmed_by": None}
                          if actual else {"actual": "", "mismatch_target": None})
            elif field == "label":
                if value not in ("yes", "no", "", None):
                    raise ValidationError("Unknown label state")
                values = {"label": {"yes": 1, "no": 0}.get(value)}
            elif field == "note":
                values = {"note": " ".join(str(value or "").split())[:NOTE_MAX]}
            else:
                values = {field: bool(value)}
            mark = uow.checklist.save(switch_id, port, values, user, now)
        return self._row(entry, mark)
