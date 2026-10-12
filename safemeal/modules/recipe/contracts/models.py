"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=Decimal("0"))]


# 类说明（枚举类）：RecipeDifficulty
# 作用：限定食谱难度枚举的允许取值，统一业务分支判定。
class RecipeDifficulty(str, Enum):
    # 字段说明：EASY
    # 作用：容易制作的难度等级。
    # 初始值：'easy'。
    # 取值说明：
    #   easy：容易制作。
    EASY = "easy"
    # 字段说明：MEDIUM
    # 作用：中等制作难度等级。
    # 初始值：'medium'。
    # 取值说明：
    #   medium：中等制作难度。
    MEDIUM = "medium"
    # 字段说明：HARD
    # 作用：较高制作难度等级。
    # 初始值：'hard'。
    # 取值说明：
    #   hard：制作难度较高。
    HARD = "hard"


# 类说明（枚举类）：DietaryType
# 作用：限定饮食类型枚举的允许取值，统一业务分支判定。
class DietaryType(str, Enum):
    # 字段说明：VEGETARIAN
    # 作用：素食类型或素菜分类。
    # 初始值：'vegetarian'。
    # 取值说明：
    #   vegetarian：素食类型或素菜分类。
    VEGETARIAN = "vegetarian"
    # 字段说明：VEGAN
    # 作用：纯素饮食类型，排除动物来源食物。
    # 初始值：'vegan'。
    # 取值说明：
    #   vegan：纯素饮食类型。
    VEGAN = "vegan"
    # 字段说明：PESCATARIAN
    # 作用：鱼素饮食类型，可食鱼类但排除其他肉类。
    # 初始值：'pescatarian'。
    # 取值说明：
    #   pescatarian：鱼素饮食类型。
    PESCATARIAN = "pescatarian"


# 类说明（枚举类）：UnitDimension
# 作用：限定食材用量单位维度枚举的允许取值，统一业务分支判定。
class UnitDimension(str, Enum):
    # 字段说明：MASS
    # 作用：按质量计量的单位维度。
    # 初始值：'mass'。
    # 取值说明：
    #   mass：按质量计量。
    MASS = "mass"
    # 字段说明：VOLUME
    # 作用：按体积计量的单位维度。
    # 初始值：'volume'。
    # 取值说明：
    #   volume：按体积计量。
    VOLUME = "volume"
    # 字段说明：COUNT
    # 作用：按数量计量的单位维度。
    # 初始值：'count'。
    # 取值说明：
    #   count：按个数计量。
    COUNT = "count"


# 类说明（数据契约类）：NormalizedQuantity
# 作用：描述规范化食材用量的结构、类型及可校验字段。
class NormalizedQuantity(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：value
    # 作用：经过单位归一化的食材用量数值。
    # 类型：Decimal。
    # 配置：下限（不含）=0。
    value: Decimal = Field(gt=0)
    # 字段说明：unit
    # 作用：食材用量单位。
    # 类型：str。
    unit: str
    # 字段说明：dimension
    # 作用：嵌入向量的维度。
    # 类型：UnitDimension。
    # 补充取值说明（类型别名或枚举）：
    #   mass：按质量计量。
    #   volume：按体积计量。
    #   count：按个数计量。
    dimension: UnitDimension


_UNIT_ALIASES = {
    "克": "g",
    "公克": "g",
    "千克": "kg",
    "公斤": "kg",
    "毫升": "ml",
    "升": "l",
    "大匙": "汤匙",
    "tbsp": "汤匙",
    "茶匙": "茶匙",
    "tsp": "茶匙",
}
_UNIT_DEFINITIONS: dict[str, tuple[UnitDimension, Decimal, str]] = {
    "mg": (UnitDimension.MASS, Decimal("0.001"), "g"),
    "g": (UnitDimension.MASS, Decimal("1"), "g"),
    "kg": (UnitDimension.MASS, Decimal("1000"), "g"),
    "ml": (UnitDimension.VOLUME, Decimal("1"), "ml"),
    "l": (UnitDimension.VOLUME, Decimal("1000"), "ml"),
    "茶匙": (UnitDimension.VOLUME, Decimal("5"), "ml"),
    "汤匙": (UnitDimension.VOLUME, Decimal("15"), "ml"),
    "个": (UnitDimension.COUNT, Decimal("1"), "个"),
    "条": (UnitDimension.COUNT, Decimal("1"), "条"),
}


# 方法说明：normalize_quantity
# 作用：将原始食材用量转换为可比较的规范数量。
# 入参：
#   value（Decimal | str | int）：当前待转换或校验的值。
#   unit（str）：食材用量单位。
# 出参：NormalizedQuantity；规范化食材用量。
def normalize_quantity(value: Decimal | str | int, unit: str) -> NormalizedQuantity:

    try:
        quantity = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("ingredient quantity must be numeric") from exc
    normalized_unit = _UNIT_ALIASES.get(
        unit.strip().casefold(), unit.strip().casefold()
    )
    definition = _UNIT_DEFINITIONS.get(normalized_unit)
    if definition is None:
        raise ValueError(f"unsupported ingredient unit: {unit}")
    dimension, factor, canonical_unit = definition
    return NormalizedQuantity(
        value=quantity * factor,
        unit=canonical_unit,
        dimension=dimension,
    )


# 类说明（数据契约类）：NutritionInfo
# 作用：描述菜谱营养信息的结构、类型及可校验字段。
class NutritionInfo(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：calories
    # 作用：热量值，单位为千卡，具体基准由营养数据的 basis 指定。
    # 类型：NonNegativeDecimal。
    calories: NonNegativeDecimal = Decimal("0")
    # 字段说明：protein_g
    # 作用：蛋白质含量，单位为克。
    # 类型：NonNegativeDecimal。
    protein_g: NonNegativeDecimal = Decimal("0")
    # 字段说明：carbs_g
    # 作用：碳水化合物含量，单位为克。
    # 类型：NonNegativeDecimal。
    carbs_g: NonNegativeDecimal = Decimal("0")
    # 字段说明：fat_g
    # 作用：脂肪含量，单位为克。
    # 类型：NonNegativeDecimal。
    fat_g: NonNegativeDecimal = Decimal("0")
    # 字段说明：basis
    # 作用：营养数据的计量基准，用于区分每百克与整道菜的数值。
    # 类型：Literal['per_recipe', 'per_100g']。
    # 初始值：'per_recipe'。
    # 取值说明：
    #   per_recipe：整道菜的营养计量基准。
    #   per_100g：每 100 克的营养计量基准。
    basis: Literal["per_recipe", "per_100g"] = "per_recipe"

    # 方法说明：validate_plausible_boundaries
    # 作用：校验时间、热量等食谱字段的合理边界。
    # 入参：
    #   无显式入参。
    # 出参：'NutritionInfo'；菜谱营养信息。
    @model_validator(mode="after")
    def validate_plausible_boundaries(self) -> "NutritionInfo":
        if self.calories > Decimal("100000"):
            raise ValueError("calories exceed the supported recipe boundary")
        if any(
            value > Decimal("10000")
            for value in (self.protein_g, self.carbs_g, self.fat_g)
        ):
            raise ValueError("macronutrients exceed the supported recipe boundary")
        return self


# 类说明（数据契约类）：Ingredient
# 作用：描述菜谱食材条目的结构、类型及可校验字段。
class Ingredient(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：int。
    # 配置：下限（不含）=0。
    id: int = Field(gt=0)
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：NonBlankText。
    name: NonBlankText
    # 字段说明：category
    # 作用：目标食材或菜品分类。
    # 类型：str | None。
    # 初始值：None。
    category: str | None = None
    # 字段说明：nutrition
    # 作用：菜谱或食材的结构化营养信息。
    # 类型：NutritionInfo。
    nutrition: NutritionInfo


# 类说明（数据契约类）：IngredientQuantity
# 作用：描述食材原始用量的结构、类型及可校验字段。
class IngredientQuantity(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：ingredient
    # 作用：当前食材条目。
    # 类型：Ingredient。
    ingredient: Ingredient
    # 字段说明：quantity
    # 作用：当前业务对象的计数或要求的数量。
    # 类型：Decimal。
    # 配置：下限（不含）=0。
    quantity: Decimal = Field(gt=0)
    # 字段说明：unit
    # 作用：食材用量单位。
    # 类型：NonBlankText。
    unit: NonBlankText
    # 字段说明：normalized
    # 作用：已经完成清洗或标准化的数据。
    # 类型：NormalizedQuantity。
    normalized: NormalizedQuantity
    # 字段说明：preparation
    # 作用：制作前的准备要求或预处理步骤。
    # 类型：str | None。
    # 初始值：None。
    preparation: str | None = None
    # 字段说明：is_main
    # 作用：食材是否属于菜谱主料。
    # 类型：bool。
    # 初始值：False。
    is_main: bool = False
    # 字段说明：ingredient_type
    # 作用：食材在菜谱中的角色或食材自身类别。
    # 类型：Literal['main', 'auxiliary', 'seasoning']。
    # 取值说明：
    #   main：主料。
    #   auxiliary：辅料。
    #   seasoning：调味料。
    ingredient_type: Literal["main", "auxiliary", "seasoning"]

    # 方法说明：populate_normalized_quantity
    # 作用：在模型校验中补充食材用量的标准化字段。
    # 入参：
    #   data（object）：当前操作的结构化数据载荷。
    # 出参：object；由调用约定决定的数据对象。
    @model_validator(mode="before")
    @classmethod
    def populate_normalized_quantity(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("normalized") is None:
            data = dict(data)
            data["normalized"] = normalize_quantity(data["quantity"], str(data["unit"]))
        return data


# 类说明（数据契约类）：CookingStep
# 作用：描述烹饪步骤的结构、类型及可校验字段。
class CookingStep(BaseModel):
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
    # 初始值：None。
    temperature: str | None = None
    # 字段说明：tips
    # 作用：制作建议或使用注意事项。
    # 类型：str | None。
    # 初始值：None。
    tips: str | None = None


# 类说明（数据契约类）：Recipe
# 作用：描述完整食谱业务模型的结构、类型及可校验字段。
class Recipe(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：int。
    # 配置：下限（不含）=0。
    id: int = Field(gt=0)
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：NonBlankText。
    name: NonBlankText
    # 字段说明：description
    # 作用：当前对象的说明文本。
    # 类型：str | None。
    # 初始值：None。
    description: str | None = None
    # 字段说明：total_time_minutes
    # 作用：制作或执行所需时间，单位为分钟。
    # 类型：int。
    # 配置：最小值（含）=0；最大值（含）=7 * 24 * 60。
    total_time_minutes: int = Field(ge=0, le=7 * 24 * 60)
    # 字段说明：servings
    # 作用：菜谱或菜单计划的用餐人数。
    # 类型：int。
    # 配置：下限（不含）=0；最大值（含）=1000。
    servings: int = Field(gt=0, le=1000)
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
    # 初始值：None。
    cuisine: str | None = None
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
    # 类型：tuple[IngredientQuantity, ...]。
    # 配置：最小长度=1。
    ingredients: tuple[IngredientQuantity, ...] = Field(min_length=1)
    # 字段说明：steps
    # 作用：菜谱制作步骤，按执行顺序排列。
    # 类型：tuple[CookingStep, ...]。
    # 配置：最小长度=1。
    steps: tuple[CookingStep, ...] = Field(min_length=1)
    # 字段说明：nutrition
    # 作用：菜谱或食材的结构化营养信息。
    # 类型：NutritionInfo。
    nutrition: NutritionInfo

    # 方法说明：validate_aggregate_invariants
    # 作用：校验生成菜谱各聚合字段之间的业务约束。
    # 入参：
    #   无显式入参。
    # 出参：'Recipe'；完整食谱业务模型。
    @model_validator(mode="after")
    def validate_aggregate_invariants(self) -> "Recipe":
        ingredient_ids = [item.ingredient.id for item in self.ingredients]
        if len(ingredient_ids) != len(set(ingredient_ids)):
            raise ValueError("recipe contains duplicate ingredients")
        step_numbers = [step.number for step in self.steps]
        if step_numbers != list(range(1, len(step_numbers) + 1)):
            raise ValueError("recipe steps must be ordered and contiguous from 1")
        return self


__all__ = [
    "CookingStep",
    "DietaryType",
    "Ingredient",
    "IngredientQuantity",
    "NormalizedQuantity",
    "NutritionInfo",
    "Recipe",
    "RecipeDifficulty",
    "UnitDimension",
    "normalize_quantity",
]
