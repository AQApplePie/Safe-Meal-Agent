"""服务于 Reflector 节点的确定性证据充分性判断。

Reflector 在请求 LLM 反思前调用本模块，判断工具证据是否已经满足请求、能否跳过
额外模型调用；本模块不负责检索或渲染证据。
"""

from __future__ import annotations

from safemeal.application.contracts.agent_decisions import Observation


_CONTEXT_OBSERVATION_TOOLS = {
    "dietary_context",
    "dietary_safety_filter",
    "user_memory_context",
}


def _target_dish_is_classified(observations: list[Observation]) -> bool:
    for observation in reversed(observations):
        if (
            observation.tool_name != "dietary_safe_recipe_query"
            or not observation.ok
            or not isinstance(observation.data, dict)
        ):
            continue
        target_dish = str(observation.data.get("target_dish") or "").strip()
        if not target_dish:
            continue
        classified_recipes = [
            recipe
            for bucket in ("safe_recipes", "excluded_recipes")
            for recipe in observation.data.get(bucket, []) or []
            if isinstance(recipe, dict)
        ]
        if any(
            str(recipe.get("name") or "").strip() == target_dish
            for recipe in classified_recipes
        ):
            return True
    return False


def deterministic_evidence_is_sufficient(
    observations: list[Observation],
) -> bool:
    """判断 Reflector 是否已获得充分的确定性证据。"""

    if _target_dish_is_classified(observations):
        return True
    external_observations = [
        observation
        for observation in observations
        if observation.tool_name not in _CONTEXT_OBSERVATION_TOOLS
    ]
    return any(
        observation.tool_name in {"generate_recipe", "multi_route_retrieval"}
        and observation.ok
        and observation.has_data
        for observation in external_observations
    )


__all__ = ["deterministic_evidence_is_sufficient"]
