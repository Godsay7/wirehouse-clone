"""Small JSON endpoints used by live.js."""

from flask import Blueprint, jsonify

from ..helpers import services

bp = Blueprint("api", __name__)


@bp.route("/api/version")
def version():
    """Data version counters; the page refreshes its live parts when they change."""

    response = jsonify(services().data_versions())
    response.headers["Cache-Control"] = "no-store"
    return response
