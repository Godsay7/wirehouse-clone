"""Dashboard: all switches, port statistics and inventory search."""

from flask import Blueprint, jsonify, render_template, request, url_for

from ...bll.domain.freshness import minutes_ago
from ...core.text import format_datetime
from .. import i18n
from ..helpers import rack_url, services

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
def index():
    search = request.args.get("search", "").strip()
    errors_only = request.args.get("errors") == "1"
    data = services().inventory.dashboard(search, errors_only=errors_only)

    return render_template(
        "index.html",
        search=search,
        errors_only=errors_only,
        format_datetime=format_datetime,
        minutes_ago=minutes_ago,
        **data,
    )


@bp.route("/search/suggest")
def suggest():
    """Quick matches for the search box on the home page (JSON)."""

    search = request.args.get("q", "").strip()
    found = services().inventory.suggest(search)
    items = []
    for row in found["docs"]:
        if row.get("map_id"):
            href = url_for("floor_maps.view", map_id=row["map_id"], search=row["title"])
        elif row.get("rack_id"):
            href = rack_url(row["rack_id"], row.get("side"), row.get("element_id"))
        else:
            href = url_for("dashboard.index", search=row["title"])
        where = " / ".join(str(part) for part in (row.get("room"), row.get("rack")) if part)
        items.append({
            "kind": i18n.gettext(row["kind"]),
            "label": i18n.translate_message(row["title"]),
            "detail": " · ".join(part for part in (i18n.translate_message(row.get("text") or ""), i18n.translate_message(where)) if part and part != "-"),
            "href": href,
        })
    for port in found["ports"]:
        detail = [value for value in (port.get("device"), port.get("ip_display"), port.get("hostname_display"),
                                      port.get("vlan_text") and f"VLAN {port['vlan_text']}") if value and value != "-"]
        items.append({
            "kind": i18n.gettext("Switch port"),
            "label": f"{port['switch_name']} {port.get('if_name') or port.get('port')}",
            "detail": " · ".join(detail),
            "href": url_for("switches.view", switch_id=port["switch_id"], search=port.get("if_name") or port.get("port")),
        })
    return jsonify({
        "query": search,
        "items": items,
        "all": url_for("dashboard.index", search=search) if search else None,
    })
