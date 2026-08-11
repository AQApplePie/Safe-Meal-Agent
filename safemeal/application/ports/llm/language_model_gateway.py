"""Language-model capabilities used by application services.

应用层只声明 Planner、Reflection、Responder 所需的能力，不绑定具体 LLM SDK
或云厂商实现。
"""

from typing import Protocol

from safemeal.shared.contracts.agent_conversation import ConversationMessage
from safemeal.shared.contracts.tools import ToolSpecification

from safemeal.application.contracts.agent_decisions import (
    Observation,
    PlanDecision,
    ReflectionDecision,
)
from safemeal.application.contracts.recipe_generation import RecipeGenerationRequest
from safemeal.modules.recipe_catalog.generated_recipe import GeneratedRecipe


class LanguageModelGateway(Protocol):
    async def plan(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        tool_specs: list[ToolSpecification],
        observations: list[Observation],
    ) -> PlanDecision: ...

    async def reflect(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        tool_specs: list[ToolSpecification],
        observations: list[Observation],
        iteration: int,
    ) -> ReflectionDecision: ...

    async def answer(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        observations: list[Observation],
        reflection_rationale: str,
        evidence_sufficient: bool,
        missing_information: list[str],
    ) -> str: ...

    async def generate_recipe(
        self,
        request: RecipeGenerationRequest,
    ) -> GeneratedRecipe: ...

    async def close(self) -> None: ...


__all__ = ["LanguageModelGateway"]
