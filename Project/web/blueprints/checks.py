"""Cabling Check: documented cabling vs what the switches see (LLDP/CDP, port descriptions,
another device on a port), and the cable journal export."""

import csv
import io

from flask import Blueprint, Response, g, redirect, render_template, request, url_for

from ...core.text import format_datetime, now_iso
from ...core.xlsx import build_xlsx

from .. import i18n
from ...bll.services.cabling_check import JOURNAL_TRANSLATED
from ..helpers import services, to_int

bp = Blueprint("checks", __name__)


@bp.route("/checks")
def index():
    return render_template("checks.html", format_datetime=format_datetime, **services().cabling_check.report())


@bp.route("/export/cable-journal.<fmt>")
def cable_journal(fmt):
    """Every switch port with its documented cable and live state, as .xlsx or .csv (?switch_id= for one switch).
    Only for signed-in users: a visitor is sent to the sign-in page first."""

    if not g.get("user"):
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    if fmt not in ("xlsx", "csv"):
        return Response("Unknown format", status=404)

    switch_id = to_int(request.args.get("switch_id")) or None
    header, widths, rows = services().cabling_check.cable_journal(switch_id)
    # In the interface language: the headers, and the texts the server writes
    # into the cable columns ("(temporary)", "path ends here" …).
    translated = [index for index, name in enumerate(header) if name in JOURNAL_TRANSLATED]
    rows = [[i18n.translate_message(value) if index in translated else value for index, value in enumerate(row)]
            for row in rows]
    header = [i18n.gettext(name) for name in header]
    stamp = now_iso()[:10]
    name = f"cable-journal-{rows[0][0] if switch_id and rows else 'all'}-{stamp}"

    if fmt == "xlsx":
        body = build_xlsx(header, rows, sheet_name="Cable journal", widths=widths)
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        # Excel opens UTF-8 with a BOM correctly; ';' is the list separator it expects here.
        text = io.StringIO()
        writer = csv.writer(text, delimiter=";", lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)
        body = "\ufeff" + text.getvalue()
        mimetype = "text/csv; charset=utf-8"

    return Response(body, mimetype=mimetype, headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})

