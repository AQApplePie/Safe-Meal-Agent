"""定义跨层传递的稳定数据契约。"""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from safemeal.shared.types import JsonObject
from safemeal.modules.dietary.contracts.constraints import RecipeSafetyRecord
from safemeal.modules.dietary.contracts.control_plane import (
    ConstraintDecision,
)
from safemeal.shared.contracts.semantic import ConstraintStatement


# 类说明（数据契约类）：DietarySafeRecipeQueryArgs
# 作用：饮食忌口/过敏安全查询参数。
class DietarySafeRecipeQueryArgs(BaseModel):
    """饮食忌口/过敏安全查询参数。"""

    # 字段说明：excluded_ingredients
    # 作用：需要硬排除的忌口/过敏食材，例如 ['鸡蛋', '扇贝']。
    # 类型：list[str]。
    # 配置：最小长度=1。
    excluded_ingredients: list[str] = Field(
        min_length=1,
        description="需要硬排除的忌口/过敏食材，例如 ['鸡蛋', '扇贝']。",
    )
    # 字段说明：target_dish
    # 作用：需要判断是否适合的指定菜名；为空时返回安全推荐和排除样例。
    # 类型：Optional[str]。
    # 配置：默认值=None。
    target_dish: Optional[str] = Field(
        default=None,
        description="需要判断是否适合的指定菜名；为空时返回安全推荐和排除样例。",
    )
    # 字段说明：recommend_limit
    # 作用：需要返回的安全推荐数量。
    # 类型：int。
    # 配置：默认值=2；最小值（含）=0；最大值（含）=10。
    recommend_limit: int = Field(
        default=2,
        ge=0,
        le=10,
        description="需要返回的安全推荐数量。",
    )
    # 字段说明：excluded_limit
    # 作用：需要返回的命中禁忌食材菜品数量。
    # 类型：int。
    # 配置：默认值=5；最小值（含）=0；最大值（含）=20。
    excluded_limit: int = Field(
        default=5,
        ge=0,
        le=20,
        description="需要返回的命中禁忌食材菜品数量。",
    )


# 类说明（数据契约类）：KnowledgeSearchResult
# 作用：描述知识检索工具结果的结构、类型及可校验字段。
class KnowledgeSearchResult(BaseModel):
    # 字段说明：query
    # 作用：结构化查询条件或检索问题。
    # 类型：str。
    query: str
    # 字段说明：documents
    # 作用：待处理的文档或文档片段集合。
    # 类型：list[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    documents: list[JsonObject] = Field(default_factory=list)
    # 字段说明：count
    # 作用：本次知识检索返回的结果条目数量。
    # 类型：int。
    count: int


# 类说明（数据契约类）：KnowledgeSearchArgs
# 作用：描述知识检索工具参数的结构、类型及可校验字段。
class KnowledgeSearchArgs(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")

    # 字段说明：query
    # 作用：结构化查询条件或检索问题。
    # 类型：str。
    query: str
    # 字段说明：top_k
    # 作用：检索返回的最大候选数。
    # 类型：int。
    # 配置：默认值=5；最小值（含）=1；最大值（含）=20。
    top_k: int = Field(default=5, ge=1, le=20)
    # 字段说明：filter_expr
    # 作用：当前检索使用的过滤条件或表达式。
    # 类型：Optional[str]。
    # 初始值：None。
    filter_expr: Optional[str] = None


# 类说明（数据契约类）：DietarySafeRecipeQueryResult
# 作用：忌口/过敏专用查询工具返回值。
class DietarySafeRecipeQueryResult(BaseModel):
    """忌口/过敏专用查询工具返回值。"""

    # 字段说明：database
    # 作用：数据库名称或数据库配置。
    # 类型：str。
    # 初始值：'neo4j'。
    database: str = "neo4j"
    # 字段说明：query_type
    # 作用：检索请求的业务类别。
    # 类型：str。
    # 初始值：'dietary_safe_recipe_query'。
    query_type: str = "dietary_safe_recipe_query"
    # 字段说明：target_dish
    # 作用：本轮要查询、替换或审核的目标菜品。
    # 类型：Optional[str]。
    # 初始值：None。
    target_dish: Optional[str] = None
    # 字段说明：excluded_ingredients
    # 作用：必须排除的食材集合。
    # 类型：list[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    excluded_ingredients: list[str] = Field(default_factory=list)
    # 字段说明：expanded_excluded_ingredients
    # 作用：经过别名或类别展开后的禁用食材词项。
    # 类型：list[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    expanded_excluded_ingredients: list[str] = Field(default_factory=list)
    # 字段说明：safe_recipes
    # 作用：审核后具有足够证据满足安全条件的菜谱。
    # 类型：list[RecipeSafetyRecord]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    safe_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    # 字段说明：excluded_recipes
    # 作用：因约束不满足被移出结果的菜谱及相关记录。
    # 类型：list[RecipeSafetyRecord]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    excluded_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    # 字段说明：unknown_recipes
    # 作用：食材或证据不完整、无法确定安全性的菜谱。
    # 类型：list[RecipeSafetyRecord]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    unknown_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    # 字段说明：missing_information
    # 作用：当前任务尚缺少的信息集合。
    # 类型：list[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    missing_information: list[str] = Field(default_factory=list)


# 类说明（数据契约类）：GetRecipeArgs
# 作用：描述菜谱详情工具参数的结构、类型及可校验字段。
class GetRecipeArgs(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")

    # 字段说明：recipe_id
    # 作用：目标食谱的整数标识。
    # 类型：int。
    # 配置：下限（不含）=0。
    recipe_id: int = Field(gt=0)


# 类说明（数据契约类）：VerifyRecipeConstraintsArgs
# 作用：描述食谱约束复核工具参数的结构、类型及可校验字段。
class VerifyRecipeConstraintsArgs(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：recipe_ids
    # 作用：待查询或校验的食谱标识集合。
    # 类型：list[int]。
    # 配置：最小长度=1；最大长度=20。
    recipe_ids: list[int] = Field(min_length=1, max_length=20)
    # 字段说明：constraints
    # 作用：待合并或待执行的约束集合。
    # 类型：list[ConstraintStatement]。
    # 配置：最小长度=1；最大长度=20。
    constraints: list[ConstraintStatement] = Field(min_length=1, max_length=20)

    # 方法说明：validate_unique_recipe_ids
    # 作用：校验批量请求中的食谱标识不存在重复。
    # 入参：
    #   无显式入参。
    # 出参：'VerifyRecipeConstraintsArgs'；食谱约束复核工具参数。
    @model_validator(mode="after")
    def validate_unique_recipe_ids(self) -> "VerifyRecipeConstraintsArgs":
        if len(self.recipe_ids) != len(set(self.recipe_ids)):
            raise ValueError("recipe_ids must be unique")
        return self


# 类说明（数据契约类）：RecipeConstraintVerificationResult
# 作用：描述食谱硬约束复核结果的结构、类型及可校验字段。
class RecipeConstraintVerificationResult(BaseModel):
    # 字段说明：verified
    # 作用：该数据是否通过当前组件规定的验证。
    # 类型：bool。
    verified: bool
    # 字段说明：recipe_count
    # 作用：菜谱条目数量。
    # 类型：int。
    recipe_count: int
    # 字段说明：decisions
    # 作用：逐项约束审核的结论集合，保留违规或未知的理由。
    # 类型：list[ConstraintDecision]。
    decisions: list[ConstraintDecision]
