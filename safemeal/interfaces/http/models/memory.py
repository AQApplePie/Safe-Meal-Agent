"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from safemeal.modules.conversation.contracts.memory.models import (
    MemoryStatus,
    UserMemoryRead,
)
from safemeal.shared.types import JsonObject


# 类说明（数据契约类）：UserMemoryUpdateRequest
# 作用：更新长期记忆的 HTTP 请求体。
class UserMemoryUpdateRequest(BaseModel):
    """更新长期记忆的 HTTP 请求体。"""

    # 字段说明：memory_value
    # 作用：长期记忆的人类可读内容。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1。
    memory_value: Optional[str] = Field(default=None, min_length=1)
    # 字段说明：confidence
    # 作用：该记忆事实的置信度，范围为 0 至 1；显式安全约束仍按可信规则处理。
    # 类型：Optional[float]。
    # 配置：默认值=None；最小值（含）=0.0；最大值（含）=1.0。
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Optional[MemoryStatus]。
    # 初始值：None。
    status: Optional[MemoryStatus] = None
    # 字段说明：memory_metadata
    # 作用：记忆的来源及辅助元数据。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    memory_metadata: Optional[JsonObject] = None


# 类说明（业务或基础设施实现类）：UserMemoryResponse
# 作用：长期记忆 HTTP 响应体。
class UserMemoryResponse(UserMemoryRead):
    """长期记忆 HTTP 响应体。"""
