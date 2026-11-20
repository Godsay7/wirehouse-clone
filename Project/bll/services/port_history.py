"""Port history: everything that happened on one switch port, newest first.

Sources:
* port_changes (collector): link up / down, speed, VLAN, devices (MACs);
* port_error_events (collector): error counters that grew;
* Rack History (rack_audit): cables, note, name and documented devices of
  the port, hostnames typed in for the devices seen on it.
"""

from ...core.mac import split_macs
from ..domain.cabling_check import DEVICE_PORT_MAX_MACS, port_macs
from ..domain.rack_audit import Names, actor_label, describe_rows
from ..errors import NotFoundError
from .cabling_check import cable_journal_entries
from .rack_history import _current_names

PAGE_SIZE = 150


class PortHistoryService:

    def __init__(self, database, inventory):
        self.database = database
        self.inventory = inventory

    def history(self, switch_id, port, before=None, limit=PAGE_SIZE):
        # The port as the switch page shows it (names, IPs, VLAN, errors).
        page = self.inventory.switch_page(switch_id)
        current = next((row for row in page["all_ports"] if row.get("port") == port), None)
        if current is None:
            raise NotFoundError(f"Port {port} of switch {switch_id} not found")

        with self.database.read() as uow:
            hostnames = {**uow.checks.hostnames(), **uow.checks.host_names()}
            ips = uow.checks.ips()

            # Hostnames typed in for any device seen on the port count as its history.
            macs = set(port_macs(current.get("mac"))) | set(port_macs(current.get("last_mac")))

            def fetch(since, page_limit):
                changes = uow.history.port_changes(switch_id, port, before, since, page_limit)
                errors = uow.history.port_error_events(switch_id, port, before, since, page_limit)
                for row in changes:
                    if row["change_type"] == "MAC":
                        for value in (row["old_value"], row["new_value"]):
                            found = port_macs(value)
                            if len(found) <= DEVICE_PORT_MAX_MACS:
                                macs.update(found)
                audit = uow.audit.port_entries(switch_id, port, sorted(macs), before, since, page_limit)
                return changes, errors, audit

            # One page: each source gives at most ``limit`` events. Where a
            # source was cut off, older events of it are missing, so the page
            # ends at the newest such cut, and that last moment is fetched in
            # full from every source ("older" then starts below it).
            changes, errors, audit = fetch(None, limit)
            cuts = [rows[-1] for rows in (changes, errors) if len(rows) == limit]
            cuts = [row["detected_at"] for row in cuts] + ([audit[-1][0]["at"]] if len(audit) == limit else [])
            older = max(cuts) if cuts else None
            if older:
                changes, errors, audit = fetch(older, None)

            names = Names(_current_names(uow))
            journal = next((entry for entry in cable_journal_entries(uow, switch_id) if entry["port"] == port), None)

        def device(mac):
            return {"mac": mac, "name": hostnames.get(mac, ""), "ip": ips.get(mac, "")}

        events = [_change_event(row, device) for row in changes]
        events += [_error_event(row) for row in errors]
        for entry, rows in audit:
            events.append({
                "at": entry["at"],
                "kind": "doc",
                "lines": describe_rows(rows, names),
                "who": actor_label(entry),
                "user": entry.get("actor_user") or "",
                "undone": bool(entry.get("undone_by")),
                "audit_id": entry["id"],
            })
        events = _speed_into_link([event for event in events if event])
        events.sort(key=lambda event: event["at"], reverse=True)

        cable = {"Cabled to": journal["cabled_to"], "Cable leads to": journal["leads_to"],
                 "Port note": journal["note"]} if journal else {}
        return {
            "switch": page["switch"],
            "port": current,
            "devices": [device(mac) for mac in port_macs(current.get("mac"))],
            "cable": cable,
            "events": events,
            "older": older,
            "before": before,
            "error_window_hours": page["error_window_hours"],
        }


def _change_event(row, device):
    kind = row["change_type"]
    if kind == "Link":
        return {"at": row["detected_at"], "kind": "link", "up": (row["new_value"] or "").upper() == "UP",
                "old": row["old_value"], "new": row["new_value"]}
    if kind in ("Speed", "VLAN"):
        return {"at": row["detected_at"], "kind": kind.lower(), "old": row["old_value"], "new": row["new_value"]}
    if kind == "MAC":
        old, new = split_macs(row["old_value"]), split_macs(row["new_value"])
        event = {"at": row["detected_at"], "kind": "devices"}
        if len(old) > DEVICE_PORT_MAX_MACS or len(new) > DEVICE_PORT_MAX_MACS:
            # An uplink: which of its many devices came and went says little.
            event.update(many=True, old_count=len(old), new_count=len(new))
            return event
        event.update(many=False,
                     appeared=[device(mac) for mac in new if mac not in old],
                     left=[device(mac) for mac in old if mac not in new])
        return event if event["appeared"] or event["left"] else None
    return None


def _speed_into_link(events):
    """A link that goes up or down usually changes its speed at the same
    moment (1G -> 10M when down): that speed is shown in the link's row."""

    links = {}
    for event in events:
        if event["kind"] == "link":
            links.setdefault(event["at"], []).append(event)
    kept = []
    for event in events:
        free = [link for link in links.get(event["at"], []) if "speed" not in link] if event["kind"] == "speed" else []
        if free:
            free[0]["speed"] = {"old": event["old"], "new": event["new"]}
        else:
            kept.append(event)
    return kept


def _error_event(row):
    return {"at": row["detected_at"], "kind": "errors",
            "errors": {"in": row["in_errors"], "out": row["out_errors"], "fcs": row["fcs_errors"]}}
