from __future__ import annotations

import logging
import sys
from typing import Any, MutableMapping

import structlog


def _add_app_context(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    event_dict.setdefault("app", "npe")
    return event_dict


def get_logger(**bind: Any) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger with optional bindings."""
    return structlog.get_logger().bind(**bind)


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Clear any existing handlers to prevent duplicates (e.g. Celery's default handler)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)

    # Uvicorn adds its own handlers; stop them propagating to root
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(_name).propagate = False

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )
