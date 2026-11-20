"""Change History built from port_history snapshots."""

import re

from flask import Blueprint, redirect, render_template, request, url_for

from ...bll.domain.change_history import short_change_value
from ...core.text import format_datetime
from ...bll.errors import NotFoundError, ValidationError
from ..helpers import services, to_int

bp = Blueprint("changes", __name__)


@bp.route("/changes")
def index():
    search = request.args.get("search", "").strip()

    return render_template(
        "changes.html",
        rows=services().inventory.change_history(search),
        search=search,
        format_datetime=format_datetime,
        short_change_value=short_change_value,
    )


@bp.route("/changes/racks")
def racks():
    """Who changed what in Rack Change (cables, equipment, notes), with undo."""

    return render_template(
        "rack_history.html",
        format_datetime=format_datetime,
        message=request.args.get("message", ""),
        error=request.args.get("error", ""),
        **services().rack_history.history(
            before=to_int(request.args.get("before")) or None,
            filters={
                "text": request.args.get("q", "").strip(),
                "room_id": to_int(request.args.get("room")) or None,
                "user": request.args.get("user", "").strip(),
                "since": _date(request.args.get("since")),
                "until": _date(request.args.get("until")),
            },
        ),
    )


@bp.route("/changes/racks/<int:audit_id>/undo", methods=["POST"])
def undo_rack_change(audit_id):
    try:
        undo_id = services().rack_history.undo(audit_id)
    except (ValidationError, NotFoundError) as exc:
        return redirect(url_for("changes.racks", error=exc.message))
    return redirect(url_for("changes.racks", message=f"Change #{audit_id} undone (#{undo_id})."))


def _date(value):
    """'2026-11-17' or None (a date from an <input type="date">)."""

    value = (value or "").strip()
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None
