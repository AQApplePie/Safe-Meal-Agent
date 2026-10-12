"""定义跨层传递的稳定数据契约。"""

from dataclasses import dataclass


# 类说明（数据契约类）：WorkflowProgress
# 作用：描述Workflow 阶段进度事件的结构、类型及可校验字段。
@dataclass(frozen=True)
class WorkflowProgress:
    # 字段说明：stage
    # 作用：当前执行或模型调用阶段。
    # 类型：str。
    stage: str
    # 字段说明：message
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    message: str
