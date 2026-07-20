"""LightRAG HTTP 请求与响应模型。"""

from typing import List, Optional

from pydantic import BaseModel, Field

from SafeMealAgent.back.application.contracts.lightrag import SearchMode
from SafeMealAgent.back.shared.types import JsonObject


class LightRAGQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5_000, description="查询问题")
    mode: SearchMode = Field(default="hybrid", description="检索模式")
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    stream: bool = Field(default=False, description="是否使用流式响应")


class LightRAGQueryResponse(BaseModel):
    query: str
    response: str
    mode: SearchMode
    metadata: JsonObject = Field(default_factory=dict)


class LightRAGInsertRequest(BaseModel):
    documents: List[str] = Field(..., min_length=1, max_length=100)


class LightRAGInsertResponse(BaseModel):
    total: int
    success: int
    already_present: int = 0
    failed: int
    errors: List[str] = Field(default_factory=list)
