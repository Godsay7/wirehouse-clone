"""Which rack endpoints may be cabled together, and with which cable type."""

PATCH_TYPES = {"ethernet", "sdi", "odf"}
CABLE_TYPES = {"ethernet", "fiber", "sdi"}


def normalize_patch_type(value):
    patch_type = str(value or "ethernet").strip().lower()
    return patch_type if patch_type in PATCH_TYPES else "ethernet"


def endpoint_media(endpoint_type, patch_type=None, patch_exists=True):
    """Return the media class used for connection validation/coloring.

    patch endpoints: their panel type (ethernet / sdi / odf), None if missing.
    switch/server endpoints: "network" — they may terminate copper Ethernet
    or fiber from an ODF.
    """

    if endpoint_type == "patch":
        if not patch_exists:
            return None
        return normalize_patch_type(patch_type)

    # Temporary switches stand in for real ones: same media as a switch port.
    if endpoint_type in {"switch", "server", "placeholder"}:
        return "network"

    return None


def resolve_cable_type(t1, media1, t2, media2):
    """Validate endpoint media and return (cable_type, error)."""

    if media1 is None or media2 is None:
        return None, "Unknown or missing connection endpoint"

    # Direct switch-to-switch links are valid network links.
    # They are stored in the same generic endpoint table and use
    # the normal Ethernet cable type/color unless a future port-media
    # model says otherwise.

    # SDI is isolated from network/fiber. It may only connect SDI patch to SDI patch.
    if "sdi" in {media1, media2}:
        if media1 == media2 == "sdi" and t1 == t2 == "patch":
            return "sdi", None
        return None, "SDI ports can only connect to other SDI patch-panel ports"

    # ODF/fiber may terminate on another ODF or on a switch/server port.
    if "odf" in {media1, media2}:
        other_media = media2 if media1 == "odf" else media1
        if other_media in {"odf", "network"}:
            return "fiber", None
        return None, "ODF ports can only connect to ODF, switch, or server ports"

    # Regular Ethernet may connect to Ethernet patch or network endpoints.
    if media1 in {"ethernet", "network"} and media2 in {"ethernet", "network"}:
        return "ethernet", None

    return None, "Incompatible connection media"


def patch_link_cable_type(patch_a_type, patch_b_type, stored_cable_type):
    """Cable type for a legacy patch_connections row."""

    patch_a_type = normalize_patch_type(patch_a_type)
    patch_b_type = normalize_patch_type(patch_b_type)

    if patch_a_type == patch_b_type == "odf":
        return "fiber"

    if patch_a_type == patch_b_type == "sdi":
        return "sdi"

    cable_type = str(stored_cable_type or "ethernet").lower()
    return cable_type if cable_type in CABLE_TYPES else "ethernet"
