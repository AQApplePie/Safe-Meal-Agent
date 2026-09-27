"""Workflow language understanding independent of the recipe Agent."""

from typing import Protocol
from safemeal.application.contracts.workflow.models import IntentDecision
from safemeal.application.contracts.agent.context import AgentContext


class IntentClassifier(Protocol):
    async def classify_intent(
        self, message: str, context: AgentContext
    ) -> IntentDecision: ...
