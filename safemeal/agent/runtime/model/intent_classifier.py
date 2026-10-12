"""Agent 模型层要求的意图理解能力。"""

from typing import Protocol, runtime_checkable
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.agent.contracts.context import AgentContext


# 类说明（接口类）：IntentClassifier
# 作用：定义意图分类器接口的能力契约，供应用层与具体实现解耦。
@runtime_checkable
class IntentClassifier(Protocol):
    # 方法说明：classify_intent
    # 作用：调用模型判断当前请求的业务意图。
    # 入参：
    #   message（str）：本轮用户消息或问题文本。
    #   context（AgentContext）：本轮执行上下文。
    # 出参：IntentDecision；Agent 意图决策。
    async def classify_intent(
        self, message: str, context: AgentContext
    ) -> IntentDecision: ...
