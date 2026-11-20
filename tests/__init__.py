"""Tests check the English interface; tests/test_i18n.py covers Ukrainian.

Web tests run signed in as "tester" (changes need a signed-in user, see
Project/web/auth.py); tests/test_auth.py checks the visitor who is not.
"""

import atexit
import os
import tempfile

os.environ.setdefault("SWITCH_INVENTORY_LANG", "en")

# Sign-in: a session key and a users file of the tests' own, so the tests
# never touch config/secret_key or config/web_users.
os.environ.setdefault("SWITCH_INVENTORY_SECRET_KEY", "tests-only-secret")
_handle, USERS_FILE = tempfile.mkstemp(prefix="wirehouse-users-")
os.close(_handle)
atexit.register(lambda: os.path.exists(USERS_FILE) and os.unlink(USERS_FILE))
os.environ["SWITCH_INVENTORY_USERS_FILE"] = USERS_FILE

TEST_USER = "tester"
TEST_PASSWORD = "tester-password"

from flask import Flask  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402

from Project.bll.services.auth import write_user  # noqa: E402

write_user(USERS_FILE, TEST_USER, TEST_PASSWORD)


class SignedInClient(FlaskClient):
    """The default test client: already signed in as TEST_USER."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from Project.web import auth

        with self.application.test_request_context():
            fingerprint = auth.users().fingerprint(TEST_USER)
        with self.session_transaction() as session:
            session["user"] = TEST_USER
            session["pw"] = fingerprint


Flask.test_client_class = SignedInClient
