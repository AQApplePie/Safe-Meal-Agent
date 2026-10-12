"""服务于 Reflector 节点的确定性证据充分性判断。

Reflector 在请求 LLM 反思前调用本模块，判断工具证据是否已经满足请求、能否跳过
额外模型调用；本模块不负责检索或渲染证据。
"""

from __future__ import annotations

from safemeal.agent.contracts.decisions import Observation


# 方法说明：_target_dish_is_classified
# 作用：判断目标菜品是否已经关联到食材分类。
# 入参：
#   observations（list[Observation]）：本轮已获得的工具观察集合。
# 出参：bool；目标菜品是否已经具有食材分类证据。
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


# 方法说明：deterministic_evidence_is_sufficient
# 作用：判断 Reflector 是否已获得充分的确定性证据。
# 入参：
#   observations（list[Observation]）：本轮已获得的工具观察集合。
# 出参：bool；当前证据是否已经足以完成任务。
def deterministic_evidence_is_sufficient(
    observations: list[Observation],
) -> bool:
    """判断 Reflector 是否已获得充分的确定性证据。"""

    if any(
        item.tool_name == "search_recipes"
        and item.ok
        and isinstance(item.data, dict)
        and item.data.get("exact_name") is True
        and item.data.get("status") in {"FOUND", "FIELD_MISSING", "NOT_FOUND", "ERROR"}
        for item in observations
    ):
        return True
    if _target_dish_is_classified(observations):
        return True
    return any(
        observation.tool_name in {"generate_recipe", "multi_route_retrieval"}
        and observation.ok
        and observation.has_data
        for observation in observations
    )


# 方法说明：recommendation_completion
# 作用：返回普通数量推荐的请求数、满足数和完成状态。
# 入参：
#   observations（list[Observation]）：本轮已获得的工具观察集合。
# 出参：tuple[int, int, bool] | None；整数、整数、布尔判定值组成的元组或None（未取得结果）。
def recommendation_completion(
    observations: list[Observation],
) -> tuple[int, int, bool] | None:
    """返回普通数量推荐的请求数、满足数和完成状态。"""

    for observation in reversed(observations):
        if (
            observation.tool_name == "recommend_recipes"
            and observation.ok
            and isinstance(observation.data, dict)
            and observation.data.get("requested_count") is not None
        ):
            requested = int(observation.data["requested_count"])
            fulfilled = int(observation.data.get("fulfilled_count") or 0)
            return requested, fulfilled, fulfilled >= requested
    return None


__all__ = ["deterministic_evidence_is_sufficient", "recommendation_completion"]
