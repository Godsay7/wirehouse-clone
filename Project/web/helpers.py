"""Small request/response helpers shared by blueprints."""

from flask import current_app, g, redirect, url_for

from ..bll.domain.rack_units import normalize_rack_side

ROOM_COOKIE = "rack_server_room_id"
ROOM_COOKIE_MAX_AGE = 31536000  # one year


def services():
    return current_app.extensions["services"]


def to_int(value, default=0):
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def side_from(values):
    return normalize_rack_side(values.get("side"))


def preferred_room_id(request):
    """An explicitly selected room has priority; otherwise the last room used
    in this browser (cookie)."""

    requested_room_id = to_int(request.args.get("room_id"))
    remembered_room_id = to_int(request.cookies.get(ROOM_COOKIE))
    return requested_room_id or remembered_room_id


def remember_room(response, room_id):
    """Remember the selected server room in a cookie, or forget it."""

    if room_id:
        response.set_cookie(
            ROOM_COOKIE,
            str(room_id),
            max_age=ROOM_COOKIE_MAX_AGE,
            samesite="Lax",
        )
    else:
        response.delete_cookie(ROOM_COOKIE)

    return response


def rack_url(rack_id, side=None, focus=None):
    """Link that opens a rack at a port: Rack Change for a signed-in user,
    otherwise /rack/<id>, which opens it in Rack View (blueprints/rack_view.py)."""

    endpoint = "rack_change.view" if g.get("user") else "rack_view.open_rack"
    return url_for(endpoint, rack_id=rack_id, side=side or "front", focus=focus or None)


def redirect_to_rack(rack_id, side, error=None):
    """Back to the Rack Change editor, optionally showing an error message."""

    if error:
        return redirect(url_for("rack_change.view", rack_id=rack_id, side=side, error=error))

    return redirect(url_for("rack_change.view", rack_id=rack_id, side=side))
