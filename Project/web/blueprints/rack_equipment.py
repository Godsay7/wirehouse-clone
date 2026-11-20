"""Rack Change forms that add or remove rack equipment.

Every handler redirects back to the rack editor; validation errors are shown
there through the ``error`` query parameter.
"""

from functools import wraps

from flask import Blueprint, Response, abort, jsonify, request

from ...bll.errors import NotFoundError, ValidationError
from ..helpers import redirect_to_rack, services, side_from

bp = Blueprint("equipment", __name__)


def _int_fields(form, defaults):
    """Parse several integer form fields; any invalid value resets all of them."""

    try:
        return [int(form.get(name) or default) for name, default in defaults]
    except ValueError:
        return [default for _, default in defaults]


def back_to_rack(side_source):
    """Run the action, then redirect to the rack editor (with error, if any).

    side_source: "form" or "args" — where this form sends the current side.
    """

    def decorator(action):
        @wraps(action)
        def wrapper(rack_id, **kwargs):
            values = request.form if side_source == "form" else request.args
            current_side = side_from(values)

            try:
                action(rack_id, current_side, **kwargs)
            except ValidationError as exc:
                return redirect_to_rack(rack_id, current_side, error=exc.message)

            return redirect_to_rack(rack_id, current_side)

        return wrapper

    return decorator


# ------------------------------------------------------------
# Servers
# ------------------------------------------------------------

@bp.route("/rack/<int:rack_id>/server/add", methods=["POST"])
@back_to_rack("form")
def add_server(rack_id, side):
    top_unit, height_units, port_count = _int_fields(
        request.form,
        [("rack_unit", 0), ("height_units", 1), ("port_count", 0)],
    )

    services().rack_equipment.add_server(
        rack_id,
        request.form.get("name"),
        top_unit,
        height_units,
        port_count,
        side,
        request.form.get("depth", "full"),
    )


@bp.route("/rack/<int:rack_id>/server/<int:server_id>/depth", methods=["POST"])
@back_to_rack("args")
def server_depth(rack_id, side, server_id):
    services().rack_equipment.set_server_depth(rack_id, server_id, request.form.get("depth", "full"))


@bp.route("/rack/<int:rack_id>/server/<int:server_id>/image", methods=["POST"])
@back_to_rack("args")
def server_image(rack_id, side, server_id):
    if request.form.get("remove_image"):
        services().rack_equipment.remove_server_front_image(server_id)
        return

    file = request.files.get("image")
    if file and file.filename:
        services().rack_equipment.set_server_front_image(
            server_id,
            file.read(),
            file.content_type,
        )


@bp.route("/rack/server/<int:server_id>/front-image")
def server_front_image(server_id):
    """A server's front picture. Pages link it with ?v=<version>, so it is
    cached for a year; a new picture gets a new URL."""

    try:
        mime_type, content = services().rack_equipment.server_front_image(server_id)
    except NotFoundError:
        abort(404)
    response = Response(content, mimetype=mime_type)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@bp.route("/rack/<int:rack_id>/server/<int:server_id>/delete", methods=["POST"])
@back_to_rack("args")
def delete_server(rack_id, side, server_id):
    services().rack_equipment.delete_server(rack_id, server_id)


@bp.route("/rack/<int:rack_id>/server/<int:server_id>/port/add", methods=["POST"])
@back_to_rack("args")
def add_server_port(rack_id, side, server_id):
    services().rack_equipment.add_server_port(server_id)


@bp.route("/rack/<int:rack_id>/server/<int:server_id>/port/<int:port_number>/delete", methods=["POST"])
@back_to_rack("args")
def delete_server_port(rack_id, side, server_id, port_number):
    services().rack_equipment.delete_server_port(server_id, port_number)


# ------------------------------------------------------------
# SNMP switches
# ------------------------------------------------------------

@bp.route("/rack/<int:rack_id>/switch/add", methods=["POST"])
@back_to_rack("form")
def add_switch(rack_id, side):
    switch_id, rack_unit = _int_fields(
        request.form,
        [("switch_id", 0), ("rack_unit", 0)],
    )

    services().rack_equipment.mount_switch(rack_id, switch_id, rack_unit, side)


@bp.route("/rack/<int:rack_id>/switch/<int:switch_id>/remove", methods=["POST"])
@back_to_rack("args")
def remove_switch(rack_id, side, switch_id):
    services().rack_equipment.unmount_switch(rack_id, switch_id)


@bp.route("/rack/<int:rack_id>/switch/<int:switch_id>/mgmt-port", methods=["POST"])
@back_to_rack("args")
def switch_mgmt_port(rack_id, side, switch_id):
    """Show / remove the management port (mng) of a mounted switch."""

    services().rack_equipment.set_switch_mgmt_port(rack_id, switch_id, request.form.get("enabled") == "1")


def _move(action, rack_id, device_id):
    """Drag-and-drop in Rack Change (js/rack_move.js): JSON {"rack_unit": top U}."""

    payload = request.get_json(silent=True) or {}
    try:
        top_unit = int(payload.get("rack_unit"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid rack unit"}), 400
    try:
        action(rack_id, device_id, top_unit)
    except ValidationError as exc:
        return jsonify({"ok": False, "error": exc.message}), 400
    except NotFoundError as exc:
        return jsonify({"ok": False, "error": exc.message or "Not found"}), 404
    return jsonify({"ok": True})


@bp.route("/rack/<int:rack_id>/switch/<int:switch_id>/move", methods=["POST"])
def move_switch(rack_id, switch_id):
    return _move(services().rack_equipment.move_switch, rack_id, switch_id)


@bp.route("/rack/<int:rack_id>/switch-placeholder/<int:placeholder_id>/move", methods=["POST"])
def move_placeholder(rack_id, placeholder_id):
    return _move(services().rack_equipment.move_placeholder, rack_id, placeholder_id)


@bp.route("/rack/<int:rack_id>/server/<int:server_id>/move", methods=["POST"])
def move_server(rack_id, server_id):
    return _move(services().rack_equipment.move_server, rack_id, server_id)


@bp.route("/rack/<int:rack_id>/patch-panel/<int:panel_id>/move", methods=["POST"])
def move_patch_panel(rack_id, panel_id):
    return _move(services().rack_equipment.move_patch_panel, rack_id, panel_id)


@bp.route("/rack/<int:rack_id>/cable-organizer/<int:organizer_id>/move", methods=["POST"])
def move_organizer(rack_id, organizer_id):
    return _move(services().rack_equipment.move_organizer, rack_id, organizer_id)


# ------------------------------------------------------------
# Temporary switches
# ------------------------------------------------------------

@bp.route("/rack/<int:rack_id>/switch-placeholder/add", methods=["POST"])
@back_to_rack("form")
def add_placeholder(rack_id, side):
    """Add a visual temporary switch that is not present in SNMP inventory yet."""

    rack_unit, height_units, port_count = _int_fields(
        request.form,
        [("rack_unit", 0), ("height_units", 1), ("port_count", 24)],
    )

    services().rack_equipment.add_placeholder(
        rack_id,
        request.form.get("name"),
        request.form.get("model"),
        rack_unit,
        height_units,
        port_count,
        side,
    )


@bp.route("/rack/<int:rack_id>/switch-placeholder/<int:placeholder_id>/delete", methods=["POST"])
@back_to_rack("form")
def delete_placeholder(rack_id, side, placeholder_id):
    services().rack_equipment.delete_placeholder(rack_id, placeholder_id)


# ------------------------------------------------------------
# Patch panels
# ------------------------------------------------------------

@bp.route("/rack/<int:rack_id>/patch-panel/add", methods=["POST"])
@back_to_rack("form")
def add_patch_panel(rack_id, side):
    rack_unit, port_count = _int_fields(
        request.form,
        [("rack_unit", 0), ("port_count", 24)],
    )

    services().rack_equipment.add_patch_panel(
        rack_id,
        request.form.get("name"),
        rack_unit,
        port_count,
        request.form.get("patch_type"),
        side,
    )


@bp.route("/rack/<int:rack_id>/trunk/add", methods=["POST"])
@back_to_rack("form")
def add_trunk(rack_id, side):
    """Trunk cable from an ODF of this rack to any other ODF."""

    form = request.form
    services().cabling.add_trunk(
        form.get("panel_a_id"),
        form.get("port_a_start"),
        form.get("panel_b_id"),
        form.get("port_b_start"),
        form.get("port_count"),
        form.get("name"),
    )


@bp.route("/rack/<int:rack_id>/trunk/<int:trunk_id>/delete", methods=["POST"])
@back_to_rack("args")
def delete_trunk(rack_id, side, trunk_id):
    try:
        services().cabling.delete_trunk(trunk_id)
    except NotFoundError:
        pass


@bp.route("/rack/<int:rack_id>/patch-panel/<int:panel_id>/layout", methods=["POST"])
@back_to_rack("args")
def patch_panel_layout(rack_id, side, panel_id):
    """Ports in one row (1, 2, 3 …) or odd on top and even below (1 / 2, 3 / 4 …)."""

    try:
        services().rack_equipment.set_patch_panel_layout(rack_id, panel_id, request.form.get("port_layout", "row"))
    except NotFoundError:
        pass


@bp.route("/rack/<int:rack_id>/patch-panel/<int:panel_id>/delete", methods=["POST"])
@back_to_rack("args")
def delete_patch_panel(rack_id, side, panel_id):
    services().rack_equipment.delete_patch_panel(rack_id, panel_id)


# ------------------------------------------------------------
# Cable organizers
# ------------------------------------------------------------

@bp.route("/rack/<int:rack_id>/cable-organizer/add", methods=["POST"])
@back_to_rack("form")
def add_organizer(rack_id, side):
    rack_unit, height_units = _int_fields(
        request.form,
        [("rack_unit", 0), ("height_units", 1)],
    )

    services().rack_equipment.add_organizer(
        rack_id,
        request.form.get("name"),
        rack_unit,
        height_units,
        side,
    )


@bp.route("/rack/<int:rack_id>/cable-organizer/<int:organizer_id>/delete", methods=["POST"])
@back_to_rack("args")
def delete_organizer(rack_id, side, organizer_id):
    services().rack_equipment.delete_organizer(rack_id, organizer_id)
