"""已认证用户的食谱交互契约。"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ReactionKind = Literal["like", "favorite"]


# 类说明（数据契约类）：InteractionActor
# 作用：描述行为操作租户与用户主体的结构、类型及可校验字段。
class InteractionActor(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：tenant_id
    # 作用：可信租户标识，用于业务数据隔离。
    # 类型：str。
    # 配置：最小长度=1；最大长度=100。
    tenant_id: str = Field(min_length=1, max_length=100)
    # 字段说明：subject
    # 作用：当前身份的用户主体标识。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    subject: str = Field(min_length=1, max_length=255)


# 类说明（数据契约类）：RecipeInteraction
# 作用：描述用户食谱交互状态与计数的结构、类型及可校验字段。
class RecipeInteraction(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：recipe_id
    # 作用：目标食谱的整数标识。
    # 类型：int。
    recipe_id: int
    # 字段说明：liked
    # 作用：当前用户是否已点赞该菜谱。
    # 类型：bool。
    liked: bool
    # 字段说明：favorited
    # 作用：当前用户是否已收藏该菜谱。
    # 类型：bool。
    favorited: bool
    # 字段说明：like_count
    # 作用：菜谱当前点赞关系数量。
    # 类型：int。
    like_count: int
    # 字段说明：favorite_count
    # 作用：菜谱当前收藏关系数量。
    # 类型：int。
    favorite_count: int
