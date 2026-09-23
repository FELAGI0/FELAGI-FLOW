import logging

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import JSONRenderer, TimeStamper, add_log_level

from app.shared.config import settings


def setup_logging() -> None:
    level: int = logging.getLevelName(settings.log_level)
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[merge_contextvars, add_log_level, TimeStamper(fmt="iso"), JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
