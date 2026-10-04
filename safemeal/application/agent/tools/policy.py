"""Pre-execution policy enforcement for every Agent Tool call.

Model arguments are proposals, not trusted commands. This module injects hard
dietary requirements immediately before execution and rejects malformed fields so
the model cannot remove constraints supplied by Workflow.
"""

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
    """Return accepted calls with trusted constraints plus explicit rejections."""

    accepted: list[ToolCall] = []
    rejected: list[ToolResult] = []
    excluded = list((constraint or {}).get("excluded_ingredients") or [])
    for call in calls:
        # Neo4j uses a plural field name distinct from typed recipe tools.
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
                # Generation receives a readable copy in addition to structured
                # fields because its provider request contains one requirements text.
                arguments["requirements"] = (
                    str(arguments.get("requirements") or "生成食谱")
                    + "\n用户偏好与硬约束（required=true 必须满足）："
                    + requirements.model_dump_json()
                )
            call = call.model_copy(update={"arguments": arguments})
        accepted.append(call)
    return accepted, rejected


__all__ = ["review_tool_calls"]
