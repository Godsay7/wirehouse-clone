"""Sign in / sign out (the person icon in the header). See web/auth.py."""

from flask import Blueprint, current_app, g, redirect, render_template, request, url_for

from .. import auth
from ..i18n import gettext as _

bp = Blueprint("auth", __name__)


def _client_key():
    from .. import client_ip

    return client_ip() or "?"


@bp.route("/login", methods=["GET", "POST"])
def login():
    target = auth.safe_next(request.values.get("next"))
    if g.get("user") and request.method == "GET":
        return redirect(target)

    error = None
    name = ""
    status = 200
    if request.method == "POST":
        name = (request.form.get("username") or "").strip()
        key = _client_key()
        if not auth.same_origin():
            error, status = _("The request did not come from this site"), 403
        elif auth.throttle().blocked(key):
            error, status = _("Too many failed attempts. Try again in a few minutes."), 429
        else:
            user = auth.users().authenticate(name, request.form.get("password") or "")
            if user:
                auth.throttle().succeeded(key)
                auth.sign_in(user)
                current_app.logger.info("Signed in: %s from %s", user, key)
                return redirect(target, code=303)
            auth.throttle().failed(key)
            current_app.logger.warning("Failed sign-in as %r from %s", name, key)
            error, status = _("Wrong user name or password"), 401

    return render_template("login.html", error=error, username=name, next=target), status


@bp.route("/logout", methods=["POST"])
def logout():
    if g.get("user"):
        current_app.logger.info("Signed out: %s", g.user)
    auth.sign_out()
    return redirect(auth.safe_next(request.form.get("next")), code=303)
