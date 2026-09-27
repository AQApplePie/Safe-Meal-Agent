"""Review every call against trusted constraints immediately before execution."""

from safemeal.application.contracts.agent.decisions import ToolCall
from safemeal.application.contracts.tools.base import ToolResult
from safemeal.shared.types import JsonObject


def review_tool_calls(
    calls: list[ToolCall], constraint: JsonObject | None, *, approved: bool = False
) -> tuple[list[ToolCall], list[ToolResult]]:
    accepted, rejected = [], []
    excluded = list((constraint or {}).get("excluded_ingredients") or [])
    for call in calls:
        if call.tool_name == "external_mcp_call" and not approved:
            rejected.append(
                ToolResult(
                    call_id=call.id,
                    tool_name=call.tool_name,
                    ok=False,
                    status="rejected",
                    error="External tools require explicit approval",
                    error_code="tool_not_approved",
                )
            )
            continue
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
        accepted.append(call)
    return accepted, rejected
