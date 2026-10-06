"""实现运行期运维能力。"""

import sys
from typing import Optional

from loguru import logger

DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "request_id={extra[request_id]} | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def configure_logging(
    *,
    level: Optional[str] = None,
    debug: bool = False,
    log_format: Optional[str] = None,
    serialize: bool = False,
) -> None:
    resolved_level = level or ("DEBUG" if debug else "INFO")
    logger.remove()
    logger.configure(extra={"request_id": "-"})
    logger.add(
        sys.stderr,
        format=log_format or DEFAULT_FORMAT,
        level=resolved_level,
        diagnose=debug,
        serialize=serialize,
    )
