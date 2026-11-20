"""Rack View: read-only board with every rack of one server room."""

from flask import Blueprint, g, jsonify, make_response, redirect, render_template, request, url_for

from ...bll.errors import NotFoundError, ValidationError

from ...bll.domain.rack_board import SLOT_COLUMNS
from ..helpers import preferred_room_id, remember_room, services, side_from

bp = Blueprint("rack_view", __name__)


@bp.route("/rack")
def home():
    data = services().rack_view.board(preferred_room_id(request))

    response = make_response(
        render_template(
            "rack_view.html",
            rack_slot_columns=SLOT_COLUMNS,
            **data,
        )
    )

    selected_room = data["selected_room"]
    return remember_room(response, selected_room["id"] if selected_room else None)


@bp.route("/rack/layout/order", methods=["POST"])
def layout_order():
    """Persist exact Rack View slot positions for one server room."""

    payload = request.get_json(silent=True) or {}

    try:
        server_room_id = int(payload.get("server_room_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid server_room_id"}), 400

    raw_slots = payload.get("slots")

    if isinstance(raw_slots, list):
        slots = services().rack_admin.save_board_slots(
            server_room_id, raw_slots, payload.get("slot_positions")
        )
        return jsonify({"ok": True, "slots": slots})

    raw_rack_ids = payload.get("rack_ids")
    if not isinstance(raw_rack_ids, list):
        return jsonify({"ok": False, "error": "slots must be a list"}), 400

    rack_ids = services().rack_admin.save_board_order(server_room_id, raw_rack_ids)
    return jsonify({"ok": True, "rack_ids": rack_ids})


@bp.route("/rack/layout/reset", methods=["POST"])
def layout_reset():
    """Reset one server room back to the default rack order."""

    payload = request.get_json(silent=True) or {}

    try:
        server_room_id = int(payload.get("server_room_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid server_room_id"}), 400

    services().rack_admin.reset_board_order(server_room_id)
    return jsonify({"ok": True})


@bp.route("/rack/<int:rack_id>")
def open_rack(rack_id):
    """Open a rack (at a port: ?side=&focus=). Links from the history, Check
    and search come here: a signed-in user gets Rack Change, a visitor Rack
    View with that rack opened (Rack Change is only for signed-in users)."""

    side = side_from(request.args)
    focus = request.args.get("focus") or None
    if g.get("user"):
        return redirect(url_for("rack_change.view", rack_id=rack_id, side=side, focus=focus))

    room_id = services().rack_view.rack_room_id(rack_id)
    if not room_id:
        return redirect(url_for("rack_view.home"))
    return redirect(url_for("rack_view.home", room_id=room_id, open=rack_id, side=side, focus=focus))



# ------------------------------------------------------------
# Board positions: remove empty ones, add / remove one empty slot
# ------------------------------------------------------------

def _room_id(payload):
    try:
        return int(payload.get("server_room_id") or 0)
    except (TypeError, ValueError):
        return 0


def _layout_action(action):
    payload = request.get_json(silent=True) or {}
    server_room_id = _room_id(payload)
    if not server_room_id:
        return jsonify({"ok": False, "error": "Invalid server_room_id"}), 400

    try:
        result = action(server_room_id, payload)
    except ValidationError as exc:
        return jsonify({"ok": False, "error": exc.message}), 400
    except NotFoundError as exc:
        return jsonify({"ok": False, "error": exc.message or "Not found"}), 404

    return jsonify({"ok": True, **(result or {})})


@bp.route("/rack/layout/remove-empty", methods=["POST"])
def layout_remove_empty():
    """Keep only positions that hold a rack (each rack stays in its row)."""

    return _layout_action(lambda room_id, _: services().rack_admin.remove_empty_slots(room_id))


@bp.route("/rack/layout/add-slot", methods=["POST"])
def layout_add_slot():
    """Add one empty position after the last one."""

    return _layout_action(
        lambda room_id, _: {"position": services().rack_admin.add_empty_slot(room_id)}
    )


@bp.route("/rack/layout/remove-slot", methods=["POST"])
def layout_remove_slot():
    """Remove one empty position."""

    def action(room_id, payload):
        try:
            position = int(payload.get("position"))
        except (TypeError, ValueError):
            raise ValidationError("Invalid position")
        services().rack_admin.remove_slot(room_id, position)

    return _layout_action(action)
