"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# 类说明（数据契约类）：ChatSessionUpdateRequest
# 作用：描述聊天会话 HTTP 更新请求的结构、类型及可校验字段。
class ChatSessionUpdateRequest(BaseModel):

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")

    # 字段说明：title
    # 作用：会话、文档或菜谱标题。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1；最大长度=500。
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    # 字段说明：is_active
    # 作用：该记录或约束是否处于生效状态。
    # 类型：Optional[bool]。
    # 初始值：None。
    is_active: Optional[bool] = None

    # 方法说明：require_change
    # 作用：校验会话更新至少包含一个可修改字段，且显式字段不能为无效空值。
    # 入参：
    #   无显式入参。
    # 出参：'ChatSessionUpdateRequest'；聊天会话 HTTP 更新请求。
    @model_validator(mode="after")
    def require_change(self) -> "ChatSessionUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one session field must be provided")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active cannot be null")
        return self


# 类说明（数据契约类）：ChatSessionResponse
# 作用：描述聊天会话 HTTP 响应的结构、类型及可校验字段。
class ChatSessionResponse(BaseModel):

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    model_config = ConfigDict(from_attributes=True)

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：str。
    id: str
    # 字段说明：title
    # 作用：会话、文档或菜谱标题。
    # 类型：str。
    title: str
    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 类型：str。
    user_id: str
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：datetime。
    created_at: datetime
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：Optional[datetime]。
    updated_at: Optional[datetime]
    # 字段说明：is_active
    # 作用：该记录或约束是否处于生效状态。
    # 类型：bool。
    is_active: bool

    # 方法说明：normalize_utc
    # 作用：将日期时间归一化为 UTC，统一时间比较与存储语义。
    # 入参：
    #   value（Optional[datetime]）：当前待转换或校验的值。
    # 出参：Optional[datetime]；日期时间或 None。
    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def normalize_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = [
    "ChatSessionResponse",
    "ChatSessionUpdateRequest",
]
