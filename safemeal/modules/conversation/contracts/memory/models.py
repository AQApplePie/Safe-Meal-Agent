"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from safemeal.shared.types import JsonObject


MemoryType: TypeAlias = Literal[
    "dietary_allergy",
    "dietary_restriction",
    "taste_dislike",
    "taste_preference",
    "cooking_constraint",
    "cooking_equipment",
    "cooking_time",
    "health_goal",
    "conversation_episode",
]
MemoryStatus: TypeAlias = Literal["active", "archived"]
MemorySource: TypeAlias = Literal[
    "explicit_user_statement", "conversation_summary", "manual"
]


# 类说明（数据契约类）：UserMemoryCreate
# 作用：创建或更新一条用户长期记忆。
class UserMemoryCreate(BaseModel):
    """创建或更新一条用户长期记忆。"""

    # 字段说明：user_id
    # 作用：用户标识。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    user_id: str = Field(..., min_length=1, max_length=255, description="用户标识。")
    # 字段说明：memory_type
    # 作用：记忆类型。
    # 类型：MemoryType。
    # 取值说明：
    #   dietary_allergy：持久化过敏记忆。
    #   dietary_restriction：持久化饮食限制记忆。
    #   taste_dislike：持久化口味厌恶记忆。
    #   taste_preference：持久化口味喜好记忆。
    #   cooking_constraint：制作条件约束。
    #   cooking_equipment：可用厨具记忆。
    #   cooking_time：烹饪时间要求记忆。
    #   health_goal：持久化健康目标记忆。
    #   conversation_episode：历史对话的事件片段。
    memory_type: MemoryType = Field(..., description="记忆类型。")
    # 字段说明：memory_key
    # 作用：用于去重和检索的记忆键。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    memory_key: str = Field(
        ..., min_length=1, max_length=255, description="用于去重和检索的记忆键。"
    )
    # 字段说明：memory_value
    # 作用：可展示给 Agent 的记忆内容。
    # 类型：str。
    # 配置：最小长度=1；最大长度=2000。
    memory_value: str = Field(
        ..., min_length=1, max_length=2_000, description="可展示给 Agent 的记忆内容。"
    )
    # 字段说明：confidence
    # 作用：记忆置信度；显式过敏/忌口通常接近 1。
    # 类型：float。
    # 配置：默认值=1.0；最小值（含）=0.0；最大值（含）=1.0。
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="记忆置信度；显式过敏/忌口通常接近 1。",
    )
    # 字段说明：source
    # 作用：记忆来源，例如 explicit_user_statement/manual。
    # 类型：MemorySource。
    # 配置：默认值='explicit_user_statement'。
    # 取值说明：
    #   explicit_user_statement：用户明确表达的事实。
    #   conversation_summary：历史对话摘要。
    #   manual：人工指定的模式。
    source: MemorySource = Field(
        default="explicit_user_statement",
        description="记忆来源，例如 explicit_user_statement/manual。",
    )
    # 字段说明：source_session_id
    # 作用：产生这条记忆的会话 ID。
    # 类型：Optional[str]。
    # 配置：默认值=None；最大长度=255。
    source_session_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="产生这条记忆的会话 ID。",
    )
    # 字段说明：source_message_id
    # 作用：产生这条记忆的消息 ID；没有时可为空。
    # 类型：Optional[str]。
    # 配置：默认值=None；最大长度=255。
    source_message_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="产生这条记忆的消息 ID；没有时可为空。",
    )
    # 字段说明：memory_metadata
    # 作用：额外结构化信息，例如禁忌食材展开、抽取规则版本等。
    # 类型：Optional[JsonObject]。
    # 配置：默认值=None。
    memory_metadata: Optional[JsonObject] = Field(
        default=None,
        description="额外结构化信息，例如禁忌食材展开、抽取规则版本等。",
    )


# 类说明（数据契约类）：UserMemoryUpdate
# 作用：更新一条用户长期记忆。
class UserMemoryUpdate(BaseModel):
    """更新一条用户长期记忆。"""

    # 字段说明：memory_value
    # 作用：长期记忆的人类可读内容。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1；最大长度=1000。
    memory_value: Optional[str] = Field(default=None, min_length=1, max_length=1_000)
    # 字段说明：confidence
    # 作用：该记忆事实的置信度，范围为 0 至 1；显式安全约束仍按可信规则处理。
    # 类型：Optional[float]。
    # 配置：默认值=None；最小值（含）=0.0；最大值（含）=1.0。
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # 字段说明：status
    # 作用：记忆生命周期状态，active 表示生效，archived 表示归档。
    # 类型：Optional[MemoryStatus]。
    # 配置：默认值=None。
    # 取值说明：
    #   active：处于可用状态。
    #   archived：已归档。
    status: Optional[MemoryStatus] = Field(
        default=None, description="active/archived。"
    )
    # 字段说明：memory_metadata
    # 作用：记忆的来源及辅助元数据。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    memory_metadata: Optional[JsonObject] = None


# 类说明（数据契约类）：UserMemoryRead
# 作用：读取用户长期记忆时返回的稳定视图。
class UserMemoryRead(BaseModel):
    """读取用户长期记忆时返回的稳定视图。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    model_config = ConfigDict(from_attributes=True)

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：int。
    id: int
    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 类型：str。
    user_id: str
    # 字段说明：memory_type
    # 作用：长期记忆类型。
    # 类型：MemoryType。
    # 取值说明：
    #   dietary_allergy：持久化过敏记忆。
    #   dietary_restriction：持久化饮食限制记忆。
    #   taste_dislike：持久化口味厌恶记忆。
    #   taste_preference：持久化口味喜好记忆。
    #   cooking_constraint：制作条件约束。
    #   cooking_equipment：可用厨具记忆。
    #   cooking_time：烹饪时间要求记忆。
    #   health_goal：持久化健康目标记忆。
    #   conversation_episode：历史对话的事件片段。
    memory_type: MemoryType
    # 字段说明：memory_key
    # 作用：机器可读的长期记忆事实键。
    # 类型：str。
    memory_key: str
    # 字段说明：memory_value
    # 作用：长期记忆的人类可读内容。
    # 类型：str。
    memory_value: str
    # 字段说明：confidence
    # 作用：该记忆事实的置信度，范围为 0 至 1；显式安全约束仍按可信规则处理。
    # 类型：float。
    confidence: float
    # 字段说明：source
    # 作用：数据来源标识或提供该数据的对象。
    # 类型：MemorySource。
    # 取值说明：
    #   explicit_user_statement：用户明确表达的事实。
    #   conversation_summary：历史对话摘要。
    #   manual：人工指定的模式。
    source: MemorySource
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：MemoryStatus。
    # 取值说明：
    #   active：处于可用状态。
    #   archived：已归档。
    status: MemoryStatus
    # 字段说明：source_session_id
    # 作用：记忆或结果对应的来源会话标识。
    # 类型：Optional[str]。
    # 初始值：None。
    source_session_id: Optional[str] = None
    # 字段说明：source_message_id
    # 作用：记忆或结果对应的来源消息标识。
    # 类型：Optional[str]。
    # 初始值：None。
    source_message_id: Optional[str] = None
    # 字段说明：memory_metadata
    # 作用：记忆的来源及辅助元数据。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    memory_metadata: Optional[JsonObject] = None
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：datetime。
    created_at: datetime
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：Optional[datetime]。
    # 初始值：None。
    updated_at: Optional[datetime] = None
    # 字段说明：last_used_at
    # 作用：凭据或资源最近一次使用时间。
    # 类型：Optional[datetime]。
    # 初始值：None。
    last_used_at: Optional[datetime] = None
