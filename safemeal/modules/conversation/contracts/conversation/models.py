"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from typing import Optional, TypeAlias

from pydantic import BaseModel, Field

ConversationMessage: TypeAlias = dict[str, str]
ConversationHistory: TypeAlias = list[ConversationMessage]


# 类说明（数据契约类）：AnswerSource
# 作用：最终答案引用的来源信息。
class AnswerSource(BaseModel):
    """最终答案引用的来源信息。"""

    # 字段说明：source
    # 作用：来源名称，例如 mysql:recipes、retrieval 或文档路径。
    # 类型：str。
    source: str = Field(
        description="来源名称，例如 mysql:recipes、retrieval 或文档路径。"
    )
    # 字段说明：tool
    # 作用：产生该来源的工具名。
    # 类型：str。
    # 配置：默认值=''。
    tool: str = Field(default="", description="产生该来源的工具名。")
    # 字段说明：call_id
    # 作用：对应工具调用 ID。
    # 类型：str。
    # 配置：默认值=''。
    call_id: str = Field(default="", description="对应工具调用 ID。")
    # 字段说明：document_id
    # 作用：文档标识。
    # 类型：str | None。
    # 初始值：None。
    document_id: str | None = None
    # 字段说明：chunk_id
    # 作用：文档切片唯一标识，用于检索定位及引用溯源。
    # 类型：str | None。
    # 初始值：None。
    chunk_id: str | None = None
    # 字段说明：query
    # 作用：可选 SQL/Cypher/检索查询。
    # 类型：Optional[str]。
    # 配置：默认值=None。
    query: Optional[str] = Field(default=None, description="可选 SQL/Cypher/检索查询。")
    # 字段说明：evidence_call_ids
    # 作用：聚合来源时关联的底层证据调用 ID。
    # 类型：list[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    evidence_call_ids: list[str] = Field(
        default_factory=list,
        description="聚合来源时关联的底层证据调用 ID。",
    )


# 类说明（数据契约类）：RouterInfo
# 作用：Agent 最终路由说明。
class RouterInfo(BaseModel):
    """Agent 最终路由说明。"""

    # 字段说明：type
    # 作用：路由类型，例如 agent-tools-loop。
    # 类型：str。
    type: str = Field(description="路由类型，例如 agent-tools-loop。")
    # 字段说明：logic
    # 作用：本轮路由或反思理由。
    # 类型：str。
    logic: str = Field(description="本轮路由或反思理由。")
