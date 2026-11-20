"""Home page at / (the logo links here): status, problems, recent changes, sections."""

from flask import Blueprint, redirect, render_template, request, url_for

from ...core.text import format_datetime
from ..helpers import services

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    # Old links and bookmarks to the dashboard search ("/?search=...").
    if request.args.get("search"):
        return redirect(url_for("dashboard.index", search=request.args["search"]))

    return render_template("home.html", format_datetime=format_datetime, **services().home.overview())


@bp.route("/home")
def old_home():
    return redirect(url_for("home.index"), code=301)
