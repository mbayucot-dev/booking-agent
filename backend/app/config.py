"""Backwards-compatible settings shim.

The canonical settings live in :mod:`app.core.config`; this re-exports them so
``from app.config import Settings, get_settings`` keeps working.
"""

from app.core.config import Settings, get_settings  # noqa: F401
