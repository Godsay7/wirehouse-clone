"""Who is making the current change: set by the web layer per request.

The rack change history records it. Outside a request (scripts, tests) it
is empty and the history shows "system".
"""

from contextvars import ContextVar

_actor = ContextVar("actor", default=None)


def set_actor(ip="", name="", action="", user=""):
    """ip: client address; name: optional label (PC name); action: e.g.
    'POST /rack/connect'; user: the signed-in user."""

    return _actor.set({"ip": ip or "", "name": name or "", "action": action or "", "user": user or ""})


def reset_actor(token):
    _actor.reset(token)


def current_actor():
    return _actor.get() or {"ip": "", "name": "", "action": "", "user": ""}
