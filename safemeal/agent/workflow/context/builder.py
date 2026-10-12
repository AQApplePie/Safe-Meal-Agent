"""实现聊天工作流中的对应职责。"""

from __future__ import annotations

from typing import AbstractSet, Optional, Protocol, Sequence

from safemeal.agent.contracts.context import AgentContext, AgentContextPatch
from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
)
from safemeal.shared.contracts.request_frame import RequestFrame
from safemeal.agent.context.history import (
    ConversationHistoryService,
)
from safemeal.agent.context.relevance import MemoryRelevanceSelector
from safemeal.modules.conversation.application.memory.user_memory_service import (
    UserMemoryService,
)
from safemeal.shared.types import JsonObject, to_json_object, to_json_object_list
from .conversation_context import ConversationContextWindow


# 类说明（接口类）：AgentContextProvider
# 作用：定义Agent 上下文提供接口的能力契约，供应用层与具体实现解耦。
class AgentContextProvider(Protocol):
    # 方法说明：collect
    # 作用：收集Agent 上下文提供接口当前调用所需的上下文信息。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   message（str）：本轮用户消息或问题文本。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   conversation_history（ConversationHistory）：按顺序组织的历史对话消息。
    #   source_message_id（Optional[str]）：记忆或结果对应的来源消息标识；默认值为 None。
    #   episodic_memories（Sequence[JsonObject]）：已加载的近期任务片段记忆；默认值为 ()。
    # 出参：AgentContextPatch；Agent 上下文局部更新。
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


# 类说明（业务或基础设施实现类）：MemoryContextProvider
# 作用：实现长期记忆上下文提供器，封装该组件的业务处理与依赖协作。
class MemoryContextProvider:
    # 方法说明：__init__
    # 作用：初始化长期记忆上下文提供器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   memory_service（UserMemoryService）：长期记忆业务服务。
    #   selector（MemoryRelevanceSelector | None）：上下文记忆或分块策略的选择组件；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        memory_service: UserMemoryService,
        selector: MemoryRelevanceSelector | None = None,
    ) -> None:
        # 实例属性说明：_memory_service
        # 作用：长期记忆业务服务。
        self._memory_service = memory_service
        # 实例属性说明：_selector
        # 作用：上下文记忆或分块策略的选择组件。
        self._selector = selector or MemoryRelevanceSelector()

    # 方法说明：collect
    # 作用：收集长期记忆上下文提供器当前调用所需的上下文信息。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   message（str）：本轮用户消息或问题文本。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   conversation_history（ConversationHistory）：按顺序组织的历史对话消息。
    #   source_message_id（Optional[str]）：记忆或结果对应的来源消息标识；默认值为 None。
    #   episodic_memories（Sequence[JsonObject]）：已加载的近期任务片段记忆；默认值为 ()。
    # 出参：AgentContextPatch；Agent 上下文局部更新。
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

    # 方法说明：collect_selected
    # 作用：从工具结果中收集已选菜品，合并到菜单进度。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   message（str）：本轮用户消息或问题文本。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   conversation_history（ConversationHistory）：按顺序组织的历史对话消息。
    #   context_needs（AbstractSet[str]）：当前任务需要补充的上下文类型。
    #   source_message_id（Optional[str]）：记忆或结果对应的来源消息标识；默认值为 None。
    #   episodic_memories（Sequence[JsonObject]）：已加载的近期任务片段记忆；默认值为 ()。
    # 出参：AgentContextPatch；Agent 上下文局部更新。
    def collect_selected(
        self,
        *,
        user_id: str,
        message: str,
        session_id: str,
        conversation_history: ConversationHistory,
        context_needs: AbstractSet[str],
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


# 类说明（业务或基础设施实现类）：AgentContextBuilder
# 作用：实现Agent 上下文构建器，封装该组件的业务处理与依赖协作。
class AgentContextBuilder:
    # 方法说明：__init__
    # 作用：初始化Agent 上下文构建器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   providers（Sequence[AgentContextProvider] | None）：可选的外部模型供应商配置集合；默认值为
    # None。
    #   memory_service（UserMemoryService | None）：长期记忆业务服务；默认值为 None。
    #   conversation_window（ConversationContextWindow | None）：历史消息裁剪与摘要组件；默认值为
    # None。
    #   history_service（ConversationHistoryService | None）：历史消息及活动菜单读取服务；默认值为
    # None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
        # 实例属性说明：_providers
        # 作用：可选的外部模型供应商配置集合。
        self._providers = context_providers
        # 实例属性说明：_conversation_window
        # 作用：历史消息裁剪与摘要组件。
        self._conversation_window = conversation_window
        # 实例属性说明：_history_service
        # 作用：历史消息及活动菜单读取服务。
        self._history_service = history_service

    # 方法说明：build_chat_context
    # 作用：读取历史与长期记忆，组装聊天执行上下文。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   message（str）：本轮用户消息或问题文本。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   conversation_history（ConversationHistory）：按顺序组织的历史对话消息。
    #   source_message_id（Optional[str]）：记忆或结果对应的来源消息标识；默认值为 None。
    #   use_user_memory（bool）：是否为本轮加载并使用长期记忆；默认值为 True。
    #   request_frame（RequestFrame | None）：已归一化的请求语义框架；默认值为 None。
    #   preloaded_history（ConversationHistory | None）：已加载的近期对话上下文；默认值为 None。
    #   preloaded_active_menu（JsonObject | None）：本轮已有的结构化活动菜单；默认值为 None。
    # 出参：AgentContext；Agent 执行上下文。
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
        preloaded_active_menu: JsonObject | None = None,
    ) -> AgentContext:

        if preloaded_history is not None:
            conversation_history = list(preloaded_history)
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
        if preloaded_active_menu is not None:
            context.context_metadata["active_menu"] = preloaded_active_menu
        needs = set(request_frame.context_needs if request_frame else ())
        for provider in self._providers if use_user_memory else ():
            if (
                isinstance(provider, MemoryContextProvider)
                and request_frame is not None
            ):
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

    # 方法说明：load_context_sources
    # 作用：通过上下文层的唯一读取入口取得本轮可信输入快照。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   source_message_id（str | None）：记忆或结果对应的来源消息标识。
    #   fallback（ConversationHistory）：当前值不可用时使用的回退值。
    # 出参：tuple[ConversationHistory, JsonObject | None]；历史对话上下文、JSON
    # 字段映射或None（未取得结果）组成的元组。
    def load_context_sources(
        self,
        *,
        user_id: str,
        session_id: str,
        source_message_id: str | None,
        fallback: ConversationHistory,
    ) -> tuple[ConversationHistory, JsonObject | None]:
        """通过上下文层的唯一读取入口取得本轮可信输入快照。"""

        if source_message_id is None:
            return list(fallback), None
        if self._history_service is None:
            raise RuntimeError("Persisted turns require a conversation history service")
        return self._history_service.load_context_before_turn(
            user_id=user_id,
            session_id=session_id,
            source_message_id=source_message_id,
        )

    # 方法说明：_apply_patch
    # 作用：把上下文提供器返回的局部更新合并进 Agent 上下文。
    # 入参：
    #   context（AgentContext）：本轮执行上下文。
    #   patch（AgentContextPatch）：待合并的局部状态更新。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    @staticmethod
    def _apply_patch(context: AgentContext, patch: AgentContextPatch) -> None:
        context.user_memories.extend(to_json_object_list(patch.user_memories))
        context.episodic_memories.extend(to_json_object_list(patch.episodic_memories))
        context.observations.extend(to_json_object_list(patch.observations))
        if patch.user_profile is not None:
            if context.user_profile is None:
                context.user_profile = to_json_object(patch.user_profile)
            else:
                context.user_profile.update(to_json_object(patch.user_profile))
        context.context_metadata.update(to_json_object(patch.context_metadata))


# 方法说明：create_default_agent_context_providers
# 作用：创建历史、记忆等默认上下文提供器。
# 入参：
#   memory_service（UserMemoryService）：长期记忆业务服务。
#   memory_limit（int）：本轮最多加载的长期记忆条数；默认值为 20。
# 出参：list[AgentContextProvider]；Agent 上下文提供接口的集合。
def create_default_agent_context_providers(
    *,
    memory_service: UserMemoryService,
    memory_limit: int = 20,
) -> list[AgentContextProvider]:

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
