"""Agent 内部结构化模型。

Planner、工具执行、Observation 和 Reflection 节点通过这些模型传递结构化数据，
保证 LLM 输出、工具参数、证据来源和状态记录可以被稳定解析。
"""

from __future__ import annotations
from dataclasses import dataclass


from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from safemeal.shared.types import JsonObject, JsonValue


# 类说明（数据契约类）：ToolCall
# 作用：LLM 计划执行的一次工具调用。
class ToolCall(BaseModel):
    """LLM 计划执行的一次工具调用。"""

    # 字段说明：id
    # 作用：本轮唯一调用编号。
    # 类型：str。
    # 配置：最小长度=1；最大长度=128。
    id: str = Field(min_length=1, max_length=128, description="本轮唯一调用编号")
    # 字段说明：tool_name
    # 作用：必须是工具注册表中的名称。
    # 类型：str。
    # 配置：最小长度=1；最大长度=128。
    tool_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="必须是工具注册表中的名称",
    )
    # 字段说明：arguments
    # 作用：工具参数；由具体工具的 args_schema 做二次校验。
    # 类型：JsonObject。
    # 配置：默认值工厂（每次创建独立对象）=dict。
    arguments: JsonObject = Field(
        default_factory=dict,
        description="工具参数；由具体工具的 args_schema 做二次校验。",
    )
    # 字段说明：purpose
    # 作用：调用该工具要解决的问题。
    # 类型：str。
    # 配置：最小长度=1；最大长度=1000。
    purpose: str = Field(
        min_length=1, max_length=1_000, description="调用该工具要解决的问题"
    )
    # 字段说明：success_criteria
    # 作用：什么结果可视为本次调用成功。
    # 类型：str。
    # 配置：最小长度=1；最大长度=1000。
    success_criteria: str = Field(
        min_length=1,
        max_length=1_000,
        description="什么结果可视为本次调用成功",
    )


# 类说明（数据契约类）：PlanDecision
# 作用：首次规划或重新规划的结构化输出。
class PlanDecision(BaseModel):
    """首次规划或重新规划的结构化输出。"""

    # 字段说明：decision
    # 作用：规划、约束或审批形成的决策。
    # 类型：Literal['answer', 'tools']。
    # 取值说明：
    #   answer：形成最终回答。
    #   tools：工具执行阶段。
    decision: Literal["answer", "tools"]
    # 字段说明：rationale
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    rationale: str
    # 字段说明：direct_answer
    # 作用：无需继续调用工具即可返回给用户的答复文本。
    # 类型：Optional[str]。
    # 初始值：None。
    direct_answer: Optional[str] = None
    # 字段说明：calls
    # 作用：待执行或待审核的工具调用列表。
    # 类型：List[ToolCall]。
    # 配置：默认值工厂（每次创建独立对象）=list；最大长度=4。
    calls: List[ToolCall] = Field(default_factory=list, max_length=4)

    # 方法说明：validate_decision_shape
    # 作用：校验规划决策的动作字段组合是否合法。
    # 入参：
    #   无显式入参。
    # 出参：'PlanDecision'；工具规划决策。
    @model_validator(mode="after")
    def validate_decision_shape(self) -> "PlanDecision":
        if self.decision == "answer" and not (self.direct_answer or "").strip():
            raise ValueError("answer decisions require a non-empty direct_answer")
        if self.decision == "tools" and not self.calls:
            raise ValueError("tools decisions require at least one tools call")
        call_ids = [call.id for call in self.calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tools call ids must be unique within a decision")
        return self


# 类说明（数据契约类）：Observation
# 作用：Observation 节点对一次工具执行结果的标准化记录。
class Observation(BaseModel):
    """Observation 节点对一次工具执行结果的标准化记录。"""

    # 字段说明：call_id
    # 作用：工具调用标识。
    # 类型：str。
    call_id: str
    # 字段说明：tool_name
    # 作用：工具名称。
    # 类型：str。
    tool_name: str
    # 字段说明：purpose
    # 作用：工具或组件的业务用途说明。
    # 类型：str。
    purpose: str
    # 字段说明：success_criteria
    # 作用：任务完成的判定条件，供规划与反思核对。
    # 类型：str。
    success_criteria: str
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
    # 字段说明：has_data
    # 作用：结果中是否存在可用数据。
    # 类型：bool。
    has_data: bool
    # 字段说明：summary
    # 作用：已生成的上下文或工具结果摘要。
    # 类型：str。
    summary: str
    # 字段说明：data
    # 作用：工具执行返回的业务载荷，供观察、反思和答复生成使用。
    # 类型：JsonValue。
    # 初始值：None。
    data: JsonValue = None
    # 字段说明：error
    # 作用：当前操作的错误信息。
    # 类型：Optional[str]。
    # 初始值：None。
    error: Optional[str] = None
    # 字段说明：error_code
    # 作用：对外稳定的错误码。
    # 类型：Optional[str]。
    # 初始值：None。
    error_code: Optional[str] = None
    # 字段说明：retryable
    # 作用：当前失败是否允许重试。
    # 类型：bool。
    # 初始值：False。
    retryable: bool = False


# 类说明（数据契约类）：ReflectionDecision
# 作用：LLM 对当前证据是否充分作出的判断。
class ReflectionDecision(BaseModel):
    """LLM 对当前证据是否充分作出的判断。"""

    # 字段说明：decision
    # 作用：规划、约束或审批形成的决策。
    # 类型：Literal['finish', 'continue', 'replan']。
    # 取值说明：
    #   finish：结束当前执行。
    #   continue：继续当前执行。
    #   replan：重新规划。
    decision: Literal["finish", "continue", "replan"]
    # 字段说明：rationale
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    rationale: str
    # 字段说明：evidence_sufficient
    # 作用：现有证据是否足以完成任务。
    # 类型：bool。
    evidence_sufficient: bool
    # 字段说明：missing_information
    # 作用：当前任务尚缺少的信息集合。
    # 类型：List[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    missing_information: List[str] = Field(default_factory=list)
    # 字段说明：next_calls
    # 作用：规划器提出的下一批工具调用。
    # 类型：List[ToolCall]。
    # 配置：默认值工厂（每次创建独立对象）=list；最大长度=4。
    next_calls: List[ToolCall] = Field(default_factory=list, max_length=4)

    # 方法说明：validate_decision_shape
    # 作用：校验规划决策的动作字段组合是否合法。
    # 入参：
    #   无显式入参。
    # 出参：'ReflectionDecision'；证据反思与继续执行决策。
    @model_validator(mode="after")
    def validate_decision_shape(self) -> "ReflectionDecision":
        if self.decision == "continue" and not self.next_calls:
            raise ValueError("continue decisions require at least one tools call")
        call_ids = [call.id for call in self.next_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tools call ids must be unique within a decision")
        return self


# 类说明（数据契约类）：ModelBudgetUsage
# 作用：描述模型预算累计用量的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class ModelBudgetUsage:
    # 字段说明：tokens
    # 作用：待统计或消费的 Token 数。
    # 类型：int。
    tokens: int
    # 字段说明：cost
    # 作用：已核算的模型调用费用，计价单位沿用配置中的价格表。
    # 类型：float。
    cost: float
    # 字段说明：cost_complete
    # 作用：调用成本是否可完整计算，缺失用量或价格时为 false。
    # 类型：bool。
    cost_complete: bool


# 类说明（数据契约类）：DeterministicRouteDecision
# 作用：描述规则路由判定的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class DeterministicRouteDecision:
    # 字段说明：route
    # 作用：HTTP 路由模板或业务路由标识。
    # 类型：str。
    route: str
    # 字段说明：message
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    message: str
    # 字段说明：reason
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    reason: str
