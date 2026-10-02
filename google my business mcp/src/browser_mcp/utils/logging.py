"""
Structured logging configuration for Browser MCP.
"""

import logging
import os
import sys

_ROOT_LOGGER = "browser_mcp"
_handlers_installed = False

_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_level(level: str | None) -> int:
    """Maps a level name to a logging constant, defaulting to INFO."""
    name = (level or os.getenv("BROWSER_MCP_LOG_LEVEL", "INFO")).upper()
    resolved = getattr(logging, name, logging.INFO)
    return resolved if isinstance(resolved, int) else logging.INFO


def setup_logging(level: str | None = None) -> logging.Logger:
    """Configures the package logger and returns it.

    The level is applied on every call, not only the first. Every module calls
    get_logger() at import time, so honouring the level only on initialisation
    would make a later setup_logging("DEBUG") a silent no-op and make debug
    logging impossible to turn on programmatically.
    """
    global _handlers_installed

    logger = logging.getLogger(_ROOT_LOGGER)
    logger.setLevel(_resolve_level(level))

    if _handlers_installed:
        return logger

    # Logs go to stderr so stdout stays clean for the MCP stdio protocol.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False
    _handlers_installed = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Returns a child of the package logger, configuring it on first use."""
    setup_logging()
    return logging.getLogger(f"{_ROOT_LOGGER}.{name}" if name else _ROOT_LOGGER)

