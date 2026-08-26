"""
Centralized logging configuration for the Data Agent.

Import `get_logger` wherever you need a logger:
    from app.core.logging_config import get_logger
    logger = get_logger(__name__)

The root logger for this project is ``data_agent``.
Set the LOG_LEVEL environment variable to control verbosity (default: DEBUG).
"""
import logging
import os
import sys


def _configure_root_logger() -> None:
    """Configure the project-level logger once at import time."""
    level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)

    logger = logging.getLogger("data_agent")
    if logger.handlers:
        # Already configured — avoid adding duplicate handlers
        return

    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    # Prevent log records from bubbling up to the root logger (which may
    # produce duplicate output or be suppressed altogether).
    logger.propagate = False


_configure_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Return a child logger scoped under ``data_agent``."""
    # Strip the package prefix so names read as e.g. "agent.nodes"
    short_name = name.replace("app.", "")
    return logging.getLogger(f"data_agent.{short_name}")
