"""
logger.py
---------
Consistent logging configuration for the whole backend. Import
`setup_logging()` once at app startup; every module then just does
`logging.getLogger("linuxpilot.<area>")`.
"""

from __future__ import annotations

import logging
import sys

from backend.utils.config import settings


def setup_logging() -> None:
    root = logging.getLogger("linuxpilot")
    if root.handlers:
        return  # already configured (e.g. reload)

    root.setLevel(settings.LOG_LEVEL)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    root.addHandler(handler)
