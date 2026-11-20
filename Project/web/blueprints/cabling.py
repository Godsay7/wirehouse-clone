"""JSON API used by the rack editor scripts: cables and port descriptions."""

from flask import Blueprint, jsonify, request

from ...bll.errors import NotFoundError, ReplaceRequired, ValidationError
from ..helpers import services

bp = Blueprint("cabling", __name__)

# JSON field names of each endpoint type: (id field, port field).
ENDPOINT_FIELDS = {
    "switch": ("switch_id", "switch_port"),
    "patch": ("patch_panel_id", "patch_port"),
    "server": ("server_id", "server_port"),
    "placeholder": ("placeholder_id", "placeholder_port"),
}


def parse_endpoint(endpoint):
    """{"type": "patch", "patch_panel_id": 3, "patch_port": 7} -> ("patch", 3, 7)."""

    endpoint_type = endpoint.get("type")

    if endpoint_type not in ENDPOINT_FIELDS:
        return None, 0, 0

    id_field, port_field = ENDPOINT_FIELDS[endpoint_type]
    return endpoint_type, int(endpoint.get(id_field, 0)), int(endpoint.get(port_field, 0))


@bp.route("/rack/connect", methods=["POST"])
def connect():
    payload = request.get_json(silent=True) or {}

    ep1 = payload.get("first_endpoint")
    ep2 = payload.get("second_endpoint")

    if not ep1 or not ep2:
        return jsonify({"ok": False, "error": "Invalid endpoints"}), 400

    endpoint_a = parse_endpoint(ep1)
    endpoint_b = parse_endpoint(ep2)

    if not endpoint_a[0] or not endpoint_b[0]:
        return jsonify({"ok": False, "error": "Unknown endpoint types"}), 400

    try:
        connection_id = services().cabling.connect(endpoint_a, endpoint_b, replace=bool(payload.get("replace")))
    except ReplaceRequired as exc:
        # The browser asks the user, then repeats the request with "replace": true.
        return jsonify({"ok": False, "needs_confirm": True, "error": exc.message, "conflicts": exc.conflicts}), 409
    except ValidationError as exc:
        return jsonify({"ok": False, "error": exc.message}), 400

    return jsonify({"ok": True, "connection_id": connection_id})


@bp.route("/rack/path")
def cable_path():
    """Full path of the cable through one port: ?type=patch&id=3&port=7."""

    endpoint_type = request.args.get("type", "")

    if endpoint_type not in ENDPOINT_FIELDS:
        return jsonify({"ok": False, "error": "Unknown endpoint type"}), 400

    try:
        endpoint = (endpoint_type, int(request.args.get("id", "")), int(request.args.get("port", "")))
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid endpoint"}), 400

    try:
        path = services().cabling.trace_path(endpoint)
    except NotFoundError as exc:
        return jsonify({"ok": False, "error": exc.message}), 404

    return jsonify({"ok": True, **path})


@bp.route("/rack/port/description", methods=["POST"])
def port_description():
    payload = request.get_json(silent=True) or {}
    endpoint = payload.get("endpoint")
    description = payload.get("description", "").strip()

    if not endpoint:
        return jsonify({"ok": False, "error": "Invalid endpoint"}), 400

    try:
        endpoint_type, endpoint_id, port = parse_endpoint(endpoint)
        services().cabling.set_port_description(endpoint_type, endpoint_id, port, description)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True})


@bp.route("/rack/disconnect/<connection_ref>", methods=["POST"])
def disconnect(connection_ref):
    try:
        services().cabling.disconnect(connection_ref)
    except ValidationError as exc:
        return jsonify({"ok": False, "error": exc.message}), 400

    return jsonify({"ok": True})
