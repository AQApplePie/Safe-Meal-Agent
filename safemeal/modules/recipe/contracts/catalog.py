"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from safemeal.modules.recipe.contracts.models import (
    DietaryType,
    Recipe,
    RecipeDifficulty,
)
from safemeal.modules.recipe.contracts.lookup import RecipeCandidate
from safemeal.modules.recipe.contracts.lookup import MenuRecipeCandidate
from safemeal.shared.contracts.request_frame import MenuCategory

FoodCategory = Literal["fish", "seafood", "vegetarian"]


# 类说明（枚举类）：RecipeSortField
# 作用：限定食谱排序字段枚举的允许取值，统一业务分支判定。
class RecipeSortField(str, Enum):
    # 字段说明：NAME
    # 作用：按菜谱名称排序。
    # 初始值：'name'。
    # 取值说明：
    #   name：菜谱名称排序字段。
    NAME = "name"
    # 字段说明：TOTAL_TIME
    # 作用：TOTALTIME，供该组件初始化及运行控制使用。
    # 初始值：'total_time'。
    # 取值说明：
    #   total_time：菜谱总制作时间排序字段。
    TOTAL_TIME = "total_time"
    # 字段说明：CALORIES
    # 作用：按菜谱总热量字段排序。
    # 初始值：'total_calories'。
    # 取值说明：
    #   total_calories：菜谱总热量排序字段。
    CALORIES = "total_calories"


# 类说明（数据契约类）：RecipeQuery
# 作用：描述食谱筛选与推荐查询的结构、类型及可校验字段。
class RecipeQuery(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：name_contains
    # 作用：菜名包含匹配的搜索词。
    # 类型：str | None。
    # 配置：默认值=None；最小长度=1；最大长度=255。
    name_contains: str | None = Field(default=None, min_length=1, max_length=255)
    # 字段说明：include_ingredients
    # 作用：推荐结果必须包含的食材词项集合。
    # 类型：tuple[str, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=20。
    include_ingredients: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    # 字段说明：exclude_ingredients
    # 作用：必须排除的食材集合。
    # 类型：tuple[str, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=50。
    exclude_ingredients: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    # 字段说明：difficulties
    # 作用：允许的食谱难度集合。
    # 类型：tuple[RecipeDifficulty, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=3。
    # 补充取值说明（类型别名或枚举）：
    #   easy：容易制作。
    #   medium：中等制作难度。
    #   hard：制作难度较高。
    difficulties: tuple[RecipeDifficulty, ...] = Field(
        default_factory=tuple, max_length=3
    )
    # 字段说明：cuisine
    # 作用：食谱菜系筛选条件。
    # 类型：str | None。
    # 配置：默认值=None；最小长度=1；最大长度=255。
    cuisine: str | None = Field(default=None, min_length=1, max_length=255)
    # 字段说明：max_total_time_minutes
    # 作用：食谱制作总时长上限，单位分钟。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=0；最大值（含）=7 * 24 * 60。
    max_total_time_minutes: int | None = Field(default=None, ge=0, le=7 * 24 * 60)
    # 字段说明：max_calories
    # 作用：食谱热量上限。
    # 类型：Decimal | None。
    # 配置：默认值=None；最小值（含）=0；最大值（含）=100000。
    max_calories: Decimal | None = Field(default=None, ge=0, le=100000)
    # 字段说明：dietary_types
    # 作用：本轮要求满足的饮食类型集合。
    # 类型：tuple[DietaryType, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=3。
    # 补充取值说明（类型别名或枚举）：
    #   vegetarian：素食类型或素菜分类。
    #   vegan：纯素饮食类型。
    #   pescatarian：鱼素饮食类型。
    dietary_types: tuple[DietaryType, ...] = Field(default_factory=tuple, max_length=3)
    # 字段说明：food_categories
    # 作用：菜品或食材的分类标签，参与过滤与菜单配额判断。
    # 类型：tuple[FoodCategory, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=3。
    # 取值说明：
    #   fish：鱼类。
    #   seafood：海鲜类。
    #   vegetarian：素食类型或素菜分类。
    food_categories: tuple[FoodCategory, ...] = Field(
        default_factory=tuple, max_length=3
    )
    # 字段说明：exclude_food_categories
    # 作用：检索时必须排除的食材类别。
    # 类型：tuple[FoodCategory, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=3。
    # 取值说明：
    #   fish：鱼类。
    #   seafood：海鲜类。
    #   vegetarian：素食类型或素菜分类。
    exclude_food_categories: tuple[FoodCategory, ...] = Field(
        default_factory=tuple, max_length=3
    )
    # 字段说明：sort_by
    # 作用：食谱排序字段。
    # 类型：RecipeSortField。
    # 补充取值说明（类型别名或枚举）：
    #   name：菜谱名称排序字段。
    #   total_time：菜谱总制作时间排序字段。
    #   total_calories：菜谱总热量排序字段。
    sort_by: RecipeSortField = RecipeSortField.NAME
    # 字段说明：sort_order
    # 作用：升序或降序排序方向。
    # 类型：Literal['asc', 'desc']。
    # 初始值：'asc'。
    # 取值说明：
    #   asc：按升序排列。
    #   desc：按降序排列。
    sort_order: Literal["asc", "desc"] = "asc"
    # 字段说明：offset
    # 作用：本次分页跳过的记录数量。
    # 类型：int。
    # 配置：默认值=0；最小值（含）=0；最大值（含）=100000。
    offset: int = Field(default=0, ge=0, le=100000)
    # 字段说明：limit
    # 作用：本次查询或处理的最大条目数。
    # 类型：int。
    # 配置：默认值=10；最小值（含）=1；最大值（含）=50。
    limit: int = Field(default=10, ge=1, le=50)
    # 字段说明：requested_count
    # 作用：用户要求返回的菜谱数量。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1；最大值（含）=50。
    requested_count: int | None = Field(default=None, ge=1, le=50)

    # 字段说明：exact_name
    # 作用：精确匹配使用的菜名。
    # 类型：bool。
    # 初始值：False。
    exact_name: bool = False
    # 字段说明：required_fields
    # 作用：必须存在的字段集合。
    # 类型：tuple[Literal['ingredients', 'steps', 'time', 'nutrition'], ...]。
    # 初始值：()。
    # 取值说明：
    #   ingredients：食材清单。
    #   steps：制作步骤。
    #   time：制作时间。
    #   nutrition：营养信息。
    required_fields: tuple[
        Literal["ingredients", "steps", "time", "nutrition"], ...
    ] = ()
    # 字段说明：category
    # 作用：目标食材或菜品分类。
    # 类型：MenuCategory | None。
    # 初始值：None。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    category: MenuCategory | None = None
    # 字段说明：candidate_mode
    # 作用：候选检索的模式，影响候选的匹配与生成路径。
    # 类型：bool。
    # 初始值：False。
    candidate_mode: bool = False
    # 字段说明：exclude_recipe_ids
    # 作用：排除的菜谱标识，避免重复推荐或返回已筛除菜品。
    # 类型：tuple[int, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=200。
    exclude_recipe_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=200)
    # 字段说明：exclude_recipe_names
    # 作用：排除的菜名集合，在缺少标识时仍可去重。
    # 类型：tuple[str, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=200。
    exclude_recipe_names: tuple[str, ...] = Field(default_factory=tuple, max_length=200)
    # 字段说明：scope
    # 作用：当前请求或查询的可信范围。
    # 类型：Literal['local', 'all']。
    # 初始值：'local'。
    # 取值说明：
    #   local：使用本地实现或本地数据。
    #   all：全部类别或结果。
    scope: Literal["local", "all"] = "local"

    # 方法说明：normalize_terms
    # 作用：归一化并去重查询词项。
    # 入参：
    #   value（object）：当前待转换或校验的值。
    # 出参：object；由调用约定决定的数据对象。
    @field_validator("include_ingredients", "exclude_ingredients", mode="before")
    @classmethod
    def normalize_terms(cls, value: object) -> object:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("ingredient filters must be a list or tuple")
        values = [str(item).strip() for item in value]
        return tuple(dict.fromkeys(item for item in values if item))


# 类说明（数据契约类）：RecipeSearchResult
# 作用：描述食谱查询与推荐结果的结构、类型及可校验字段。
class RecipeSearchResult(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[Recipe | RecipeCandidate | MenuRecipeCandidate, ...]。
    items: tuple[Recipe | RecipeCandidate | MenuRecipeCandidate, ...]
    # 字段说明：total
    # 作用：当前查询或结果集合的总数量。
    # 类型：int。
    # 配置：最小值（含）=0。
    total: int = Field(ge=0)
    # 字段说明：offset
    # 作用：本次分页跳过的记录数量。
    # 类型：int。
    # 配置：最小值（含）=0。
    offset: int = Field(ge=0)
    # 字段说明：limit
    # 作用：本次查询或处理的最大条目数。
    # 类型：int。
    # 配置：最小值（含）=1。
    limit: int = Field(ge=1)
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['FOUND', 'PARTIAL', 'NOT_FOUND', 'ERROR', 'FIELD_MISSING']。
    # 初始值：'FOUND'。
    # 取值说明：
    #   FOUND：查到目标记录。
    #   PARTIAL：仅返回部分结果。
    #   NOT_FOUND：未查到目标记录。
    #   ERROR：查询或执行失败。
    #   FIELD_MISSING：目标记录存在但要求的字段缺失。
    status: Literal["FOUND", "PARTIAL", "NOT_FOUND", "ERROR", "FIELD_MISSING"] = "FOUND"
    # 字段说明：requested_count
    # 作用：用户要求返回的菜谱数量。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1；最大值（含）=50。
    requested_count: int | None = Field(default=None, ge=1, le=50)
    # 字段说明：fulfilled_count
    # 作用：当前已完成的目标或配额数量。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=0；最大值（含）=50。
    fulfilled_count: int | None = Field(default=None, ge=0, le=50)
    # 字段说明：missing_fields
    # 作用：结果缺少的字段名称，用于提示不完整性或补查。
    # 类型：tuple[Literal['ingredients', 'steps', 'time', 'nutrition'], ...]。
    # 初始值：()。
    # 取值说明：
    #   ingredients：食材清单。
    #   steps：制作步骤。
    #   time：制作时间。
    #   nutrition：营养信息。
    missing_fields: tuple[
        Literal["ingredients", "steps", "time", "nutrition"], ...
    ] = ()
    # 字段说明：query
    # 作用：结构化查询条件或检索问题。
    # 类型：str | None。
    # 初始值：None。
    query: str | None = None
    # 字段说明：exact_name
    # 作用：精确匹配使用的菜名。
    # 类型：bool。
    # 初始值：False。
    exact_name: bool = False
    # 字段说明：match_type
    # 作用：检索结果采用的匹配方式。
    # 类型：Literal['exact', 'normalized', 'lexical', 'none']。
    # 初始值：'none'。
    # 取值说明：
    #   exact：精确匹配。
    #   normalized：数据已经归一化。
    #   lexical：词法匹配或检索。
    #   none：无相应策略或值。
    match_type: Literal["exact", "normalized", "lexical", "none"] = "none"
    # 字段说明：searched_sources
    # 作用：本次已查询的数据源，用于解释覆盖范围与降级结果。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    searched_sources: tuple[str, ...] = ()
    # 字段说明：errors
    # 作用：执行或校验过程中产生的错误信息集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    errors: tuple[str, ...] = ()


__all__ = ["RecipeQuery", "RecipeSearchResult", "RecipeSortField"]
