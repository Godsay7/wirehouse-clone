"""Sign-in: who may change data on the site.

Without signing in the site is read-only. For now the users are local:
lines "name:password-hash" in settings.USERS_FILE, written by
scripts/set_password.py. Later another source (Active Directory group) can
take the same place: anything with ``authenticate()`` and ``fingerprint()``.
"""

import hashlib
import os
import threading
import time

from werkzeug.security import check_password_hash, generate_password_hash


class LocalUsers:
    """Users from a small text file, re-read when the file changes."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._stamp = None
        self._users = {}

    def _load(self):
        try:
            stat = os.stat(self.path)
        except OSError:
            self._stamp, self._users = None, {}
            return self._users
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._stamp:
            return self._users

        users = {}
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                name, password_hash = line.split(":", 1)
                if name.strip() and password_hash.strip():
                    users[name.strip()] = password_hash.strip()
        self._stamp, self._users = stamp, users
        return users

    def users(self):
        with self._lock:
            return dict(self._load())

    def authenticate(self, name, password):
        """The user's name when the password is right, otherwise None."""

        password_hash = self.users().get((name or "").strip())
        if password_hash and password and check_password_hash(password_hash, password):
            return (name or "").strip()
        return None

    def fingerprint(self, name):
        """Changes when the user's password changes or the user is removed:
        kept in the session, so a new password signs out every browser."""

        password_hash = self.users().get(name or "")
        if not password_hash:
            return None
        return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def write_user(path, name, password):
    """Add the user or set a new password (scripts/set_password.py)."""

    name = (name or "").strip()
    if not name or ":" in name or any(ch.isspace() for ch in name):
        raise ValueError("The user name must not be empty or contain ':' or spaces")
    if not password:
        raise ValueError("The password must not be empty")

    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            lines = [line.rstrip("\n") for line in handle]
    entry = f"{name}:{generate_password_hash(password)}"
    for index, line in enumerate(lines):
        if line.split(":", 1)[0].strip() == name:
            lines[index] = entry
            break
    else:
        if not lines:
            lines.append("# Wirehouse users: name:password-hash (scripts/set_password.py). Not in git.")
        lines.append(entry)

    temporary = f"{path}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


class LoginThrottle:
    """Slows down password guessing: after LIMIT failed attempts from one
    address within WINDOW seconds, further attempts are refused until the
    oldest failure leaves the window. One web process, so memory is enough."""

    LIMIT = 10
    WINDOW = 600

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = {}

    def _recent(self, key, now):
        recent = [moment for moment in self._failures.get(key, []) if now - moment < self.WINDOW]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, key):
        with self._lock:
            return len(self._recent(key, self._clock())) >= self.LIMIT

    def failed(self, key):
        with self._lock:
            now = self._clock()
            self._recent(key, now)
            self._failures.setdefault(key, []).append(now)

    def succeeded(self, key):
        with self._lock:
            self._failures.pop(key, None)
