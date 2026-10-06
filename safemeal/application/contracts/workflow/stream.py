"""定义跨层传递的稳定数据契约。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowProgress:
    stage: str
    message: str
