"""Agent 模型层要求的意图理解能力。"""

from typing import Protocol, runtime_checkable
from safemeal.application.contracts.agent.intent import IntentDecision
from safemeal.application.contracts.agent.context import AgentContext


@runtime_checkable
class IntentClassifier(Protocol):
    async def classify_intent(
        self, message: str, context: AgentContext
    ) -> IntentDecision: ...
