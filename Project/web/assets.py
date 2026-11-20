"""Static asset bundles. Order matters: later stylesheets override earlier ones."""

CSS_BUNDLES = {
    # Loaded on every page by base.html.
    "common": [
        # First: the design tokens (colours, type, shape) the others use.
        "css/common/tokens.css",
        "css/common/base.css",
        "css/common/switch-panel.css",
        "css/common/change-history.css",
        "css/common/port-ip-hostname.css",
        "css/common/port-panel.css",
        "css/common/port-panel-compact.css",
        "css/common/port-panel-fixes.css",
        "css/common/auth.css",
    ],
    # Rack View and Rack Change.
    "rack": [
        "css/rack/rack.css",
        "css/rack/rack-cisco-4900m.css",
        # Rack View: the board of racks and the opened rack.
        "css/rack/rack-view.css",
        # Rack Change: zoom buttons, narrow screens.
        "css/rack/rack-change.css",
        "css/rack/cable-path.css",
        # Last: server blocks, cable lines, port menu (see the file header).
        "css/rack/rack-devices.css",
    ],
}


def compute_asset_version(*folders):
    """A short fingerprint of every file under ``folders`` (static files and
    the translation catalog). It goes into "?v=" of the CSS / JS URLs, so a
    deploy that changes any of them makes browsers fetch the new files, and
    an unchanged deploy keeps their cache."""

    import hashlib
    import os

    digest = hashlib.sha1()
    for folder in folders:
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in sorted(files):
                path = os.path.join(root, name)
                digest.update(os.path.relpath(path, folder).encode())
                with open(path, "rb") as handle:
                    digest.update(handle.read())
    return digest.hexdigest()[:12]
