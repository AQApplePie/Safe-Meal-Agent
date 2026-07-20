"""Default Agent context provider registration.

This is the extension point for context capabilities that should participate in
the chat pipeline.  Add user profile, episodic memory or device context by
adding a provider here; the chat flow itself should remain unchanged.
"""

from __future__ import annotations

from SafeMealAgent.back.application.use_cases.agent.context_builder import (
    AgentContextProvider,
    MemoryContextProvider,
)
from SafeMealAgent.back.application.use_cases.agent.conversation_memory import MemoryRelevanceSelector
from SafeMealAgent.back.shared.contracts.memory import AgentMemoryProvider


def create_default_agent_context_providers(
    *,
    memory_provider: AgentMemoryProvider,
    memory_limit: int = 20,
) -> list[AgentContextProvider]:
    """Return context providers used by the core chat pipeline."""

    return [
        MemoryContextProvider(
            memory_provider=memory_provider,
            selector=MemoryRelevanceSelector(limit=memory_limit),
        ),
    ]


__all__ = ["create_default_agent_context_providers"]
