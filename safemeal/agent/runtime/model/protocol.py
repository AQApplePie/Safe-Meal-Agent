"""Language-model capabilities used by application services.

应用层只声明 Planner、Reflection、Responder 所需的能力，不绑定具体 LLM SDK
或云厂商实现。
"""

from typing import Protocol

from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationMessage,
)
from safemeal.agent.runtime.tools.contracts.base import ToolSpecification

from safemeal.agent.contracts.decisions import (
    Observation,
    PlanDecision,
    ReflectionDecision,
)
from safemeal.modules.recipe.contracts.generation import RecipeGenerationRequest
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe


# 类说明（接口类）：AgentModelGateway
# 作用：定义Agent 模型网关接口的能力契约，供应用层与具体实现解耦。
class AgentModelGateway(Protocol):
    # 方法说明：plan
    # 作用：结合意图、约束和工具证据生成下一步调用计划。
    # 入参：
    #   question（str）：本轮用户消息或问题文本。
    #   conversation_history（list[ConversationMessage]）：按顺序组织的历史对话消息。
    #   tool_specs（list[ToolSpecification]）：工具用途与参数规范集合。
    #   observations（list[Observation]）：本轮已获得的工具观察集合。
    # 出参：PlanDecision；工具规划决策。
    async def plan(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        tool_specs: list[ToolSpecification],
        observations: list[Observation],
    ) -> PlanDecision: ...

    # 方法说明：reflect
    # 作用：评估当前证据、菜单配额与剩余预算，决定继续或结束。
    # 入参：
    #   question（str）：本轮用户消息或问题文本。
    #   conversation_history（list[ConversationMessage]）：按顺序组织的历史对话消息。
    #   tool_specs（list[ToolSpecification]）：工具用途与参数规范集合。
    #   observations（list[Observation]）：本轮已获得的工具观察集合。
    #   iteration（int）：当前 Agent 循环次数。
    # 出参：ReflectionDecision；证据反思与继续执行决策。
    async def reflect(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        tool_specs: list[ToolSpecification],
        observations: list[Observation],
        iteration: int,
    ) -> ReflectionDecision: ...

    # 方法说明：answer
    # 作用：根据用户问题、历史与已有证据生成最终回答文本。
    # 入参：
    #   question（str）：本轮用户消息或问题文本。
    #   conversation_history（list[ConversationMessage]）：按顺序组织的历史对话消息。
    #   observations（list[Observation]）：本轮已获得的工具观察集合。
    #   reflection_rationale（str）：反思阶段对证据充分性的说明。
    #   evidence_sufficient（bool）：现有证据是否足以完成任务。
    #   missing_information（list[str]）：当前任务尚缺少的信息集合。
    # 出参：str；根据本轮证据生成的最终答案文本。
    async def answer(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        observations: list[Observation],
        reflection_rationale: str,
        evidence_sufficient: bool,
        missing_information: list[str],
    ) -> str: ...

    # 方法说明：generate_recipe
    # 作用：根据结构化生成要求调用模型，校验生成菜谱。
    # 入参：
    #   request（RecipeGenerationRequest）：结构化食谱生成请求。
    # 出参：GeneratedRecipe；模型生成菜谱。
    async def generate_recipe(
        self,
        request: RecipeGenerationRequest,
    ) -> GeneratedRecipe: ...

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def close(self) -> None: ...


__all__ = ["AgentModelGateway"]
