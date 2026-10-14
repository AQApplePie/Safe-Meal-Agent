"""可重建统计事实和可丢弃榜单存储端口。"""

from datetime import date, datetime
from typing import Protocol
from safemeal.modules.interaction.contracts.ranking import (
    RankedRecipe,
    RankingMode,
    RankingPage,
    RankingSnapshot,
)


# 类说明（接口类）：RankingRepository
# 作用：定义榜单 SQL 事实聚合接口的能力契约，供应用层与具体实现解耦。
class RankingRepository(Protocol):
    # 方法说明：tenants
    # 作用：按游标分页读取存在行为事实的租户。
    # 入参：
    #   after（str | None）：分页游标或查询下界。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：tuple[str, ...]；按游标排序取得的租户标识元组。
    def tenants(self, after: str | None, limit: int) -> tuple[str, ...]: ...
    # 方法说明：aggregate
    # 作用：按租户与榜单模式聚合行为事实，返回按分数排序的菜谱。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   mode（RankingMode）：当前榜单或运行模式。
    #   start（datetime）：查询时间窗口的起始时刻。
    #   end（datetime）：时间查询窗口的结束时刻。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：tuple[RankedRecipe, ...]；SQL 聚合得到的排名食谱组成的元组。
    def aggregate(
        self,
        tenant_id: str,
        mode: RankingMode,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> tuple[RankedRecipe, ...]: ...


# 类说明（接口类）：RankingStore
# 作用：定义榜单快照缓存接口的能力契约，供应用层与具体实现解耦。
class RankingStore(Protocol):
    # 方法说明：read
    # 作用：通过榜单快照缓存接口读取目标记录或当前状态。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   mode（RankingMode）：当前榜单或运行模式。
    #   day（date | None）：今日榜单对应的日期。
    #   offset（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：RankingPage | None；榜单分页响应或None（未取得结果）。
    def read(
        self,
        tenant_id: str,
        mode: RankingMode,
        day: date | None,
        offset: int,
        limit: int,
    ) -> RankingPage | None: ...
    # 方法说明：acquire
    # 作用：尝试取得受限资源的使用权，并返回本次取得结果。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：str | None；文本字符串或None（未取得结果）。
    def acquire(self, tenant_id: str) -> str | None: ...
    # 方法说明：publish
    # 作用：在租约有效时发布完整榜单快照，原子切换可见数据。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   token（str）：令牌或本次租约的处理凭证。
    #   snapshot（RankingSnapshot）：完整榜单快照。
    # 出参：bool；当前有效租约下是否成功发布完整榜单。
    def publish(
        self, tenant_id: str, token: str, snapshot: RankingSnapshot
    ) -> bool: ...
    # 方法说明：release
    # 作用：仅在令牌匹配时释放榜单刷新租约。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   token（str）：令牌或本次租约的处理凭证。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def release(self, tenant_id: str, token: str) -> None: ...
