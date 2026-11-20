"""Cable checklist (services/checklist.py): for every signed-in user.

A visitor who has not signed in gets 404, as if the page did not exist.
"""

from flask import Blueprint, abort, g, jsonify, render_template, request

from ...bll.errors import NotFoundError, ValidationError
from ...core.text import format_datetime
from ..helpers import services, to_int

bp = Blueprint("checklist", __name__)


def checklist_allowed():
    return bool(g.get("user"))


@bp.before_request
def only_its_users():
    if not checklist_allowed():
        abort(404)


@bp.route("/checklist")
def index():
    rows = services().checklist.rows()
    return render_template("checklist.html", rows=rows, format_datetime=format_datetime)


@bp.route("/checklist/port", methods=["POST"])
def mark():
    """JSON {switch_id, port, field: confirmed | shorter | tidy | note, value}."""

    payload = request.get_json(silent=True) or {}
    switch_id, port = to_int(payload.get("switch_id")), to_int(payload.get("port"))
    if switch_id is None or port is None:
        return jsonify({"ok": False, "error": "Invalid switch port"}), 400
    try:
        row = services().checklist.mark(switch_id, port, payload.get("field"), payload.get("value"), g.user)
    except ValidationError as exc:
        return jsonify({"ok": False, "error": exc.message}), 400
    except NotFoundError as exc:
        return jsonify({"ok": False, "error": exc.message}), 404
    return jsonify({"ok": True, "row": {**row, "confirmed_at": format_datetime(row["confirmed_at"]) if row["confirmed_at"] else ""}})
