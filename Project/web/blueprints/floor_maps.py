"""Floor Maps: page with the map editor and its JSON API."""

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from ...bll.errors import NotFoundError, ValidationError
from ..helpers import services

bp = Blueprint("floor_maps", __name__)


@bp.route("/floor-maps")
def home():
    maps = services().floor_maps.list_maps()

    if maps:
        return redirect(url_for("floor_maps.view", map_id=maps[0]["id"]))

    return render_template("floor_maps.html", maps=[], data=None)


@bp.route("/floor-maps/<int:map_id>")
def view(map_id):
    floor_maps = services().floor_maps
    data = floor_maps.map_data(map_id)

    return render_template("floor_maps.html", maps=floor_maps.list_maps(), data=data)


# ------------------------------------------------------------
# JSON API
# ------------------------------------------------------------

def json_api(view_function):
    """Turn service errors into {"ok": false, "error": ...} responses."""

    @wraps(view_function)
    def wrapper(*args, **kwargs):
        try:
            result = view_function(*args, **kwargs)
        except ValidationError as exc:
            return jsonify({"ok": False, "error": exc.message}), 400
        except NotFoundError as exc:
            return jsonify({"ok": False, "error": exc.message or "Not found"}), 404

        return jsonify({"ok": True, **(result or {})})

    return wrapper


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object")
    return data


@bp.route("/floor-maps/api/maps/<int:map_id>")
@json_api
def api_map(map_id):
    return services().floor_maps.map_data(map_id)


@bp.route("/floor-maps/api/maps", methods=["POST"])
@json_api
def api_create_map():
    map_id = services().floor_maps.create_map(payload().get("name"))
    return {"id": map_id, "url": url_for("floor_maps.view", map_id=map_id)}


@bp.route("/floor-maps/api/maps/order", methods=["POST"])
@json_api
def api_reorder_maps():
    services().floor_maps.reorder_maps(payload().get("map_ids"))


@bp.route("/floor-maps/api/maps/<int:map_id>", methods=["PATCH"])
@json_api
def api_update_map(map_id):
    services().floor_maps.update_map(map_id, payload())


@bp.route("/floor-maps/api/maps/<int:map_id>", methods=["DELETE"])
@json_api
def api_delete_map(map_id):
    services().floor_maps.delete_map(map_id)
    return {"url": url_for("floor_maps.home")}


@bp.route("/floor-maps/api/maps/<int:map_id>/move", methods=["POST"])
@json_api
def api_move(map_id):
    data = payload()
    services().floor_maps.move(map_id, data.get("rooms", []), data.get("workplaces", []))


@bp.route("/floor-maps/api/maps/<int:map_id>/rooms", methods=["POST"])
@json_api
def api_create_room(map_id):
    return {"id": services().floor_maps.create_room(map_id, payload())}


@bp.route("/floor-maps/api/rooms/<int:room_id>", methods=["PATCH"])
@json_api
def api_update_room(room_id):
    services().floor_maps.update_room(room_id, payload())


@bp.route("/floor-maps/api/rooms/<int:room_id>", methods=["DELETE"])
@json_api
def api_delete_room(room_id):
    services().floor_maps.delete_room(room_id)


@bp.route("/floor-maps/api/maps/<int:map_id>/workplaces", methods=["POST"])
@json_api
def api_create_workplace(map_id):
    return {"id": services().floor_maps.create_workplace(map_id, payload())}


@bp.route("/floor-maps/api/workplaces/<int:workplace_id>", methods=["PATCH"])
@json_api
def api_update_workplace(workplace_id):
    services().floor_maps.update_workplace(workplace_id, payload())


@bp.route("/floor-maps/api/maps/<int:map_id>/fill-sockets", methods=["POST"])
@json_api
def api_fill_sockets(map_id):
    """Set the suggested wall socket on every workplace of the map that has none."""

    return {"filled": services().floor_maps.fill_sockets(map_id)}


@bp.route("/floor-maps/api/workplaces/<int:workplace_id>", methods=["DELETE"])
@json_api
def api_delete_workplace(workplace_id):
    services().floor_maps.delete_workplace(workplace_id)
