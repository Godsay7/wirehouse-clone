#!/usr/bin/env python3
"""Web UI entry point (kept at this path for switch-inventory-web.service).

The application itself lives in the Project package:
    Project/web   presentation layer (Flask blueprints, templates)
    Project/bll   business logic
    Project/dal   SQLite access
"""

import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from Project import settings  # noqa: E402
from Project.web import create_app  # noqa: E402

app = create_app()


if __name__ == "__main__":
    print("=" * 60)
    print("Switch Inventory Web Interface")
    print("=" * 60)
    print(f"Database: {settings.DB_PATH}")
    print(f"Listening: http://{settings.HOST}:{settings.PORT}")
    print("=" * 60)

    app.run(
        host=settings.HOST,
        port=settings.PORT,
        debug=False
    )
