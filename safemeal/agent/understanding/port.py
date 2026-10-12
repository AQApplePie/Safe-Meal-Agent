"""定义应用层依赖的能力端口。"""

from typing import Protocol

from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
)
from safemeal.shared.contracts.request_frame import RequestFrame


# 类说明（接口类）：RequestUnderstandingGateway
# 作用：定义请求理解能力接口的能力契约，供应用层与具体实现解耦。
class RequestUnderstandingGateway(Protocol):
    # 字段说明：backend_name
    # 作用：实际承担请求理解或服务实现的后端标识。
    # 类型：str。
    backend_name: str

    # 方法说明：understand
    # 作用：从本轮文本与近期上下文形成校验后的请求语义框架。
    # 入参：
    #   message（str）：本轮用户消息或问题文本。
    #   recent_context（ConversationHistory）：已加载的近期对话上下文。
    # 出参：RequestFrame；归一化请求语义框架。
    async def understand(
        self, message: str, recent_context: ConversationHistory
    ) -> RequestFrame: ...
