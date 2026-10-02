"""Agent与本地Tool runtime共享的类型化契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from safemeal.shared.types import JsonObject, JsonValue


class ToolSpecification(BaseModel):
    """Agent 可用工具的完整、可审计描述。

    Planner 只依赖这个工具说明，不直接依赖工具实现类。除 JSON Schema 外，
    契约还显式说明用途、正负边界和副作用，避免模型只凭工具名称猜测能力。
    ``arguments_schema`` 与运行时 Pydantic 参数模型同源生成。
    """

    name: str = Field(description="工具名称，必须唯一。")
    # Defaults preserve compatibility with lightweight test doubles. Production
    # ToolHandler instances reject missing metadata before publishing a spec.
    purpose: str = Field(default="", description="工具唯一的核心用途。")
    use_when: tuple[str, ...] = Field(default=(), description="应该调用该工具的场景。")
    do_not_use_when: tuple[str, ...] = Field(
        default=(), description="禁止或不适合调用的场景。"
    )
    input_constraints: tuple[str, ...] = Field(
        default=(), description="Schema 之外的业务输入约束。"
    )
    side_effects: tuple[str, ...] = Field(
        default=(), description="调用可能产生的外部副作用。"
    )
    requires_approval: bool = Field(
        default=False, description="该工具是否属于默认需要人工批准的高风险操作。"
    )
    idempotent: bool = Field(
        default=True, description="相同参数重复调用是否应得到等价结果。"
    )
    description: str = Field(description="由结构化边界生成的 Planner 可读摘要。")
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
                raise ValueError("successful tools results cannot contain error state")
        elif self.status == "ok":
            self.status = "error"
        return self
