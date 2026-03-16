"""Application package initialization.

This module exposes the FastAPI application instance when the package is imported.
It also ensures that Celery tasks are registered when the worker starts.
"""

from .main import app  # noqa: F401

__all__ = ["app"]