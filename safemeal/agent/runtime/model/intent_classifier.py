"""Agent 模型层要求的意图理解能力。"""

from typing import Protocol, runtime_checkable
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.agent.contracts.context import AgentContext


@runtime_checkable
class IntentClassifier(Protocol):
    async def classify_intent(
        self, message: str, context: AgentContext
    ) -> IntentDecision: ...
