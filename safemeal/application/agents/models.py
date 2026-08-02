"""Agent 内部结构化模型。

Planner、工具执行、Observation 和 Reflection 节点通过这些模型传递结构化数据，
保证 LLM 输出、工具参数、证据来源和 Trace 记录可以被稳定解析。
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from safemeal.shared.types import JsonObject, JsonValue


class ToolCall(BaseModel):
    """LLM 计划执行的一次工具调用。"""

    id: str = Field(min_length=1, max_length=128, description="本轮唯一调用编号")
    tool_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="必须是工具注册表中的名称",
    )
    arguments: JsonObject = Field(
        default_factory=dict,
        description="工具参数；由具体工具的 args_schema 做二次校验。",
    )
    purpose: str = Field(
        min_length=1, max_length=1_000, description="调用该工具要解决的问题"
    )
    success_criteria: str = Field(
        min_length=1,
        max_length=1_000,
        description="什么结果可视为本次调用成功",
    )


class PlanDecision(BaseModel):
    """首次规划或重新规划的结构化输出。"""

    decision: Literal["answer", "tools"]
    rationale: str
    direct_answer: Optional[str] = None
    calls: List[ToolCall] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "PlanDecision":
        if self.decision == "answer" and not (self.direct_answer or "").strip():
            raise ValueError("answer decisions require a non-empty direct_answer")
        if self.decision == "tools" and not self.calls:
            raise ValueError("tools decisions require at least one tool call")
        call_ids = [call.id for call in self.calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool call ids must be unique within a decision")
        return self


class Observation(BaseModel):
    """Observation 节点对一次工具执行结果的标准化记录。"""

    call_id: str
    tool_name: str
    purpose: str
    success_criteria: str
    ok: bool
    status: Literal["ok", "error", "timeout", "unavailable", "rejected"] = "ok"
    has_data: bool
    summary: str
    data: JsonValue = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    retryable: bool = False


class ReflectionDecision(BaseModel):
    """LLM 对当前证据是否充分作出的判断。"""

    decision: Literal["finish", "continue", "replan"]
    rationale: str
    evidence_sufficient: bool
    missing_information: List[str] = Field(default_factory=list)
    next_calls: List[ToolCall] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "ReflectionDecision":
        if self.decision == "continue" and not self.next_calls:
            raise ValueError("continue decisions require at least one tool call")
        call_ids = [call.id for call in self.next_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool call ids must be unique within a decision")
        return self
