"""租户内食谱热度快照与有界榜单。"""

from datetime import date
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

RankingMode = Literal["today", "popular"]


# 类说明（数据契约类）：RankedRecipe
# 作用：描述SQL 聚合得到的排名食谱的结构、类型及可校验字段。
class RankedRecipe(BaseModel):
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
    # 字段说明：score
    # 作用：检索、排序或评估产生的分值，数值含义由具体算法定义。
    # 类型：int。
    # 配置：下限（不含）=0；最大值（含）=9007199254740991。
    score: int = Field(gt=0, le=9007199254740991)


# 类说明（数据契约类）：RankingSnapshot
# 作用：描述完整榜单快照的结构、类型及可校验字段。
class RankingSnapshot(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：mode
    # 作用：当前榜单或运行模式。
    # 类型：RankingMode。
    # 取值说明：
    #   today：今日热门排行。
    #   popular：当前受欢迎排行。
    mode: RankingMode
    # 字段说明：day
    # 作用：今日榜单对应的日期。
    # 类型：date | None。
    day: date | None
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：AwareDatetime。
    updated_at: AwareDatetime
    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[RankedRecipe, ...]。
    items: tuple[RankedRecipe, ...]
    # 字段说明：truncated
    # 作用：内容是否因长度或预算限制被裁剪。
    # 类型：bool。
    truncated: bool


# 类说明（业务或基础设施实现类）：RankingItem
# 作用：实现榜单食谱条目，封装该组件的业务处理与依赖协作。
class RankingItem(RankedRecipe):
    # 字段说明：rank
    # 作用：条目在榜单中的名次。
    # 类型：int。
    # 配置：下限（不含）=0。
    rank: int = Field(gt=0)


# 类说明（数据契约类）：RankingPage
# 作用：描述榜单分页响应的结构、类型及可校验字段。
class RankingPage(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True。
    model_config = ConfigDict(frozen=True)
    # 字段说明：mode
    # 作用：当前榜单或运行模式。
    # 类型：RankingMode。
    # 取值说明：
    #   today：今日热门排行。
    #   popular：当前受欢迎排行。
    mode: RankingMode
    # 字段说明：day
    # 作用：今日榜单对应的日期。
    # 类型：date | None。
    day: date | None
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：AwareDatetime。
    updated_at: AwareDatetime
    # 字段说明：source
    # 作用：当前榜单页面的数据来源，区分 Redis 快照与数据库降级结果。
    # 类型：Literal['redis', 'database']。
    # 取值说明：
    #   redis：使用 Redis 实现。
    #   database：使用数据库数据。
    source: Literal["redis", "database"]
    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[RankingItem, ...]。
    items: tuple[RankingItem, ...]
    # 字段说明：ranked_count
    # 作用：已纳入排行或排序结果的条目数量。
    # 类型：int。
    ranked_count: int
    # 字段说明：has_more
    # 作用：当前页之后是否仍有可查询记录。
    # 类型：bool。
    has_more: bool
    # 字段说明：truncated
    # 作用：内容是否因长度或预算限制被裁剪。
    # 类型：bool。
    truncated: bool
