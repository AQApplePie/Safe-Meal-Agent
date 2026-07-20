"""LightRAG 应用契约。

应用层使用这些模型表达 LightRAG 查询和写入结果，与 HTTP 请求/响应模型解耦。
"""

from typing import List, Literal

from pydantic import BaseModel, Field

SearchMode = Literal["naive", "local", "global", "hybrid", "mix", "bypass"]


class LightRAGInsertResult(BaseModel):
    total: int
    success: int
    already_present: int = 0
    failed: int
    errors: List[str] = Field(default_factory=list)
