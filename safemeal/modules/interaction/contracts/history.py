"""浏览历史的身份独立契约和分页位置。"""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


# 类说明（数据契约类）：HistoryEntry
# 作用：描述浏览历史条目的结构、类型及可校验字段。
class HistoryEntry(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：recipe_id
    # 作用：目标食谱的整数标识。
    # 类型：int。
    # 配置：下限（不含）=0；最大值（含）=2147483647。
    recipe_id: int = Field(gt=0, le=2147483647)
    # 字段说明：recipe_name
    # 作用：目标菜谱名称。
    # 类型：str。
    recipe_name: str
    # 字段说明：last_viewed_at
    # 作用：用户最近一次浏览该菜谱的时间，用于历史去重与排序。
    # 类型：AwareDatetime。
    last_viewed_at: AwareDatetime


# 类说明（数据契约类）：HistoryPosition
# 作用：描述浏览历史分页游标位置的结构、类型及可校验字段。
class HistoryPosition(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：last_viewed_at
    # 作用：用户最近一次浏览该菜谱的时间，用于历史去重与排序。
    # 类型：AwareDatetime。
    last_viewed_at: AwareDatetime
    # 字段说明：recipe_id
    # 作用：目标食谱的整数标识。
    # 类型：int。
    # 配置：下限（不含）=0；最大值（含）=2147483647。
    recipe_id: int = Field(gt=0, le=2147483647)


# 类说明（数据契约类）：HistoryPage
# 作用：描述浏览历史游标分页结果的结构、类型及可校验字段。
class HistoryPage(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[HistoryEntry, ...]。
    items: tuple[HistoryEntry, ...]
    # 字段说明：has_more
    # 作用：当前页之后是否仍有可查询记录。
    # 类型：bool。
    has_more: bool
    # 字段说明：next_cursor
    # 作用：下一页查询的游标，编码稳定排序位置。
    # 类型：str | None。
    next_cursor: str | None
