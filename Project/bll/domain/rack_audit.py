"""Rack change history in words: row changes -> lines like "Cable added: A — B"."""

# Rows of these tables that belong to a device added/removed in the same
# change are not listed one by one ("24 patch ports added" is noise).
CHILD_OF = {
    "patch_ports": ("patch_panel_id", "patch_panels"),
    "server_ports": ("server_id", "servers"),
    "placeholder_ports": ("placeholder_id", "rack_switch_placeholders"),
}


class Names:
    """Looks up readable names, also for objects that no longer exist
    (their last known row from the history is used)."""

    def __init__(self, current):
        """current: {"switches": {id: host}, "if_names": {(switch_id, port): if_name},
        "servers": {id: row}, "patch_panels": {id: row}, "rack_switch_placeholders": {id: row},
        "cable_organizers": {id: row}, "racks": {id: row}, "server_rooms": {id: row}}"""

        self.data = current

    def learn(self, rows):
        for row in rows:
            table = row["tbl"]
            if table in ("servers", "patch_panels", "rack_switch_placeholders", "cable_organizers", "racks", "server_rooms"):
                values = row["new_row"] or row["old_row"] or {}
                if "id" in values:
                    self.data.setdefault(table, {}).setdefault(values["id"], values)

    def rack(self, rack_id):
        rack = self.data.get("racks", {}).get(rack_id)
        if not rack:
            return f"rack {rack_id}"
        room = self.data.get("server_rooms", {}).get(rack.get("server_room_id"), {})
        return f"{room.get('name', '?')} / {rack.get('name', '?')}"

    def place(self, values):
        """'Room / Rack, U12 rear' of a row that has rack_id / rack_unit / side."""

        text = self.rack(values.get("rack_id"))
        if values.get("rack_unit"):
            text += f", U{values['rack_unit']}"
        if values.get("side"):
            text += f" {values['side']}"
        return text

    def thing(self, table, thing_id):
        row = self.data.get(table, {}).get(thing_id)
        return (row or {}).get("name") or f"{table.rstrip('s').replace('_', ' ')} {thing_id}"

    def switch(self, switch_id):
        return self.data.get("switches", {}).get(switch_id) or f"switch {switch_id}"

    def endpoint(self, endpoint_type, endpoint_id, port):
        if endpoint_type == "switch":
            if_name = self.data.get("if_names", {}).get((endpoint_id, port))
            return f"{self.switch(endpoint_id)} {if_name or ('mng' if port == 0 else 'p' + str(port))}"
        if endpoint_type == "server":
            return f"{self.thing('servers', endpoint_id)} {'mng' if port == 0 else 'p' + str(port)}"
        if endpoint_type == "placeholder":
            return f"{self.thing('rack_switch_placeholders', endpoint_id)} p{port}"
        return f"{self.thing('patch_panels', endpoint_id)} p{port}"


def _quote(text):
    text = str(text or "")
    return f"“{text}”" if text else "(empty)"


def describe_rows(rows, names):
    """Human-readable lines for the row changes of one history entry."""

    names.learn(rows)
    created_or_removed = {
        (row["tbl"], (row["new_row"] or row["old_row"] or {}).get("id"))
        for row in rows if row["op"] in ("insert", "delete")
    }

    lines, seen = [], set()

    def add(text):
        if text not in seen:
            seen.add(text)
            lines.append(text)

    for row in rows:
        table, op = row["tbl"], row["op"]
        old, new = row["old_row"] or {}, row["new_row"] or {}
        values = new or old

        if table in CHILD_OF:
            parent_key, parent_table = CHILD_OF[table]
            if (parent_table, values.get(parent_key)) in created_or_removed:
                continue

        verb = {"insert": "added", "delete": "removed", "update": "changed"}[op]

        if table == "port_connections":
            a = names.endpoint(values["endpoint_a_type"], values["endpoint_a_id"], values["endpoint_a_port"])
            b = names.endpoint(values["endpoint_b_type"], values["endpoint_b_id"], values["endpoint_b_port"])
            add(f"Cable {verb}: {a} — {b}")
        elif table == "patch_connections":
            a = names.endpoint("patch", values["patch_panel_a_id"], values["patch_port_a"])
            b = names.endpoint("patch", values["patch_panel_b_id"], values["patch_port_b"])
            add(f"Cable {verb}: {a} — {b}")
        elif table == "ports":
            add(f"Note on {names.endpoint('switch', values['switch_id'], values['port'])}: "
                f"{_quote(old.get('description'))} → {_quote(new.get('description'))}")
        elif table == "patch_ports":
            where = names.endpoint("patch", values["patch_panel_id"], values["port"])
            if op == "update":
                for key in ("description", "label"):
                    if old.get(key) != new.get(key):
                        add(f"Note on {where}: {_quote(old.get(key))} → {_quote(new.get(key))}")
            else:
                add(f"Patch port {verb}: {where}")
        elif table == "placeholder_ports":
            where = names.endpoint("placeholder", values["placeholder_id"], values["port"])
            add(f"Note on {where}: {_quote(old.get('description'))} → {_quote(new.get('description'))}")
        elif table == "server_ports":
            where = names.endpoint("server", values["server_id"], values["port"])
            if op == "update":
                add(f"Label of {where}: {_quote(old.get('label'))} → {_quote(new.get('label'))}")
            else:
                add(f"Server port {verb}: {where}")
        elif table in ("servers", "patch_panels", "rack_switch_placeholders", "cable_organizers"):
            kind = {"servers": "Server", "patch_panels": "Patch panel",
                    "rack_switch_placeholders": "Temporary switch", "cable_organizers": "Cable organizer"}[table]
            name = values.get("name") or kind
            if op == "update":
                changes = []
                for key, label in (("depth", "depth"), ("side", "side"), ("rack_unit", "unit"), ("name", "name"),
                                   ("height_units", "height"), ("port_count", "ports"), ("port_layout", "port layout")):
                    if key in old and old.get(key) != new.get(key):
                        changes.append(f"{label} {old.get(key)} → {new.get(key)}")
                if old.get("front_image") != new.get("front_image"):
                    changes.append("front image " + ("removed" if not new.get("front_image") else "changed"))
                add(f"{kind} {name} ({names.place(values)}): " + (", ".join(changes) or "changed"))
            else:
                add(f"{kind} {verb}: {name} ({names.place(values)})")
        elif table == "rack_switches":
            where = names.place(values)
            if op == "update":
                add(f"Switch {names.switch(values['switch_id'])} moved: {names.place(old)} → {where}")
            else:
                add(f"Switch {names.switch(values['switch_id'])} {'mounted in' if op == 'insert' else 'removed from'} {where}")
        elif table == "racks":
            room = names.data.get("server_rooms", {}).get(values.get("server_room_id"), {}).get("name", "?")
            add(f"Rack {verb}: {room} / {values.get('name')}")
        elif table == "server_rooms":
            if op == "update" and old.get("board_layout") != new.get("board_layout"):
                add(f"Rack View board of {values.get('name')}: {old.get('board_layout') or 'grid'} → {new.get('board_layout') or 'grid'}")
            else:
                add(f"Server room {verb}: {values.get('name')}")
        elif table in ("rack_view_order", "rack_view_slots"):
            add("Rack View board order changed")
        elif table == "trunk_cables":
            count = values.get("port_count", 0)
            a, b = names.thing("patch_panels", values.get("panel_a_id")), names.thing("patch_panels", values.get("panel_b_id"))
            first_a, first_b = values.get("port_a_start", 1), values.get("port_b_start", 1)
            add(f"Trunk {verb}: {a} p{first_a}–{first_a + count - 1} ↔ {b} p{first_b}–{first_b + count - 1}"
                + (f" ({values['name']})" if values.get("name") else ""))
        elif table == "port_names":
            where = names.endpoint("switch", values["switch_id"], values["port"])
            if op == "update" and old.get("name") == new.get("name") and old.get("mac") == new.get("mac"):
                add(f"Name on {where} confirmed: {values.get('name')}")
            else:
                add(f"Name on {where} {verb}: {values.get('name')} {values.get('mac')}".rstrip())
        elif table == "host_names":
            if op == "update":
                add(f"Hostname of {values.get('mac')}: {old.get('name')} → {new.get('name')}")
            else:
                add(f"Hostname {verb}: {values.get('mac')} {values.get('name')}")
        elif table == "port_expected_devices":
            where = names.endpoint("switch", values["switch_id"], values["port"])
            add(f"Documented device {verb} on {where}: {values.get('name') or ''} {values.get('mac')}".rstrip())
        else:
            add(f"{table} {verb}")

    return lines


def actor_label(entry):
    if entry.get("actor_ip") in ("127.0.0.1", "::1"):
        return "this server (script)"
    if entry.get("actor_name") and entry.get("actor_ip"):
        return f"{entry['actor_name']} ({entry['actor_ip']})"
    return entry.get("actor_name") or entry.get("actor_ip") or "system"


def final_states(rows):
    """{(table, row_id): row as it was left by this change, or None if removed}."""

    final = {}
    for row in rows:
        final[(row["tbl"], row["row_id"])] = row["new_row"] if row["op"] != "delete" else None
    return final


def entry_target(rows, names, rack_ids, room_ids):
    """Where a change happened, for the history row to open:
    {"rack_id", "side", "focus"} (Rack Change at that port), {"room_id"}
    (Rack View), or None. rack_ids / room_ids: racks and rooms that exist now."""

    def device(table, device_id):
        return names.data.get(table, {}).get(device_id) or {}

    def at_endpoint(endpoint_type, endpoint_id, port):
        if endpoint_type == "switch":
            place = names.data.get("rack_switches", {}).get(endpoint_id) or {}
        else:
            table = {"server": "servers", "placeholder": "rack_switch_placeholders"}.get(endpoint_type, "patch_panels")
            place = device(table, endpoint_id)
        if place.get("rack_id") in rack_ids:
            return {"rack_id": place["rack_id"], "side": place.get("side") or "front",
                    "focus": f"{endpoint_type}-{endpoint_id}-port-{port}"}
        return None

    for row in rows:
        table = row["tbl"]
        values = row["new_row"] or row["old_row"] or {}
        target = None

        if table == "port_connections":
            target = (at_endpoint(values["endpoint_a_type"], values["endpoint_a_id"], values["endpoint_a_port"])
                      or at_endpoint(values["endpoint_b_type"], values["endpoint_b_id"], values["endpoint_b_port"]))
        elif table == "patch_connections":
            target = at_endpoint("patch", values["patch_panel_a_id"], values["patch_port_a"])
        elif table in ("ports", "port_expected_devices", "port_names"):
            target = at_endpoint("switch", values["switch_id"], values["port"])
        elif table == "patch_ports":
            target = at_endpoint("patch", values["patch_panel_id"], values["port"])
        elif table == "server_ports":
            target = at_endpoint("server", values["server_id"], values["port"])
        elif table == "placeholder_ports":
            target = at_endpoint("placeholder", values["placeholder_id"], values["port"])
        elif table == "trunk_cables":
            target = at_endpoint("patch", values["panel_a_id"], values["port_a_start"])
        elif table in ("servers", "patch_panels", "rack_switch_placeholders", "cable_organizers", "rack_switches"):
            if values.get("rack_id") in rack_ids:
                target = {"rack_id": values["rack_id"], "side": values.get("side") or "front", "focus": None}
        elif table == "racks":
            if values.get("id") in rack_ids:
                target = {"rack_id": values["id"], "side": "front", "focus": None}
            elif values.get("server_room_id") in room_ids:
                target = {"room_id": values["server_room_id"]}
        elif table in ("server_rooms", "rack_view_order", "rack_view_slots"):
            room_id = values.get("id") if table == "server_rooms" else values.get("server_room_id")
            if room_id in room_ids:
                target = {"room_id": room_id}

        if target:
            return target
    return None

