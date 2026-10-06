"""在工具执行前统一校验参数并注入可信约束。"""

from safemeal.application.contracts.agent.decisions import ToolCall
from safemeal.application.contracts.dietary_safety.requirements import (
    DietaryRequirements,
)
from safemeal.application.contracts.tools.base import ToolResult
from safemeal.shared.types import JsonObject


def review_tool_calls(
    calls: list[ToolCall],
    constraint: JsonObject | None,
    *,
    requirements: DietaryRequirements | None = None,
) -> tuple[list[ToolCall], list[ToolResult]]:
    """返回已注入可信约束的调用，以及因参数非法而拒绝的结果。"""

    accepted: list[ToolCall] = []
    rejected: list[ToolResult] = []
    excluded = list((constraint or {}).get("excluded_ingredients") or [])
    for call in calls:
        if excluded and call.tool_name == "verify_recipe_constraints":
            arguments = dict(call.arguments)
            existing = arguments.get("constraints", [])
            if not isinstance(existing, (list, tuple)):
                rejected.append(
                    ToolResult(
                        call_id=call.id,
                        tool_name=call.tool_name,
                        ok=False,
                        status="rejected",
                        error="Invalid constraint statements",
                        error_code="invalid_tool_arguments",
                    )
                )
                continue
            injected = [
                {
                    "type": "restriction",
                    "value": ingredient,
                    "strength": "hard_safety",
                    "source": "current_input",
                    "scope": "current_turn",
                }
                for ingredient in excluded
            ]
            arguments["constraints"] = [*existing, *injected]
            call = call.model_copy(update={"arguments": arguments})
        # 图检索工具沿用复数字段名，其余菜谱工具使用统一的单数字段名。
        key = (
            "excluded_ingredients"
            if call.tool_name == "dietary_safe_recipe_query"
            else "exclude_ingredients"
        )
        if excluded and call.tool_name in {
            "search_recipes",
            "recommend_recipes",
            "generate_recipe",
            "dietary_safe_recipe_query",
        }:
            arguments = dict(call.arguments)
            existing = arguments.get(key, [])
            if not isinstance(existing, (list, tuple)):
                rejected.append(
                    ToolResult(
                        call_id=call.id,
                        tool_name=call.tool_name,
                        ok=False,
                        status="rejected",
                        error="Invalid ingredient exclusions",
                        error_code="invalid_tool_arguments",
                    )
                )
                continue
            arguments[key] = list(dict.fromkeys([*existing, *excluded]))
            call = call.model_copy(update={"arguments": arguments})

        if requirements and call.tool_name in {
            "search_recipes",
            "recommend_recipes",
            "generate_recipe",
        }:
            arguments = dict(call.arguments)
            invalid = False
            for preference in requirements.preferences:
                if not preference.required:
                    continue
                field = {
                    "include_ingredient": "include_ingredients",
                    "avoid_ingredient": "exclude_ingredients",
                    "dietary_type": "dietary_types",
                }.get(preference.kind)
                if field:
                    existing = arguments.get(field, [])
                    if not isinstance(existing, (list, tuple)) or not all(
                        isinstance(value, str) for value in existing
                    ):
                        invalid = True
                        break
                    arguments[field] = list(
                        dict.fromkeys([*existing, preference.value])
                    )
                elif preference.kind == "max_minutes":
                    existing_time = arguments.get("max_total_time_minutes")
                    if existing_time is not None and (
                        not isinstance(existing_time, int)
                        or isinstance(existing_time, bool)
                    ):
                        invalid = True
                        break
                    arguments["max_total_time_minutes"] = min(
                        existing_time or int(preference.value), int(preference.value)
                    )
            if invalid:
                rejected.append(
                    ToolResult(
                        call_id=call.id,
                        tool_name=call.tool_name,
                        ok=False,
                        status="rejected",
                        error="Invalid requirement arguments",
                        error_code="invalid_tool_arguments",
                    )
                )
                continue
            if call.tool_name == "generate_recipe":
                # 生成模型还需要可读文本，因此把结构化约束附加到生成要求中。
                arguments["requirements"] = (
                    str(arguments.get("requirements") or "生成食谱")
                    + "\n用户偏好与硬约束（required=true 必须满足）："
                    + requirements.model_dump_json()
                )
            call = call.model_copy(update={"arguments": arguments})
        accepted.append(call)
    return accepted, rejected


__all__ = ["review_tool_calls"]
