"""服务于 Responder 节点的确定性回答文本构建。"""

from __future__ import annotations

from safemeal.agent.contracts.decisions import Observation


def dietary_constraint_is_active(constraint: object) -> bool:
    return bool(isinstance(constraint, dict) and constraint.get("active"))


def render_dietary_safety_answer(observations: list[Observation]) -> str:

    safety = next(
        (
            observation.data
            for observation in reversed(observations)
            if observation.tool_name == "dietary_safety_filter"
            and isinstance(observation.data, dict)
        ),
        None,
    )
    if not isinstance(safety, dict):
        return (
            "当前没有取得足够的结构化食材证据，无法确认菜品满足你的忌口或过敏"
            "要求。为避免风险，我暂不做具体推荐。"
        )

    safe_recipes = [
        recipe for recipe in safety.get("safe_recipes", []) if isinstance(recipe, dict)
    ]
    excluded_recipes = [
        recipe
        for recipe in safety.get("excluded_recipes", [])
        if isinstance(recipe, dict)
    ]
    unknown_recipes = [
        recipe
        for recipe in safety.get("unknown_recipes", [])
        if isinstance(recipe, dict)
    ]
    lines: list[str] = []
    if safe_recipes:
        lines.append("根据当前结构化食材证据，已确认以下菜品未命中禁忌食材：")
        for recipe in safe_recipes[:5]:
            ingredients = [str(item) for item in recipe.get("ingredients", []) or []]
            detail = f"（已核对：{'、'.join(ingredients)}）" if ingredients else ""
            lines.append(f"- {recipe.get('name', '未命名菜品')}{detail}")
    else:
        lines.append("当前证据尚未确认任何可以安全推荐的菜品。")

    if excluded_recipes:
        lines.append("以下菜品命中禁忌食材，不能推荐：")
        for recipe in excluded_recipes[:5]:
            matched = [
                str(item)
                for item in recipe.get("matched_forbidden_ingredients", []) or []
            ]
            detail = f"（命中：{'、'.join(matched)}）" if matched else ""
            lines.append(f"- {recipe.get('name', '未命名菜品')}{detail}")

    if unknown_recipes:
        names = "、".join(
            str(recipe.get("name", "未命名菜品")) for recipe in unknown_recipes[:5]
        )
        lines.append(f"证据不足、暂不能确认安全：{names}。")
    missing_information = [
        str(item) for item in safety.get("missing_information", []) or []
    ]
    if missing_information and not safe_recipes:
        lines.append("仍缺少：" + "；".join(missing_information[:3]))
    lines.append("如属严重过敏，请同时核对调味料标签和加工过程中的交叉接触风险。")
    return "\n".join(lines)


__all__ = [
    "dietary_constraint_is_active",
    "render_dietary_safety_answer",
]
