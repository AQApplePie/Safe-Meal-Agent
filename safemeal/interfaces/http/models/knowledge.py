"""知识库 HTTP 模型。

请求和响应模型独立于 Router，便于接口文档生成、单测和后续版本管理。
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from safemeal.shared.types import JsonObject


class RecipeModel(BaseModel):
    id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=500)
    category: Optional[str] = Field(default=None, max_length=128)
    difficulty: Optional[str] = Field(default=None, max_length=128)
    time: Optional[str] = Field(default=None, max_length=128)
    ingredients: Optional[List[str]] = Field(default=None, max_length=200)
    steps: Optional[List[str]] = Field(default=None, max_length=200)
    tips: Optional[str] = Field(default=None, max_length=5_000)
    nutrition: Optional[JsonObject] = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5_000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResponse(BaseModel):
    results: List[JsonObject]
    count: int
