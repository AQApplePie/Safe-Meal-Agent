"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from safemeal.modules.recipe.contracts.models import DietaryType


# 类说明（数据契约类）：RecipeGenerationRequest
# 作用：描述结构化食谱生成请求的结构、类型及可校验字段。
class RecipeGenerationRequest(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：requirements
    # 作用：本轮冻结的饮食或菜单执行要求。
    # 类型：str。
    # 配置：最小长度=1；最大长度=5000。
    requirements: str = Field(min_length=1, max_length=5000)
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
    # 字段说明：dietary_types
    # 作用：本轮要求满足的饮食类型集合。
    # 类型：tuple[DietaryType, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=3。
    # 补充取值说明（类型别名或枚举）：
    #   vegetarian：素食类型或素菜分类。
    #   vegan：纯素饮食类型。
    #   pescatarian：鱼素饮食类型。
    dietary_types: tuple[DietaryType, ...] = Field(default_factory=tuple, max_length=3)
    # 字段说明：servings
    # 作用：菜谱或菜单计划的用餐人数。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1；最大值（含）=100。
    servings: int | None = Field(default=None, ge=1, le=100)
    # 字段说明：max_total_time_minutes
    # 作用：食谱制作总时长上限，单位分钟。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1；最大值（含）=24 * 60。
    max_total_time_minutes: int | None = Field(default=None, ge=1, le=24 * 60)

    # 方法说明：normalize_ingredient_terms
    # 作用：归一化食材名称或词项，统一安全匹配依据。
    # 入参：
    #   value（object）：当前待转换或校验的值。
    # 出参：object；由调用约定决定的数据对象。
    @field_validator("include_ingredients", "exclude_ingredients", mode="before")
    @classmethod
    def normalize_ingredient_terms(cls, value: object) -> object:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("ingredient constraints must be a list or tuple")
        return tuple(
            dict.fromkeys(str(item).strip() for item in value if str(item).strip())
        )


__all__ = ["RecipeGenerationRequest"]
