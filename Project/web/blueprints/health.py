"""Health check for monitoring."""

from flask import Blueprint

from ..helpers import services

bp = Blueprint("health", __name__)


@bp.route("/health")
def index():
    try:
        return services().inventory.health()
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }, 500
