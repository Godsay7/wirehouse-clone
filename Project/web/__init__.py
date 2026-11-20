"""Presentation layer: Flask application factory."""

import gzip
import os
import sqlite3
import time

from flask import Flask, g, request

from .. import settings
from . import auth, i18n
from ..core.actor import reset_actor, set_actor
from ..bll.errors import NotFoundError
from ..bll.services import Services
from ..dal import Database
from .assets import CSS_BUNDLES, compute_asset_version
from .blueprints import BLUEPRINTS
from .helpers import rack_url

# Requests that must work even before the tables exist.
SCHEMA_FREE_ENDPOINTS = {"static", "favicon", "health.index", "api.version", "language.catalog", "language.switch", "auth.login", "auth.logout"}

STARTUP_SCHEMA_ATTEMPTS = 5
STARTUP_SCHEMA_RETRY_SECONDS = 2


# Requests through nginx on this server (deploy/nginx/wirehouse.conf) come
# from the loopback address; nginx passes the real client in X-Real-IP.
LOCAL_PROXY_ADDRESSES = {"127.0.0.1", "::1"}


def client_ip():
    """The browser's address. X-Real-IP is trusted only from the local nginx:
    a request straight to :8080 from another machine cannot fake it."""

    address = request.remote_addr or ""
    forwarded = (request.headers.get("X-Real-IP") or "").strip()
    if address in LOCAL_PROXY_ADDRESSES and forwarded:
        return forwarded
    return address


class LocalProxyScheme:
    """WSGI middleware: behind the local nginx, take http/https from
    X-Forwarded-Proto so redirects and absolute URLs keep the browser's
    scheme. Ignored for requests that do not come from this server."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        proto = (environ.get("HTTP_X_FORWARDED_PROTO") or "").strip().lower()
        if environ.get("REMOTE_ADDR") in LOCAL_PROXY_ADDRESSES and proto in ("http", "https"):
            environ["wsgi.url_scheme"] = proto
        return self.wsgi_app(environ, start_response)


def create_app(database_path=None, users_file=None):
    app = Flask(__name__)
    app.wsgi_app = LocalProxyScheme(app.wsgi_app)

    services = Services.create(
        Database(database_path or settings.DB_PATH)
    )
    app.extensions["services"] = services

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    # Tables are created/migrated at startup. If the database is missing or
    # busy then, the first request retries instead of failing forever.
    schema = {"ready": _ensure_schema_at_startup(app, services)}

    @app.before_request
    def choose_language():
        g.lang = i18n.choose_language()

    # Sign-in (web/auth.py): after the language (its refusals are translated),
    # before the actor (the history records who was signed in).
    auth.init_app(app, users_file)

    @app.before_request
    def remember_actor():
        # Recorded in the rack change history: client address and the action.
        g.actor_token = set_actor(
            ip=client_ip(),
            user=g.get("user") or "",
            action=f"{request.method} {request.path}",
        )

    @app.teardown_request
    def forget_actor(_error=None):
        token = g.pop("actor_token", None)
        if token is not None:
            reset_actor(token)

    @app.before_request
    def ensure_schema():
        if schema["ready"] or request.endpoint in SCHEMA_FREE_ENDPOINTS:
            return

        services.ensure_schema()
        schema["ready"] = True

    # Globals, not context: imported macros (render_rack, switch/_macros) use them too.
    app.jinja_env.globals["_"] = i18n.gettext
    app.jinja_env.globals["_n"] = i18n.ngettext
    app.jinja_env.filters["tr"] = i18n.translate_message
    # Opens a rack: Rack Change when signed in, else Rack View (web/helpers.py).
    app.jinja_env.globals["rack_url"] = rack_url

    asset_version = compute_asset_version(
        app.static_folder,
        os.path.join(os.path.dirname(__file__), "translations"),
    )

    @app.context_processor
    def template_globals():
        return {
            # Appended to static URLs: changes whenever a static file or the
            # translations change, so browsers reload CSS/JS after a deploy.
            "asset_version": asset_version,
            "css_bundles": CSS_BUNDLES,
            # Baseline for live.js: parts of the page refresh when these grow.
            "data_versions": services.data_versions(),
            "is_htmx": request.headers.get("HX-Request") == "true",
            # The cable checklist (blueprints/checklist.py): for signed-in users.
            "checklist_allowed": bool(g.get("user")),
            # Light / dark theme chosen with the button in the header ("" = the system's).
            "theme": request.cookies.get("theme") if request.cookies.get("theme") in ("light", "dark") else "",
            # Interface language (web/i18n.py): _("Text") and {{ message|tr }}.
            "lang": i18n.current_language(),
            "languages": i18n.LANGUAGES,
        }

    @app.route("/favicon.ico")
    def favicon():
        # Browsers ask for /favicon.ico on their own (bookmarks, tabs restored
        # without the page). Cache it for a day.
        return app.send_static_file("img/favicon.ico"), 200, {
            "Cache-Control": "public, max-age=86400",
        }

    @app.errorhandler(404)
    @app.errorhandler(NotFoundError)
    def not_found(_error):
        return "Page not found", 404

    app.after_request(compress_response)
    return app


# Text is sent gzipped when the browser accepts it: a Rack View page is
# mostly repeated rack markup and shrinks about tenfold.
COMPRESSIBLE_TYPES = {"text/html", "text/css", "text/plain", "application/javascript",
                      "text/javascript", "application/json", "image/svg+xml"}
COMPRESS_MIN_BYTES = 1024


def compress_response(response):
    if (response.status_code != 200
            or response.mimetype not in COMPRESSIBLE_TYPES
            or "Content-Encoding" in response.headers
            or "gzip" not in request.headers.get("Accept-Encoding", "").lower()):
        return response

    response.direct_passthrough = False          # static files: read the body
    body = response.get_data()
    if len(body) < COMPRESS_MIN_BYTES:
        return response
    response.set_data(gzip.compress(body, compresslevel=6))
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(response.get_data()))
    response.vary.add("Accept-Encoding")
    return response


def _ensure_schema_at_startup(app, services):
    for attempt in range(1, STARTUP_SCHEMA_ATTEMPTS + 1):
        try:
            services.ensure_schema()
            return True
        except sqlite3.OperationalError as exc:
            # Usually "database is locked" while the collector is writing.
            app.logger.warning("Schema check attempt %s failed: %s", attempt, exc)
            time.sleep(STARTUP_SCHEMA_RETRY_SECONDS)
        except RuntimeError as exc:
            # Database file does not exist yet.
            app.logger.warning("Schema check skipped: %s", exc)
            return False

    return False
