"""定义跨层传递的稳定数据契约。"""

from dataclasses import dataclass
from pydantic import BaseModel, Field


# 类说明（数据契约类）：ModelPrice
# 作用：描述模型输入输出与缓存价格的结构、类型及可校验字段。
@dataclass(frozen=True)
class ModelPrice:
    # 字段说明：input_cost_per_million
    # 作用：每百万输入令牌的单价。
    # 类型：float。
    input_cost_per_million: float
    # 字段说明：output_cost_per_million
    # 作用：每百万输出令牌的单价。
    # 类型：float。
    output_cost_per_million: float
    # 字段说明：cached_input_cost_per_million
    # 作用：每百万缓存命中输入令牌的单价，供调用成本核算。
    # 类型：float。
    cached_input_cost_per_million: float


# 类说明（数据契约类）：TokenUsage
# 作用：一次或一组模型调用的 Token 用量。
class TokenUsage(BaseModel):
    """一次或一组模型调用的 Token 用量。"""

    # 字段说明：input_tokens
    # 作用：输入 Token。
    # 类型：int。
    # 配置：默认值=0；最小值（含）=0。
    input_tokens: int = Field(default=0, ge=0, description="输入 Token。")
    # 字段说明：output_tokens
    # 作用：输出 Token。
    # 类型：int。
    # 配置：默认值=0；最小值（含）=0。
    output_tokens: int = Field(default=0, ge=0, description="输出 Token。")
    # 字段说明：total_tokens
    # 作用：总 Token。
    # 类型：int。
    # 配置：默认值=0；最小值（含）=0。
    total_tokens: int = Field(default=0, ge=0, description="总 Token。")
    # 字段说明：cached_tokens
    # 作用：缓存命中的 Token。
    # 类型：int。
    # 配置：默认值=0；最小值（含）=0。
    cached_tokens: int = Field(default=0, ge=0, description="缓存命中的 Token。")
