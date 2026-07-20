"""运行时可观测性工具。

这里仅负责记录 Agent 实际发生了什么，不负责判断结果是否正确。
"""

from .models import (
    AgentRunTrace,
    ModelCallTrace,
    SpanTrace,
    TokenUsage,
    ToolCallTrace,
)
from .payload import safe_trace_payload
from .recorder import (
    AgentTraceRecorder,
    current_trace,
    record_model_call,
    trace_json,
    trace_span,
    use_trace,
)
from .streaming import answer_stream_active, emit_answer_chunk, use_answer_stream
from .correlation import current_request_id, use_request_id

__all__ = [
    "AgentRunTrace",
    "AgentTraceRecorder",
    "ModelCallTrace",
    "SpanTrace",
    "TokenUsage",
    "ToolCallTrace",
    "current_trace",
    "record_model_call",
    "safe_trace_payload",
    "trace_json",
    "trace_span",
    "use_trace",
    "answer_stream_active",
    "emit_answer_chunk",
    "use_answer_stream",
    "current_request_id",
    "use_request_id",
]
