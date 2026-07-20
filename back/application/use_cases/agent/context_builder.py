"""Build the context object passed into an Agent run.

The chat use case should not know which kinds of context the Agent consumes.
This builder is the extension point for short-term history, long-term user
memory, user profiles and future episodic memory retrieval.
"""

from __future__ import annotations

from typing import Optional, Protocol, Sequence

from SafeMealAgent.back.shared.contracts.agent_context import AgentContext, AgentContextPatch
from SafeMealAgent.back.shared.contracts.common import ConversationHistory
from SafeMealAgent.back.shared.contracts.memory import AgentMemoryProvider
from SafeMealAgent.back.shared.types import JsonObject, to_json_object, to_json_object_list
from .conversation_memory import ConversationMemoryManager, MemoryRelevanceSelector


class AgentContextProvider(Protocol):
    """Collect one slice of context for an Agent run."""

    def collect(
        self,
        *,
        user_id: str,
        message: str,
        session_id: str,
        conversation_history: ConversationHistory,
        source_message_id: Optional[str] = None,
    ) -> AgentContextPatch: ...


class MemoryContextProvider:
    """Collect long-term user memories for an Agent run."""

    def __init__(
        self,
        *,
        memory_provider: AgentMemoryProvider,
        selector: MemoryRelevanceSelector | None = None,
    ) -> None:
        self._memory_provider = memory_provider
        self._selector = selector or MemoryRelevanceSelector()

    def collect(
        self,
        *,
        user_id: str,
        message: str,
        session_id: str,
        conversation_history: ConversationHistory,
        source_message_id: Optional[str] = None,
    ) -> AgentContextPatch:
        self._memory_provider.remember_from_message(
            user_id=user_id,
            message=message,
            source_session_id=session_id,
            source_message_id=source_message_id,
        )
        user_memories = self._memory_provider.load_agent_memories(
            user_id=user_id, limit=100
        )
        user_memories = self._selector.select(message, user_memories)
        return AgentContextPatch(user_memories=to_json_object_list(user_memories))


class AgentContextBuilder:
    """Assemble Agent context from application-level providers."""

    def __init__(
        self,
        *,
        providers: Sequence[AgentContextProvider] | None = None,
        memory_provider: AgentMemoryProvider | None = None,
        conversation_manager: ConversationMemoryManager | None = None,
    ) -> None:
        context_providers = list(providers or [])
        if memory_provider is not None:
            context_providers.append(
                MemoryContextProvider(memory_provider=memory_provider)
            )
        self._providers = context_providers
        self._conversation_manager = conversation_manager

    def build_chat_context(
        self,
        *,
        user_id: str,
        message: str,
        session_id: str,
        conversation_history: ConversationHistory,
        source_message_id: Optional[str] = None,
    ) -> AgentContext:
        """Build context for a persisted user chat turn."""

        prepared = (
            self._conversation_manager.prepare(
                conversation_history,
                current_message=message,
            )
            if self._conversation_manager is not None
            else None
        )
        prepared_history = (
            prepared.history if prepared is not None else list(conversation_history)
        )
        context = AgentContext(
            conversation_history=prepared_history,
            episodic_memories=(
                prepared.episodic_memories if prepared is not None else []
            ),
            context_metadata={
                "user_id": user_id,
                "session_id": session_id,
                "estimated_context_tokens": (
                    prepared.estimated_tokens if prepared is not None else None
                ),
                "summarized_history_messages": (
                    prepared.summarized_messages if prepared is not None else 0
                ),
            },
        )
        for provider in self._providers:
            patch = provider.collect(
                user_id=user_id,
                message=message,
                session_id=session_id,
                conversation_history=prepared_history,
                source_message_id=source_message_id,
            )
            self._apply_patch(context, patch)
        return context

    @staticmethod
    def _json_objects(values: Sequence[object]) -> list[JsonObject]:
        return to_json_object_list(values)

    @staticmethod
    def _apply_patch(context: AgentContext, patch: AgentContextPatch) -> None:
        context.user_memories.extend(
            AgentContextBuilder._json_objects(patch.user_memories)
        )
        context.episodic_memories.extend(
            AgentContextBuilder._json_objects(patch.episodic_memories)
        )
        context.observations.extend(
            AgentContextBuilder._json_objects(patch.observations)
        )
        if patch.user_profile is not None:
            if context.user_profile is None:
                context.user_profile = to_json_object(patch.user_profile)
            else:
                context.user_profile.update(to_json_object(patch.user_profile))
        context.context_metadata.update(to_json_object(patch.context_metadata))
