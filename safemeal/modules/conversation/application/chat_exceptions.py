"""定义聊天用例可预期的业务异常。"""

from __future__ import annotations

from safemeal.shared.exceptions import ApplicationError


class ChatError(ApplicationError):
    """聊天用例中可以映射为稳定接口响应的异常基类。"""


class ChatSessionNotFoundError(ChatError):
    """表示会话不存在或不属于当前用户。"""

    public_message = "Chat session not found"


class ChatTurnConflictError(ChatError):
    """表示请求标识冲突或对应轮次仍在处理中。"""

    public_message = "Chat turn conflict"


class ChatAgentUnavailableError(ChatError):
    """表示用户消息已保存，但智能体未能完成处理。"""

    public_message = "Agent is temporarily unavailable"

    def __init__(self, *, error_code: str | None = None) -> None:
        super().__init__(self.public_message)
        self.error_code = error_code or "agent_execution_failed"


__all__ = [
    "ChatAgentUnavailableError",
    "ChatError",
    "ChatSessionNotFoundError",
    "ChatTurnConflictError",
]
