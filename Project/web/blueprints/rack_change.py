"""Rack Change: rack editor page, server rooms and racks."""

from flask import Blueprint, g, make_response, redirect, render_template, request, url_for

from ...bll.errors import NotFoundError, ValidationError
from ..helpers import preferred_room_id, redirect_to_rack, remember_room, services, side_from

bp = Blueprint("rack_change", __name__)


def _redirect_home(side, room_id=None, error=None):
    # url_for drops None values; falsy room ids are not sent.
    return redirect(
        url_for(
            "rack_change.home",
            room_id=room_id or None,
            side=side,
            error=error or None,
        )
    )


@bp.before_request
def signed_in_only():
    """A visitor never sees the editor: a rack opens in Rack View instead,
    the editor's start page asks to sign in (web/auth.py)."""

    if g.get("user"):
        return None
    if request.endpoint == "rack_change.view":
        args = {key: value for key, value in request.args.items() if key in ("side", "focus")}
        return redirect(url_for("rack_view.open_rack", rack_id=request.view_args["rack_id"], **args))
    if request.endpoint == "rack_change.home":
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
    return None


@bp.route("/rack-change")
def home():
    """Open the first rack of the selected room, or the empty-room page."""

    current_side = side_from(request.args)
    rooms, selected_room, room_racks = services().rack_view.rooms_and_selection(
        preferred_room_id(request)
    )
    selected_room_id = selected_room["id"] if selected_room else None

    if room_racks:
        response = make_response(redirect_to_rack(room_racks[0]["id"], current_side))
        if selected_room_id:
            remember_room(response, selected_room_id)
        return response

    response = make_response(
        render_template(
            "rack_change.html",
            rack=None,
            server_rooms=rooms,
            selected_room=selected_room,
            racks=room_racks,
            rack_rows=[],
            rack_switches=[],
            patch_panels=[],
            cable_organizers=[],
            connections=[],
            available_switches=[],
            current_side=current_side,
            error=request.args.get("error", ""),
        )
    )
    return remember_room(response, selected_room_id)


@bp.route("/rack-change/<int:rack_id>")
def view(rack_id):
    current_side = side_from(request.args)
    data = services().rack_view.editor(rack_id, current_side)
    data["error"] = request.args.get("error", "")

    response = make_response(render_template("rack_change.html", **data))
    return remember_room(response, data["rack"]["server_room_id"])


# ------------------------------------------------------------
# Server rooms
# ------------------------------------------------------------

@bp.route("/rack/server-room/create", methods=["POST"])
def create_room():
    current_side = side_from(request.form)

    try:
        room_id = services().rack_admin.create_room(request.form.get("name"))
    except ValidationError as exc:
        return _redirect_home(current_side, error=exc.message)

    return _redirect_home(current_side, room_id=room_id)


@bp.route("/rack/server-room/<int:room_id>/delete", methods=["POST"])
def delete_room(room_id):
    """Delete one server room and only its rack-layout metadata."""

    current_side = side_from(request.form)

    try:
        next_room_id = services().rack_admin.delete_room(room_id)
    except NotFoundError as exc:
        return _redirect_home(current_side, error=exc.message)

    response = make_response(_redirect_home(current_side, room_id=next_room_id))
    return remember_room(response, next_room_id)


# ------------------------------------------------------------
# Racks
# ------------------------------------------------------------

@bp.route("/rack/create", methods=["POST"])
def create_rack():
    current_side = side_from(request.form)

    try:
        server_room_id = int(request.form.get("server_room_id") or 0)
        units = int(request.form.get("units") or 42)
    except ValueError:
        server_room_id = 0
        units = 42

    try:
        rack_id = services().rack_admin.create_rack(
            server_room_id,
            request.form.get("name"),
            units,
        )
    except ValidationError as exc:
        return _redirect_home(current_side, room_id=server_room_id, error=exc.message)

    return redirect_to_rack(rack_id, current_side)


@bp.route("/rack/<int:rack_id>/width", methods=["POST"])
def rack_width(rack_id):
    current_side = side_from(request.form)
    try:
        services().rack_admin.set_rack_width(rack_id, int(request.form.get("width_percent") or 100))
    except (ValueError, ValidationError, NotFoundError) as exc:
        return redirect_to_rack(rack_id, current_side, error=getattr(exc, "message", "Unknown rack width"))
    return redirect_to_rack(rack_id, current_side)


@bp.route("/rack/<int:rack_id>/delete", methods=["POST"])
def delete_rack(rack_id):
    current_side = side_from(request.form)

    try:
        server_room_id, next_rack_id = services().rack_admin.delete_rack(rack_id)
    except NotFoundError as exc:
        return _redirect_home(current_side, error=exc.message)

    if next_rack_id:
        return redirect_to_rack(next_rack_id, current_side)

    return _redirect_home(current_side, room_id=server_room_id)
