"""公共食谱浏览的精简列表契约；详情沿用 Recipe。"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .models import RecipeDifficulty


# 类说明（数据契约类）：RecipeSummary
# 作用：描述列表使用的食谱摘要的结构、类型及可校验字段。
class RecipeSummary(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：int。
    id: int
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：description
    # 作用：当前对象的说明文本。
    # 类型：str | None。
    description: str | None
    # 字段说明：total_time_minutes
    # 作用：制作或执行所需时间，单位为分钟。
    # 类型：int。
    total_time_minutes: int
    # 字段说明：servings
    # 作用：菜谱或菜单计划的用餐人数。
    # 类型：int。
    servings: int
    # 字段说明：difficulty
    # 作用：菜谱制作难度等级。
    # 类型：RecipeDifficulty。
    # 补充取值说明（类型别名或枚举）：
    #   easy：容易制作。
    #   medium：中等制作难度。
    #   hard：制作难度较高。
    difficulty: RecipeDifficulty
    # 字段说明：cuisine
    # 作用：食谱菜系筛选条件。
    # 类型：str | None。
    cuisine: str | None
    # 字段说明：calories
    # 作用：热量值，单位为千卡，具体基准由营养数据的 basis 指定。
    # 类型：Decimal。
    calories: Decimal


# 类说明（数据契约类）：RecipeListResponse
# 作用：描述食谱列表分页响应的结构、类型及可校验字段。
class RecipeListResponse(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)

    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[RecipeSummary, ...]。
    items: tuple[RecipeSummary, ...]
    # 字段说明：total
    # 作用：当前查询或结果集合的总数量。
    # 类型：int。
    total: int
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
