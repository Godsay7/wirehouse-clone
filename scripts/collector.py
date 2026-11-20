#!/usr/bin/env python3
"""Collector entry point (kept at this path for switch-inventory.service).

The collector itself lives in Project/collector.
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

from Project.collector.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
