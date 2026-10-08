"""定义跨层传递的稳定数据契约。"""

from dataclasses import dataclass
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class ModelPrice:
    input_cost_per_million: float
    output_cost_per_million: float
    cached_input_cost_per_million: float


class TokenUsage(BaseModel):
    """一次或一组模型调用的 Token 用量。"""

    input_tokens: int = Field(default=0, ge=0, description="输入 Token。")
    output_tokens: int = Field(default=0, ge=0, description="输出 Token。")
    total_tokens: int = Field(default=0, ge=0, description="总 Token。")
    cached_tokens: int = Field(default=0, ge=0, description="缓存命中的 Token。")
