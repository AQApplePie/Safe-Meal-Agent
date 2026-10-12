"""定义聊天用例可预期的业务异常。"""

from __future__ import annotations

from safemeal.shared.exceptions import ApplicationError


# 类说明（异常类）：ChatError
# 作用：聊天用例中可以映射为稳定接口响应的异常基类。
class ChatError(ApplicationError):
    """聊天用例中可以映射为稳定接口响应的异常基类。"""


# 类说明（异常类）：ChatSessionNotFoundError
# 作用：表示会话不存在或不属于当前用户。
class ChatSessionNotFoundError(ChatError):
    """表示会话不存在或不属于当前用户。"""

    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Chat session not found'。
    public_message = "Chat session not found"


# 类说明（异常类）：ChatTurnConflictError
# 作用：表示请求标识冲突或对应轮次仍在处理中。
class ChatTurnConflictError(ChatError):
    """表示请求标识冲突或对应轮次仍在处理中。"""

    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Chat turn conflict'。
    public_message = "Chat turn conflict"


# 类说明（异常类）：ChatAgentUnavailableError
# 作用：表示用户消息已保存，但智能体未能完成处理。
class ChatAgentUnavailableError(ChatError):
    """表示用户消息已保存，但智能体未能完成处理。"""

    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Agent is temporarily unavailable'。
    public_message = "Agent is temporarily unavailable"

    # 方法说明：__init__
    # 作用：初始化聊天 Agent 不可用异常，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   error_code（str | None）：对外稳定的错误码；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, *, error_code: str | None = None) -> None:
        super().__init__(self.public_message)
        # 实例属性说明：error_code
        # 作用：对外稳定的错误码。
        self.error_code = error_code or "agent_execution_failed"


__all__ = [
    "ChatAgentUnavailableError",
    "ChatError",
    "ChatSessionNotFoundError",
    "ChatTurnConflictError",
]
