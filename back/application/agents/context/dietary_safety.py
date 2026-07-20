"""Agent Observation adapters for dietary safety domain results."""

from __future__ import annotations

import json
from typing import List, Optional, cast

from SafeMealAgent.back.application.agents.models import Observation
from SafeMealAgent.back.application.domain.dietary_safety import (
    DietaryConstraint,
    DietaryEvidenceObservation,
    build_dietary_safety_result,
)
from SafeMealAgent.back.shared.types import JsonObject, to_json_object


def build_dietary_context_observation(
    constraint: DietaryConstraint,
) -> Optional[Observation]:
    """Wrap the active dietary constraint as an Agent context observation."""

    if not constraint.active:
        return None

    data = to_json_object(constraint)
    summary = (
        "当前有效忌口/过敏约束："
        f"原始食材={constraint.raw_ingredients}；"
        f"禁忌食材展开={constraint.excluded_ingredients}；"
        f"严格度={constraint.strictness}。"
    )
    return Observation(
        call_id="dietary_context",
        tool_name="dietary_context",
        purpose="记录从当前问题和历史对话继承得到的忌口/过敏约束。",
        success_criteria="后续规划、反思和最终回答必须遵守这些禁忌食材。",
        ok=True,
        has_data=True,
        summary=summary if len(summary) <= 1200 else summary[:1200] + "...",
        data=data,
    )


def build_dietary_safety_observation(
    *,
    constraint_payload: DietaryConstraint | JsonObject | None,
    observations: list[Observation],
) -> Optional[Observation]:
    """Wrap deterministic dietary filtering results as an Agent observation."""

    if not constraint_payload:
        return None
    constraint = (
        constraint_payload
        if isinstance(constraint_payload, DietaryConstraint)
        else DietaryConstraint.model_validate(constraint_payload)
    )
    if not constraint.active:
        return None

    safety_result = build_dietary_safety_result(
        constraint=constraint,
        observations=cast(List[DietaryEvidenceObservation], observations),
    )
    data = safety_result.model_dump()
    summary = json.dumps(data, ensure_ascii=False, default=str)
    return Observation(
        call_id="dietary_safety_filter",
        tool_name="dietary_safety_filter",
        purpose="根据用户忌口/过敏约束，对已有候选菜证据进行确定性安全过滤。",
        success_criteria=(
            "推荐菜必须来自 safe_recipes；excluded_recipes 不能推荐；"
            "unknown_recipes 只能说明证据不足。"
        ),
        ok=True,
        has_data=True,
        summary=summary if len(summary) <= 1200 else summary[:1200] + "...",
        data=data,
    )
