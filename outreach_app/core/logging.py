from __future__ import annotations

import logging
import sys
from pythonjsonlogger import jsonlogger

from app.core.config import settings


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    handler.setFormatter(jsonlogger.JsonFormatter(fmt))
    root.addHandler(handler)

    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx"):
        lg = logging.getLogger(noisy)
        lg.setLevel(max(level, logging.INFO))
        lg.propagate = False
