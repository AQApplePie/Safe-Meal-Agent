"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safemeal.modules.recipe.contracts.models import (
    DietaryType,
    NonBlankText,
    NutritionInfo,
    RecipeDifficulty,
    normalize_quantity,
)


GeneratedUnit = Literal["mg", "g", "kg", "ml", "l", "茶匙", "汤匙", "个", "条"]


# 类说明（数据契约类）：GeneratedIngredient
# 作用：描述生成菜谱的食材条目的结构、类型及可校验字段。
class GeneratedIngredient(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：NonBlankText。
    name: NonBlankText
    # 字段说明：quantity
    # 作用：当前业务对象的计数或要求的数量。
    # 类型：Decimal。
    # 配置：下限（不含）=0。
    quantity: Decimal = Field(gt=0)
    # 字段说明：unit
    # 作用：食材用量单位。
    # 类型：GeneratedUnit。
    # 取值说明：
    #   mg：毫克。
    #   g：克。
    #   kg：千克。
    #   ml：毫升。
    #   l：升。
    #   茶匙：以茶匙计量。
    #   汤匙：以汤匙计量。
    #   个：以个计数。
    #   条：以条计数。
    unit: GeneratedUnit
    # 字段说明：preparation
    # 作用：制作前的准备要求或预处理步骤。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=255。
    preparation: str | None = Field(default=None, max_length=255)
    # 字段说明：category
    # 作用：目标食材或菜品分类。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=100。
    category: str | None = Field(default=None, max_length=100)

    # 方法说明：validate_quantity_unit
    # 作用：校验食材用量与单位的组合。
    # 入参：
    #   无显式入参。
    # 出参：'GeneratedIngredient'；生成菜谱的食材条目。
    @model_validator(mode="after")
    def validate_quantity_unit(self) -> "GeneratedIngredient":
        normalize_quantity(self.quantity, self.unit)
        return self


# 类说明（数据契约类）：GeneratedCookingStep
# 作用：描述生成菜谱的烹饪步骤的结构、类型及可校验字段。
class GeneratedCookingStep(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：number
    # 作用：当前制作步骤的顺序号，从 1 开始。
    # 类型：int。
    # 配置：最小值（含）=1。
    number: int = Field(ge=1)
    # 字段说明：action
    # 作用：本次行为或控制流程要执行的动作。
    # 类型：NonBlankText。
    action: NonBlankText
    # 字段说明：instruction
    # 作用：传递给执行器或模型的具体任务指令。
    # 类型：NonBlankText。
    instruction: NonBlankText
    # 字段说明：duration_minutes
    # 作用：制作或执行所需时间，单位为分钟。
    # 类型：int。
    # 配置：默认值=0；最小值（含）=0；最大值（含）=24 * 60。
    duration_minutes: int = Field(default=0, ge=0, le=24 * 60)
    # 字段说明：temperature
    # 作用：模型采样温度。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=100。
    temperature: str | None = Field(default=None, max_length=100)
    # 字段说明：tips
    # 作用：制作建议或使用注意事项。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=1000。
    tips: str | None = Field(default=None, max_length=1000)


# 类说明（数据契约类）：GeneratedRecipe
# 作用：描述模型生成菜谱的结构、类型及可校验字段。
class GeneratedRecipe(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：NonBlankText。
    name: NonBlankText
    # 字段说明：description
    # 作用：当前对象的说明文本。
    # 类型：str。
    # 配置：最小长度=1；最大长度=2000。
    description: str = Field(min_length=1, max_length=2000)
    # 字段说明：total_time_minutes
    # 作用：制作或执行所需时间，单位为分钟。
    # 类型：int。
    # 配置：最小值（含）=1；最大值（含）=24 * 60。
    total_time_minutes: int = Field(ge=1, le=24 * 60)
    # 字段说明：servings
    # 作用：菜谱或菜单计划的用餐人数。
    # 类型：int。
    # 配置：最小值（含）=1；最大值（含）=100。
    servings: int = Field(ge=1, le=100)
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
    # 配置：默认值=None；最大长度=255。
    cuisine: str | None = Field(default=None, max_length=255)
    # 字段说明：taste
    # 作用：明确的口味标注；未知时不填。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=100。
    taste: str | None = Field(
        default=None, max_length=100, description="明确的口味标注；未知时不填。"
    )
    # 字段说明：equipment
    # 作用：完成全部步骤需要的设备；未知时不填。
    # 类型：tuple[str, ...] | None。
    # 配置：默认值=None；最大长度=20。
    equipment: tuple[str, ...] | None = Field(
        default=None, max_length=20, description="完成全部步骤需要的设备；未知时不填。"
    )
    # 字段说明：ingredients
    # 作用：菜谱使用的完整食材集合。
    # 类型：tuple[GeneratedIngredient, ...]。
    # 配置：最小长度=1；最大长度=100。
    ingredients: tuple[GeneratedIngredient, ...] = Field(min_length=1, max_length=100)
    # 字段说明：steps
    # 作用：菜谱制作步骤，按执行顺序排列。
    # 类型：tuple[GeneratedCookingStep, ...]。
    # 配置：最小长度=1；最大长度=100。
    steps: tuple[GeneratedCookingStep, ...] = Field(min_length=1, max_length=100)
    # 字段说明：nutrition
    # 作用：菜谱或食材的结构化营养信息。
    # 类型：NutritionInfo。
    nutrition: NutritionInfo
    # 字段说明：allergens
    # 作用：用户过敏项，作为食材安全审查的硬性排除条件。
    # 类型：tuple[str, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=50。
    allergens: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    # 字段说明：dietary_types
    # 作用：本轮要求满足的饮食类型集合。
    # 类型：tuple[DietaryType, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=3。
    # 补充取值说明（类型别名或枚举）：
    #   vegetarian：素食类型或素菜分类。
    #   vegan：纯素饮食类型。
    #   pescatarian：鱼素饮食类型。
    dietary_types: tuple[DietaryType, ...] = Field(default_factory=tuple, max_length=3)

    # 方法说明：validate_recipe_shape
    # 作用：校验生成菜谱结构满足最低完整性要求。
    # 入参：
    #   无显式入参。
    # 出参：'GeneratedRecipe'；模型生成菜谱。
    @model_validator(mode="after")
    def validate_recipe_shape(self) -> "GeneratedRecipe":
        names = [item.name.casefold() for item in self.ingredients]
        if len(names) != len(set(names)):
            raise ValueError("generated recipe contains duplicate ingredients")
        numbers = [step.number for step in self.steps]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("generated recipe steps must be contiguous from 1")
        return self


__all__ = [
    "GeneratedCookingStep",
    "GeneratedIngredient",
    "GeneratedRecipe",
    "GeneratedUnit",
]
