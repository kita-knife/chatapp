"""Logger setup for CLI runs."""
from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "info") -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
