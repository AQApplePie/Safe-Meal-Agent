"""Agent与本地Tool runtime共享的类型化契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from safemeal.shared.types import JsonObject, JsonValue


class ToolSpecification(BaseModel):
    """Agent 可用工具的稳定描述。

    Planner 只依赖这个工具说明，不直接依赖工具实现类。``arguments_schema``
    来自 Pydantic JSON Schema，因此保留为 JSON 对象。
    """

    name: str = Field(description="工具名称，必须唯一。")
    description: str = Field(description="工具用途说明，供 Planner 做工具选择。")
    arguments_schema: JsonObject = Field(description="工具参数的 JSON Schema。")


class ToolResult(BaseModel):
    """Agent与本地Tool runtime共用的稳定工具结果。"""

    call_id: str
    tool_name: str
    ok: bool
    status: Literal["ok", "error", "timeout", "unavailable", "rejected"] = "ok"
    data: JsonValue = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> "ToolResult":
        if self.ok:
            if (
                self.status != "ok"
                or self.error is not None
                or self.error_code is not None
            ):
                raise ValueError("successful tool results cannot contain error state")
        elif self.status == "ok":
            self.status = "error"
        return self
