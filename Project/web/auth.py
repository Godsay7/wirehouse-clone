"""Sign-in for the web UI: everyone may look, only signed-in users may change.

* Every GET page is open. Any other method (POST / PATCH / DELETE — all the
  changes go through them) needs a signed-in user; otherwise the answer is
  401 with {"login_required": true} for scripts and htmx, or a redirect to
  /login for a plain form. static/js/auth.js shows "Sign in to make changes"
  before such a request is even sent.
* The session is Flask's signed cookie: the user's name and a fingerprint of
  the password hash (a new password signs out every browser).
* Changes must come from this site (Origin / Referer), so another site
  cannot post a form with the user's cookie.
"""

import os
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from flask import current_app, g, jsonify, redirect, request, session, url_for

from .. import settings
from ..bll.services.auth import LocalUsers, LoginThrottle

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Changes that do not need a signed-in user.
OPEN_ENDPOINTS = {"auth.login", "auth.logout"}

LOGIN_REQUIRED_MESSAGE = "Sign in to make changes"


def init_app(app, users_file=None):
    app.secret_key = _secret_key(app)
    app.config.update(
        SESSION_COOKIE_NAME="wirehouse_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=settings.SESSION_HOURS),
    )
    app.extensions["auth_users"] = LocalUsers(users_file or settings.USERS_FILE)
    app.extensions["auth_throttle"] = LoginThrottle()

    if not app.extensions["auth_users"].users():
        app.logger.warning(
            "No users in %s: nobody can sign in, the site is read-only "
            "(add one with scripts/set_password.py)", users_file or settings.USERS_FILE,
        )

    @app.before_request
    def load_user():
        g.user = current_user()

    @app.before_request
    def require_login_for_changes():
        if request.method in SAFE_METHODS or request.endpoint in OPEN_ENDPOINTS:
            return None
        if not same_origin():
            return _refuse(403, "The request did not come from this site")
        if g.user:
            return None
        return _refuse(401, LOGIN_REQUIRED_MESSAGE, login=True)

    @app.context_processor
    def auth_globals():
        return {"current_user": g.get("user"), "can_edit": bool(g.get("user"))}


def users():
    return current_app.extensions["auth_users"]


def throttle():
    return current_app.extensions["auth_throttle"]


def current_user():
    """The signed-in user's name, or None. A removed user or a changed
    password ends the session."""

    name = session.get("user")
    if not name:
        return None
    if session.get("pw") != users().fingerprint(name):
        session.clear()
        return None
    return name


def sign_in(name):
    session.clear()
    session.permanent = True
    session["user"] = name
    session["pw"] = users().fingerprint(name)


def sign_out():
    session.clear()


def safe_next(target, default="/"):
    """Only paths on this site: never "//evil.example" or "https://…"."""

    target = (target or "").strip()
    parts = urlsplit(target)
    if not target.startswith("/") or target.startswith("//") or parts.scheme or parts.netloc or "\\" in target:
        return default
    return target


def same_origin():
    """A change must come from a page of this site. Browsers send Origin
    with every POST / PATCH / DELETE from fetch, htmx and forms; Referer is
    the fallback. Requests with neither (scripts, tests) are allowed."""

    source = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if not source or source == "null":
        return not source
    return urlsplit(source).netloc.lower() == (request.host or "").lower()


def wants_json():
    if request.headers.get("HX-Request") == "true" or request.is_json:
        return True
    accept = request.accept_mimetypes
    return accept.best == "application/json" or (
        accept["application/json"] > 0 and accept["application/json"] >= accept["text/html"]
    )


def _refuse(status, message, login=False):
    if login and not wants_json():
        # A plain form: show the sign-in page, then back to where it was.
        referrer = request.referrer or ""
        parts = urlsplit(referrer)
        back = safe_next((parts.path or "/") + (f"?{parts.query}" if parts.query else "")) \
            if parts.netloc.lower() == (request.host or "").lower() else "/"
        return redirect(url_for("auth.login", next=back), code=303)

    from .i18n import translate_message

    response = jsonify({"ok": False, "error": translate_message(message), "login_required": login})
    response.status_code = status
    if login:
        response.headers["X-Login-Required"] = "1"
    return response


def _secret_key(app):
    if settings.SECRET_KEY:
        return settings.SECRET_KEY

    path = settings.SECRET_KEY_FILE
    try:
        with open(path, encoding="utf-8") as handle:
            key = handle.read().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    except OSError as exc:
        app.logger.warning("Cannot read %s: %s", path, exc)

    key = secrets.token_hex(32)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(key + "\n")
    except FileExistsError:
        # Another process wrote it first: use that one.
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip() or key
    except OSError as exc:
        # Still works, but every restart signs everybody out.
        app.logger.warning("Cannot save the session key to %s: %s", path, exc)
    return key
