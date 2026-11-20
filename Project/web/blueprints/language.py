"""Interface language: the switcher in the header and the catalog for JS."""

from urllib.parse import urlsplit

from flask import Blueprint, Response, redirect, request

from ... import settings
from .. import i18n

bp = Blueprint("language", __name__)


@bp.route("/lang/<code>")
def switch(code):
    """Remember the language and go back to the page (only paths on this site)."""

    target = request.args.get("next") or "/"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/"):
        target = "/"
    response = redirect(target)
    if code in i18n.LANGUAGES:
        response.set_cookie(i18n.COOKIE, code, max_age=i18n.COOKIE_MAX_AGE, samesite="Lax")
    return response


@bp.route("/i18n/<code>.js")
def catalog(code):
    response = Response(i18n.javascript_catalog(code), mimetype="application/javascript")
    # The URL carries the build number, so browsers may keep it.
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response
