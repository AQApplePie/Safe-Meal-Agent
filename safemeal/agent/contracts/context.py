"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
)
from safemeal.shared.types import JsonObject
from safemeal.modules.dietary.contracts.requirements import (
    DietaryRequirements,
)
from safemeal.shared.contracts.request_frame import RequestFrame


# 类说明（数据契约类）：AgentContext
# 作用：描述Agent 执行上下文的结构、类型及可校验字段。
class AgentContext(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")

    # 字段说明：conversation_history
    # 作用：按顺序组织的历史对话消息。
    # 类型：ConversationHistory。
    # 配置：默认值工厂（每次创建独立对象）=list；最大长度=40。
    conversation_history: ConversationHistory = Field(
        default_factory=list, max_length=40
    )
    # 字段说明：user_memories
    # 作用：已经加载的用户长期记忆。
    # 类型：list[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    user_memories: list[JsonObject] = Field(default_factory=list)
    # 字段说明：user_profile
    # 作用：用户画像与个人事实，用于任务个性化，区别于登录身份信息。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    user_profile: Optional[JsonObject] = None
    # 字段说明：dietary_constraints
    # 作用：用户饮食约束数据，包含过敏、限制与偏好。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    dietary_constraints: Optional[JsonObject] = None
    # 字段说明：requirements
    # 作用：本轮冻结的饮食或菜单执行要求。
    # 类型：DietaryRequirements | None。
    # 初始值：None。
    requirements: DietaryRequirements | None = None
    # 字段说明：intent
    # 作用：已识别的本轮请求意图。
    # 类型：Optional[str]。
    # 初始值：None。
    intent: Optional[str] = None
    # 字段说明：request_frame
    # 作用：已归一化的请求语义框架。
    # 类型：RequestFrame | None。
    # 初始值：None。
    request_frame: RequestFrame | None = None
    # 字段说明：episodic_memories
    # 作用：已加载的近期任务片段记忆。
    # 类型：list[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list；最大长度=100。
    episodic_memories: list[JsonObject] = Field(default_factory=list, max_length=100)
    # 字段说明：observations
    # 作用：本轮已获得的工具观察集合。
    # 类型：list[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list；最大长度=50。
    observations: list[JsonObject] = Field(default_factory=list, max_length=50)
    # 字段说明：context_metadata
    # 作用：上下文构建的元信息字典，用于保存加载来源、历史裁剪与摘要等过程信息。
    # 类型：JsonObject。
    # 配置：默认值工厂（每次创建独立对象）=dict。
    context_metadata: JsonObject = Field(default_factory=dict)

    # 方法说明：validate_conversation_history
    # 作用：校验历史消息格式及允许的角色。
    # 入参：
    #   history（ConversationHistory）：已加载的近期对话上下文。
    # 出参：ConversationHistory；历史对话上下文。
    @field_validator("conversation_history")
    @classmethod
    def validate_conversation_history(
        cls,
        history: ConversationHistory,
    ) -> ConversationHistory:
        allowed_roles = {"user", "assistant", "system"}
        for message in history:
            role = message.get("role", "")
            content = message.get("content", "")
            if role not in allowed_roles:
                raise ValueError(f"unsupported conversation role: {role!r}")
            if not content.strip() or len(content) > 5_000:
                raise ValueError(
                    "conversation message content must contain 1..5000 characters"
                )
        return history


# 类说明（数据契约类）：AgentContextPatch
# 作用：描述Agent 上下文局部更新的结构、类型及可校验字段。
class AgentContextPatch(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")

    # 字段说明：user_memories
    # 作用：已经加载的用户长期记忆。
    # 类型：list[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    user_memories: list[JsonObject] = Field(default_factory=list)
    # 字段说明：user_profile
    # 作用：用户画像与个人事实，用于任务个性化，区别于登录身份信息。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    user_profile: Optional[JsonObject] = None
    # 字段说明：episodic_memories
    # 作用：已加载的近期任务片段记忆。
    # 类型：list[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list；最大长度=100。
    episodic_memories: list[JsonObject] = Field(default_factory=list, max_length=100)
    # 字段说明：observations
    # 作用：本轮已获得的工具观察集合。
    # 类型：list[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list；最大长度=50。
    observations: list[JsonObject] = Field(default_factory=list, max_length=50)
    # 字段说明：context_metadata
    # 作用：上下文构建的补充元数据，用于记录裁剪、来源或加载情况。
    # 类型：JsonObject。
    # 配置：默认值工厂（每次创建独立对象）=dict。
    context_metadata: JsonObject = Field(default_factory=dict)
