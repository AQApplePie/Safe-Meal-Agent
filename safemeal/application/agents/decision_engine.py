"""Agent 决策引擎端口。

应用层只声明 Planner、Reflection、Responder 所需的能力，不绑定具体 LLM SDK
或云厂商实现。
"""

from typing import Protocol

from safemeal.shared.contracts.common import ConversationMessage
from safemeal.shared.contracts.tools import ToolSpecification

from .models import Observation, PlanDecision, ReflectionDecision


class DecisionEngine(Protocol):
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
