"""One switch: front panel and port table."""

from flask import Blueprint, abort, jsonify, render_template, request

from ...core.text import format_datetime
from ...bll.errors import NotFoundError, ValidationError
from ..helpers import services, to_int

bp = Blueprint("switches", __name__)


@bp.route("/switch/<int:switch_id>")
def view(switch_id):
    search = request.args.get("search", "").strip()
    data = services().inventory.switch_page(switch_id, search)

    return render_template(
        "switch.html",
        search=search,
        format_datetime=format_datetime,
        **data,
    )


@bp.route("/switch/<int:switch_id>/port/<int:port>")
def port_history(switch_id, port):
    """Everything that happened on one port: link, speed, VLAN, devices,
    errors and Rack History changes of its cables, note and name."""

    try:
        data = services().port_history.history(switch_id, port, before=request.args.get("before") or None)
    except NotFoundError:
        abort(404)
    return render_template("port_history.html", format_datetime=format_datetime, **data)


@bp.route("/hosts/name", methods=["POST"])
def set_host_name():
    """Hostname typed in by hand for a device (JSON {mac, name}; empty name removes it)."""

    payload = request.get_json(silent=True) or {}
    try:
        saved = services().inventory.set_host_name(payload.get("mac", ""), payload.get("name", ""))
    except ValidationError as exc:
        return jsonify({"ok": False, "error": exc.message}), 400
    return jsonify({"ok": True, **saved})


@bp.route("/ports/name", methods=["POST"])
def set_port_name():
    """Name of a switch port typed in by hand (JSON {switch_id, port, name}; empty name removes it)."""

    payload = request.get_json(silent=True) or {}
    try:
        saved = services().inventory.set_port_name(to_int(payload.get("switch_id")), to_int(payload.get("port")),
                                                   payload.get("name", ""))
    except ValidationError as exc:
        return jsonify({"ok": False, "error": exc.message}), 400
    except NotFoundError as exc:
        return jsonify({"ok": False, "error": exc.message}), 404
    return jsonify({"ok": True, **saved})
