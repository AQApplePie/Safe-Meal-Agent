"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from safemeal.shared.contracts.request_frame import MenuCategory


# 类说明（数据契约类）：RecipeCandidate
# 作用：描述推荐候选食谱的结构、类型及可校验字段。
class RecipeCandidate(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：ingredients
    # 作用：菜谱使用的完整食材集合。
    # 类型：tuple[dict[str, str], ...]。
    # 初始值：()。
    ingredients: tuple[dict[str, str], ...] = ()
    # 字段说明：steps
    # 作用：菜谱制作步骤，按执行顺序排列。
    # 类型：str。
    # 初始值：''。
    steps: str = ""
    # 字段说明：nutrition
    # 作用：菜谱或食材的结构化营养信息。
    # 类型：dict[str, str | float | int] | None。
    # 初始值：None。
    nutrition: dict[str, str | float | int] | None = None
    # 字段说明：total_time_minutes
    # 作用：制作或执行所需时间，单位为分钟。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=0。
    total_time_minutes: int | None = Field(default=None, ge=0)
    # 字段说明：servings
    # 作用：菜谱或菜单计划的用餐人数。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1。
    servings: int | None = Field(default=None, ge=1)
    # 字段说明：source_type
    # 作用：来源类别，区分本地、数据库与外部检索结果。
    # 类型：Literal['canonical_database', 'local_json', 'session', 'wikibooks', 'wikipedia']。
    # 取值说明：
    #   canonical_database：使用规范化后的数据库数据。
    #   local_json：使用本地 JSON 数据。
    #   session：会话级作用范围。
    #   wikibooks：来源为维基教科书。
    #   wikipedia：来源为维基百科。
    source_type: Literal[
        "canonical_database", "local_json", "session", "wikibooks", "wikipedia"
    ]
    # 字段说明：source_url
    # 作用：证据来源的可访问地址。
    # 类型：str | None。
    # 初始值：None。
    source_url: str | None = None
    # 字段说明：source_title
    # 作用：来源文档或页面标题。
    # 类型：str。
    source_title: str
    # 字段说明：confidence
    # 作用：该菜谱候选的检索或识别置信度，范围为 0 至 1。
    # 类型：float。
    # 配置：最小值（含）=0；最大值（含）=1。
    confidence: float = Field(ge=0, le=1)
    # 字段说明：persistent
    # 作用：该事实或数据是否需要跨轮持久化。
    # 类型：bool。
    # 初始值：False。
    persistent: bool = False
    # 字段说明：ingredients_complete
    # 作用：食材清单是否完整，缺失时不能给出确定的安全结论。
    # 类型：bool。
    # 初始值：False。
    ingredients_complete: bool = False

    # 方法说明：source
    # 作用：取得菜谱查找结果对应的来源名称。
    # 入参：
    #   无显式入参。
    # 出参：str；当前菜谱查找结果的来源名称。
    @property
    def source(self) -> str:
        return self.source_url or f"{self.source_type}:{self.source_title}"


# 类说明（数据契约类）：RecipeLookupResult
# 作用：描述外部或本地菜谱查找结果的结构、类型及可校验字段。
class RecipeLookupResult(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['FOUND', 'NOT_FOUND', 'ERROR']。
    # 取值说明：
    #   FOUND：查到目标记录。
    #   NOT_FOUND：未查到目标记录。
    #   ERROR：查询或执行失败。
    status: Literal["FOUND", "NOT_FOUND", "ERROR"]
    # 字段说明：query
    # 作用：结构化查询条件或检索问题。
    # 类型：str。
    query: str
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
    # 字段说明：provider
    # 作用：当前选中的外部模型供应商。
    # 类型：str。
    provider: str
    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[RecipeCandidate, ...]。
    # 初始值：()。
    items: tuple[RecipeCandidate, ...] = ()
    # 字段说明：error
    # 作用：当前操作的错误信息。
    # 类型：str | None。
    # 初始值：None。
    error: str | None = None


RecipeEvidence = RecipeCandidate


# 类说明（数据契约类）：MenuRecipeCandidate
# 作用：描述轻量菜单候选菜品的结构、类型及可校验字段。
class MenuRecipeCandidate(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：int | None。
    # 初始值：None。
    id: int | None = None
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：categories
    # 作用：当前对象所属的分类集合。
    # 类型：tuple[MenuCategory, ...]。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    categories: tuple[MenuCategory, ...]
    # 字段说明：main_ingredients
    # 作用：菜谱主料集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    main_ingredients: tuple[str, ...] = ()

    # 字段说明：ingredients
    # 作用：菜谱使用的完整食材集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    ingredients: tuple[str, ...] = ()
    # 字段说明：ingredients_complete
    # 作用：食材清单是否完整，缺失时不能给出确定的安全结论。
    # 类型：bool。
    # 初始值：True。
    ingredients_complete: bool = True
    # 字段说明：source_type
    # 作用：来源类别，区分本地、数据库与外部检索结果。
    # 类型：Literal['canonical_database', 'local_json', 'wikibooks']。
    # 取值说明：
    #   canonical_database：使用规范化后的数据库数据。
    #   local_json：使用本地 JSON 数据。
    #   wikibooks：来源为维基教科书。
    source_type: Literal["canonical_database", "local_json", "wikibooks"]
    # 字段说明：source_title
    # 作用：来源文档或页面标题。
    # 类型：str。
    source_title: str
    # 字段说明：safety_status
    # 作用：菜谱安全评估状态，未知状态不等同于安全。
    # 类型：Literal['eligible', 'unknown']。
    # 初始值：'eligible'。
    # 取值说明：
    #   eligible：符合参与或执行条件。
    #   unknown：证据不足，无法作出确定结论。
    safety_status: Literal["eligible", "unknown"] = "eligible"
