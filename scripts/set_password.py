#!/usr/bin/env python3
"""Add a web user or change its password (sign-in, Project/web/auth.py).

    python3 scripts/set_password.py admin            # asks for the password
    python3 scripts/set_password.py admin --remove   # delete the user

Users live in config/web_users (SWITCH_INVENTORY_USERS_FILE), one
"name:password-hash" per line, not in git. The web service re-reads the
file by itself; a new password signs that user out in every browser.
"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Project import settings  # noqa: E402
from Project.bll.services.auth import write_user  # noqa: E402


def remove_user(path, name):
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()
    kept = [line for line in lines if line.split(":", 1)[0].strip() != name]
    if len(kept) == len(lines):
        return False
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(kept)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="user name")
    parser.add_argument("--remove", action="store_true", help="delete the user")
    parser.add_argument("--file", default=settings.USERS_FILE, help=f"users file (default: {settings.USERS_FILE})")
    args = parser.parse_args()

    if args.remove:
        print("Removed." if remove_user(args.file, args.name) else "No such user.")
        return 0

    password = getpass.getpass(f"New password for {args.name}: ")
    if password != getpass.getpass("Again: "):
        print("The passwords differ.", file=sys.stderr)
        return 1
    write_user(args.file, args.name, password)
    print(f"Saved to {args.file}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
