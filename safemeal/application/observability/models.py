"""Agent 运行时 Trace 数据模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from safemeal.shared.types import JsonObject, JsonValue


TraceStatus = Literal["running", "ok", "error"]


def utc_now() -> datetime:
    """生成带 UTC 时区的当前时间。"""

    return datetime.now(timezone.utc)


class TokenUsage(BaseModel):
    """一次或一组模型调用的 Token 用量。"""

    input_tokens: int = Field(default=0, ge=0, description="输入 Token。")
    output_tokens: int = Field(default=0, ge=0, description="输出 Token。")
    total_tokens: int = Field(default=0, ge=0, description="总 Token。")
    cached_tokens: int = Field(default=0, ge=0, description="缓存命中的 Token。")


class SpanTrace(BaseModel):
    """Agent 节点或内部阶段的通用耗时记录。"""

    span_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description="Span 唯一 ID。",
    )
    kind: str = Field(description="Span 类型，例如 agent_node。")
    name: str = Field(description="节点或阶段名称。")
    started_at: datetime = Field(default_factory=utc_now, description="开始时间。")
    finished_at: Optional[datetime] = Field(default=None, description="结束时间。")
    duration_ms: Optional[float] = Field(default=None, description="耗时毫秒数。")
    status: TraceStatus = Field(default="running", description="执行状态。")
    input: JsonValue = Field(default=None, description="尺寸受控的阶段输入。")
    output: JsonValue = Field(default=None, description="尺寸受控的阶段输出。")
    error: Optional[str] = Field(default=None, description="错误信息。")


class ModelCallTrace(BaseModel):
    """Planner、Reflection、Responder 的单次模型调用记录。"""

    call_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description="模型调用唯一 ID。",
    )
    stage: str = Field(description="调用阶段。")
    model: str = Field(description="模型名称。")
    temperature: float = Field(description="调用温度。")
    started_at: datetime = Field(description="开始时间。")
    finished_at: datetime = Field(description="结束时间。")
    latency_ms: float = Field(ge=0, description="调用耗时毫秒数。")
    messages: JsonValue = Field(description="尺寸受控的模型输入消息。")
    response: JsonValue = Field(description="尺寸受控的解析后响应。")
    usage: TokenUsage = Field(default_factory=TokenUsage, description="Token 用量。")
    usage_available: bool = Field(description="供应商是否返回可信 usage。")
    error: Optional[str] = Field(default=None, description="调用错误信息。")


class ToolCallTrace(BaseModel):
    """单次工具调用的参数、校验、结果和耗时。"""

    call_id: str = Field(description="Agent 生成的工具调用 ID。")
    tool_name: str = Field(description="工具名称。")
    started_at: datetime = Field(description="开始时间。")
    finished_at: datetime = Field(description="结束时间。")
    latency_ms: float = Field(ge=0, description="工具耗时毫秒数。")
    arguments: JsonObject = Field(
        default_factory=dict,
        description="尺寸受控的原始参数。",
    )
    arguments_valid: bool = Field(description="参数是否通过 Pydantic 校验。")
    validation_error: Optional[str] = Field(
        default=None,
        description="参数校验错误。",
    )
    ok: bool = Field(description="工具是否执行成功。")
    status: str = Field(default="ok", description="稳定工具状态。")
    result: JsonValue = Field(default=None, description="尺寸受控的工具结果。")
    error: Optional[str] = Field(default=None, description="工具错误信息。")
    error_code: Optional[str] = Field(default=None, description="稳定工具错误码。")
    retryable: bool = Field(default=False, description="该失败是否可安全重试。")


class AgentRunTrace(BaseModel):
    """一次用户请求对应的完整运行轨迹。"""

    run_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description="运行唯一 ID。",
    )
    session_id: str = Field(description="业务会话 ID。")
    question: str = Field(description="当前用户问题。")
    started_at: datetime = Field(default_factory=utc_now, description="开始时间。")
    finished_at: Optional[datetime] = Field(default=None, description="结束时间。")
    total_latency_ms: Optional[float] = Field(
        default=None,
        description="请求总耗时毫秒数。",
    )
    status: TraceStatus = Field(default="running", description="请求最终状态。")
    iterations: int = Field(default=0, ge=0, description="工具执行轮次。")
    final_answer: str = Field(default="", description="最终答案。")
    sources: List[JsonObject] = Field(
        default_factory=list,
        description="最终返回来源。",
    )
    spans: List[SpanTrace] = Field(
        default_factory=list,
        description="Agent 节点与内部阶段 Span。",
    )
    model_calls: List[ModelCallTrace] = Field(
        default_factory=list,
        description="模型调用记录。",
    )
    tool_calls: List[ToolCallTrace] = Field(
        default_factory=list,
        description="工具调用记录。",
    )
    error: Optional[str] = Field(default=None, description="请求级错误。")
    metadata: JsonObject = Field(
        default_factory=dict,
        description="运行配置标签等附加元数据。",
    )

    @property
    def token_usage(self) -> TokenUsage:
        """聚合当前 Agent 决策模型调用的 Token。"""

        input_tokens = sum(item.usage.input_tokens for item in self.model_calls)
        output_tokens = sum(item.usage.output_tokens for item in self.model_calls)
        cached_tokens = sum(item.usage.cached_tokens for item in self.model_calls)
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cached_tokens=cached_tokens,
        )
