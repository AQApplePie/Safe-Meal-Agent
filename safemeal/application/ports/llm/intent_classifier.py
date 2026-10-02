"""Agent task understanding provided by a model adapter."""

from typing import Protocol, runtime_checkable
from safemeal.application.contracts.agent.intent import IntentDecision
from safemeal.application.contracts.agent.context import AgentContext


@runtime_checkable
class IntentClassifier(Protocol):
    async def classify_intent(
        self, message: str, context: AgentContext
    ) -> IntentDecision: ...
