"""本人收藏与有界批量交互读取契约。"""

from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field
from safemeal.modules.interaction.contracts.models import RecipeInteraction

RecipeId = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


# 类说明（数据契约类）：BatchInteractionQuery
# 作用：描述批量食谱交互查询请求的结构、类型及可校验字段。
class BatchInteractionQuery(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：recipe_ids
    # 作用：待查询或校验的食谱标识集合。
    # 类型：list[RecipeId]。
    # 配置：最小长度=1；最大长度=100。
    recipe_ids: list[RecipeId] = Field(min_length=1, max_length=100)


# 类说明（数据契约类）：BatchInteractionResponse
# 作用：描述批量食谱交互查询响应的结构、类型及可校验字段。
class BatchInteractionResponse(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[RecipeInteraction, ...]。
    items: tuple[RecipeInteraction, ...]
    # 字段说明：missing_recipe_ids
    # 作用：请求的菜谱中未查到的标识集合。
    # 类型：tuple[int, ...]。
    missing_recipe_ids: tuple[int, ...]


# 类说明（数据契约类）：FavoriteEntry
# 作用：描述收藏食谱条目的结构、类型及可校验字段。
class FavoriteEntry(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：recipe_id
    # 作用：目标食谱的整数标识。
    # 类型：int。
    recipe_id: int
    # 字段说明：recipe_name
    # 作用：目标菜谱名称。
    # 类型：str。
    recipe_name: str
    # 字段说明：favorited_at
    # 作用：当前用户收藏菜谱的时间。
    # 类型：datetime。
    favorited_at: datetime


# 类说明（数据契约类）：FavoritePage
# 作用：描述收藏列表分页结果的结构、类型及可校验字段。
class FavoritePage(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[FavoriteEntry, ...]。
    items: tuple[FavoriteEntry, ...]
    # 字段说明：offset
    # 作用：本次分页跳过的记录数量。
    # 类型：int。
    offset: int
    # 字段说明：limit
    # 作用：本次查询或处理的最大条目数。
    # 类型：int。
    limit: int
    # 字段说明：has_more
    # 作用：当前页之后是否仍有可查询记录。
    # 类型：bool。
    has_more: bool
