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


# 方法说明：configure_logging
# 作用：按格式和级别初始化应用日志。
# 入参：
#   level（Optional[str]）：日志记录级别；默认值为 None。
#   debug（bool）：是否启用调试模式；默认值为 False。
#   log_format（Optional[str]）：日志输出格式；默认值为 None。
#   serialize（bool）：是否序列化当前输出；默认值为 False。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
