"""Logging for Funes.

GLib's g_debug() is a varargs C macro and therefore not introspectable, so
`GLib.debug` does not exist in PyGObject; the standard library logger is used
instead. Debug output is off unless FUNES_DEBUG is set to a truthy value.
"""

import logging
import os

DEBUG_ENV = "FUNES_DEBUG"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_logger = logging.getLogger("funes")


def debug_enabled() -> bool:
    return os.environ.get(DEBUG_ENV, "").strip().lower() in _TRUTHY


def configure() -> None:
    """Install a stderr handler once; call from the application entry point."""
    if _logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("funes: %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG if debug_enabled() else logging.WARNING)


def debug(message: str) -> None:
    _logger.debug(message)


def warn(message: str) -> None:
    _logger.warning(message)
