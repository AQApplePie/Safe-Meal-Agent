"""Agent与本地Tool runtime共享的类型化契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from safemeal.shared.types import JsonObject, JsonValue


# 类说明（数据契约类）：ToolSpecification
# 作用：Agent 可用工具的完整、可审计描述。
class ToolSpecification(BaseModel):
    """Agent 可用工具的完整、可审计描述。

    Planner 只依赖这个工具说明，不直接依赖工具实现类。除 JSON Schema 外，
    契约还显式说明用途、正负边界和副作用，避免模型只凭工具名称猜测能力。
    ``arguments_schema`` 与运行时 Pydantic 参数模型同源生成。
    """

    # 字段说明：name
    # 作用：工具名称，必须唯一。
    # 类型：str。
    name: str = Field(description="工具名称，必须唯一。")

    # 字段说明：purpose
    # 作用：工具唯一的核心用途。
    # 类型：str。
    # 配置：默认值=''。
    purpose: str = Field(default="", description="工具唯一的核心用途。")
    # 字段说明：use_when
    # 作用：应该调用该工具的场景。
    # 类型：tuple[str, ...]。
    # 配置：默认值=()。
    use_when: tuple[str, ...] = Field(default=(), description="应该调用该工具的场景。")
    # 字段说明：do_not_use_when
    # 作用：禁止或不适合调用的场景。
    # 类型：tuple[str, ...]。
    # 配置：默认值=()。
    do_not_use_when: tuple[str, ...] = Field(
        default=(), description="禁止或不适合调用的场景。"
    )
    # 字段说明：input_constraints
    # 作用：Schema 之外的业务输入约束。
    # 类型：tuple[str, ...]。
    # 配置：默认值=()。
    input_constraints: tuple[str, ...] = Field(
        default=(), description="Schema 之外的业务输入约束。"
    )
    # 字段说明：side_effects
    # 作用：调用可能产生的外部副作用。
    # 类型：tuple[str, ...]。
    # 配置：默认值=()。
    side_effects: tuple[str, ...] = Field(
        default=(), description="调用可能产生的外部副作用。"
    )
    # 字段说明：requires_approval
    # 作用：该工具是否属于默认需要人工批准的高风险操作。
    # 类型：bool。
    # 配置：默认值=False。
    requires_approval: bool = Field(
        default=False, description="该工具是否属于默认需要人工批准的高风险操作。"
    )
    # 字段说明：idempotent
    # 作用：相同参数重复调用是否应得到等价结果。
    # 类型：bool。
    # 配置：默认值=True。
    idempotent: bool = Field(
        default=True, description="相同参数重复调用是否应得到等价结果。"
    )
    # 字段说明：description
    # 作用：由结构化边界生成的 Planner 可读摘要。
    # 类型：str。
    description: str = Field(description="由结构化边界生成的 Planner 可读摘要。")
    # 字段说明：arguments_schema
    # 作用：工具参数的 JSON Schema。
    # 类型：JsonObject。
    arguments_schema: JsonObject = Field(description="工具参数的 JSON Schema。")


# 类说明（数据契约类）：ToolResult
# 作用：Agent与本地Tool runtime共用的稳定工具结果。
class ToolResult(BaseModel):
    """Agent与本地Tool runtime共用的稳定工具结果。"""

    # 字段说明：call_id
    # 作用：工具调用标识。
    # 类型：str。
    call_id: str
    # 字段说明：tool_name
    # 作用：工具名称。
    # 类型：str。
    tool_name: str
    # 字段说明：ok
    # 作用：本次操作是否成功。
    # 类型：bool。
    ok: bool
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['ok', 'error', 'timeout', 'unavailable', 'rejected']。
    # 初始值：'ok'。
    # 取值说明：
    #   ok：操作正常。
    #   error：执行出错。
    #   timeout：执行超时。
    #   unavailable：当前不可用。
    #   rejected：请求或审核被拒绝。
    status: Literal["ok", "error", "timeout", "unavailable", "rejected"] = "ok"
    # 字段说明：data
    # 作用：工具执行返回的 JSON 业务载荷，失败或无数据时可为 None。
    # 类型：JsonValue。
    # 初始值：None。
    data: JsonValue = None
    # 字段说明：error
    # 作用：当前操作的错误信息。
    # 类型：str | None。
    # 初始值：None。
    error: str | None = None
    # 字段说明：error_code
    # 作用：对外稳定的错误码。
    # 类型：str | None。
    # 初始值：None。
    error_code: str | None = None
    # 字段说明：retryable
    # 作用：当前失败是否允许重试。
    # 类型：bool。
    # 初始值：False。
    retryable: bool = False

    # 方法说明：validate_status
    # 作用：校验用户状态属于受支持的状态集合。
    # 入参：
    #   无显式入参。
    # 出参：'ToolResult'；标准工具执行结果。
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
