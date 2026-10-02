"""Build the context object passed into an Agent run.

The chat use case should not know which kinds of context the Agent consumes.
This builder is the extension point for short-term history, long-term user
memory, user profiles and future episodic memory retrieval.
"""

from __future__ import annotations

from typing import Optional, Protocol, Sequence

from safemeal.application.contracts.agent.context import AgentContext, AgentContextPatch
from safemeal.application.contracts.conversation.models import ConversationHistory
from safemeal.application.contracts.workflow.request_frame import RequestFrame
from safemeal.application.service.chat.conversation_history_service import (
    ConversationHistoryService,
)
from safemeal.application.service.memory.user_memory_service import UserMemoryService
from safemeal.shared.types import JsonObject, to_json_object, to_json_object_list
from .conversation_context import ConversationContextWindow, MemoryRelevanceSelector


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
        episodic_memories: Sequence[JsonObject] = (),
    ) -> AgentContextPatch: ...


class MemoryContextProvider:
    """Collect long-term user memories for an Agent run."""

    def __init__(
        self,
        *,
        memory_service: UserMemoryService,
        selector: MemoryRelevanceSelector | None = None,
    ) -> None:
        self._memory_service = memory_service
        self._selector = selector or MemoryRelevanceSelector()

    def collect(
        self,
        *,
        user_id: str,
        message: str,
        session_id: str,
        conversation_history: ConversationHistory,
        source_message_id: Optional[str] = None,
        episodic_memories: Sequence[JsonObject] = (),
    ) -> AgentContextPatch:
        user_memories = self._memory_service.load_agent_memories(
            user_id=user_id, limit=100
        )
        user_memories = self._selector.select(message, user_memories)
        persisted_episodes = self._memory_service.load_episodic_memories(
            user_id=user_id,
            limit=self._selector.limit,
        )
        persisted_episodes = self._selector.select(message, persisted_episodes)
        return AgentContextPatch(
            user_memories=to_json_object_list(user_memories),
            episodic_memories=to_json_object_list(
                [*episodic_memories, *persisted_episodes]
            ),
        )

    def collect_selected(
        self,
        *,
        user_id: str,
        message: str,
        session_id: str,
        conversation_history: ConversationHistory,
        context_needs: set[str],
        source_message_id: Optional[str] = None,
        episodic_memories: Sequence[JsonObject] = (),
    ) -> AgentContextPatch:
        memory_types: set[str] = set()
        if "allergies" in context_needs:
            memory_types.add("dietary_allergy")
        if "dietary_restrictions" in context_needs:
            memory_types.add("dietary_restriction")
        if "food_preferences" in context_needs:
            memory_types.update(
                {"taste_preference", "taste_dislike", "health_goal", "cooking_time"}
            )
        if hasattr(self._memory_service, "load_agent_memories_by_types"):
            user_memories = self._memory_service.load_agent_memories_by_types(
                user_id=user_id, memory_types=memory_types, limit=100
            )
        else:
            user_memories = [
                item
                for item in self._memory_service.load_agent_memories(
                    user_id=user_id, limit=100
                )
                if item.get("memory_type") in memory_types
            ]
        persisted_episodes = []
        if "episodic_memory" in context_needs:
            persisted_episodes = self._memory_service.load_episodic_memories(
                user_id=user_id, limit=self._selector.limit
            )
            persisted_episodes = self._selector.select(message, persisted_episodes)
        return AgentContextPatch(
            user_memories=to_json_object_list(user_memories),
            episodic_memories=to_json_object_list(
                [*episodic_memories, *persisted_episodes]
                if "episodic_memory" in context_needs
                else []
            ),
        )


class AgentContextBuilder:
    """Assemble Agent context from application-level providers."""

    def __init__(
        self,
        *,
        providers: Sequence[AgentContextProvider] | None = None,
        memory_service: UserMemoryService | None = None,
        conversation_window: ConversationContextWindow | None = None,
        history_service: ConversationHistoryService | None = None,
    ) -> None:
        context_providers = list(providers or [])
        if memory_service is not None:
            context_providers.append(
                MemoryContextProvider(memory_service=memory_service)
            )
        self._providers = context_providers
        self._conversation_window = conversation_window
        self._history_service = history_service

    def build_chat_context(
        self,
        *,
        user_id: str,
        message: str,
        session_id: str,
        conversation_history: ConversationHistory,
        source_message_id: Optional[str] = None,
        use_user_memory: bool = True,
        request_frame: RequestFrame | None = None,
        preloaded_history: ConversationHistory | None = None,
    ) -> AgentContext:
        """Build context for a persisted user chat turn."""

        if preloaded_history is not None:
            conversation_history = list(preloaded_history)
        elif source_message_id is not None:
            if self._history_service is None:
                raise RuntimeError("Persisted turns require a conversation history service")
            conversation_history = self._history_service.load_before_turn(
                user_id=user_id, session_id=session_id, source_message_id=source_message_id
            )
        prepared = (
            self._conversation_window.prepare(
                conversation_history,
                current_message=message,
            )
            if self._conversation_window is not None
            else None
        )
        prepared_history = (
            prepared.history if prepared is not None else list(conversation_history)
        )
        context = AgentContext(
            conversation_history=prepared_history,
            episodic_memories=[],
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
        needs = set(request_frame.context_needs if request_frame else ())
        for provider in self._providers if use_user_memory else ():
            if isinstance(provider, MemoryContextProvider) and request_frame is not None:
                patch = provider.collect_selected(
                    user_id=user_id,
                    message=message,
                    session_id=session_id,
                    conversation_history=prepared_history,
                    context_needs=needs,
                    source_message_id=source_message_id,
                    episodic_memories=(
                        prepared.episodic_memories if prepared is not None else []
                    ),
                )
            else:
                patch = provider.collect(
                user_id=user_id,
                message=message,
                session_id=session_id,
                conversation_history=prepared_history,
                source_message_id=source_message_id,
                episodic_memories=(
                    prepared.episodic_memories if prepared is not None else []
                ),
            )
            self._apply_patch(context, patch)
        context.request_frame = request_frame
        loaded_context_types: list[str] = []
        if prepared_history:
            loaded_context_types.append("recent_conversation")
        loaded_memory_types = {
            str(item.get("memory_type") or "") for item in context.user_memories
        }
        if "dietary_allergy" in loaded_memory_types:
            loaded_context_types.append("allergies")
        if "dietary_restriction" in loaded_memory_types:
            loaded_context_types.append("dietary_restrictions")
        if loaded_memory_types & {
            "taste_preference",
            "taste_dislike",
            "health_goal",
            "cooking_time",
        }:
            loaded_context_types.append("food_preferences")
        if context.episodic_memories:
            loaded_context_types.append("episodic_memory")
        context.context_metadata["loaded_context_types"] = loaded_context_types
        return context

    def load_recent_history(
        self,
        *,
        user_id: str,
        session_id: str,
        source_message_id: str | None,
        fallback: ConversationHistory,
    ) -> ConversationHistory:
        if source_message_id is not None:
            if self._history_service is None:
                raise RuntimeError("Persisted turns require a conversation history service")
            return self._history_service.load_before_turn(
                user_id=user_id,
                session_id=session_id,
                source_message_id=source_message_id,
            )
        return list(fallback)

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


def create_default_agent_context_providers(
    *,
    memory_service: UserMemoryService,
    memory_limit: int = 20,
) -> list[AgentContextProvider]:
    """Build the context providers used by the chat pipeline."""

    return [
        MemoryContextProvider(
            memory_service=memory_service,
            selector=MemoryRelevanceSelector(limit=memory_limit),
        )
    ]


__all__ = [
    "AgentContextBuilder",
    "AgentContextProvider",
    "MemoryContextProvider",
    "create_default_agent_context_providers",
]
