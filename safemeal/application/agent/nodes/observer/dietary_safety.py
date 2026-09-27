"""服务于 Observer 节点的饮食安全 Observation 构建。"""

from __future__ import annotations

import json
from typing import List, cast

from safemeal.application.contracts.agent.decisions import Observation
from safemeal.modules.dietary_safety.dietary_constraints import (
    DietaryConstraint,
    DietaryEvidenceObservation,
    build_dietary_safety_result,
)
from safemeal.shared.types import JsonObject


def build_dietary_safety_observation(
    *,
    constraint_payload: DietaryConstraint | JsonObject | None,
    observations: list[Observation],
) -> Observation | None:
    """把 Observer 已收集的候选证据转换为确定性饮食安全视图。"""

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


__all__ = ["build_dietary_safety_observation"]
