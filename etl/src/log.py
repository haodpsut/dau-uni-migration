"""Logging setup with loguru — pretty console + rotating file."""

from __future__ import annotations

import sys
from pathlib import Path
from loguru import logger
from .config import settings, PROJECT_ROOT


def setup_logging() -> None:
    """Configure loguru once at startup."""
    logger.remove()  # drop default

    # Console: colored, simple
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    )

    # File: rotating, JSON for grep-ability
    log_file = PROJECT_ROOT / settings.LOG_FILE
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level="DEBUG",
        rotation="50 MB",
        retention="14 days",
        compression="gz",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        enqueue=True,  # safe for multi-process
    )

    logger.info(f"Logging initialized. Level={settings.LOG_LEVEL} File={log_file}")


__all__ = ["logger", "setup_logging"]
