"""以数据库为事实源的可恢复榜单，不累计客户端事件。"""

from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone, tzinfo
from safemeal.modules.interaction.contracts.ranking import (
    RankingMode,
    RankingSnapshot,
    RankingPage,
    RankingItem,
)
from safemeal.modules.interaction.ports.ranking import RankingRepository, RankingStore
from safemeal.shared.exceptions import InputValidationError


# 类说明（业务或基础设施实现类）：RankingService
# 作用：实现热门榜单读取与重建服务，封装该组件的业务处理与依赖协作。
class RankingService:
    # 方法说明：__init__
    # 作用：初始化热门榜单读取与重建服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   repository（RankingRepository）：当前业务依赖的仓储实现。
    #   store（RankingStore | None）：榜单快照缓存存储；默认值为 None。
    #   cap（int）：当前操作允许的数量上限；默认值为 1000。
    #   day_timezone（tzinfo）：榜单日期窗口使用的时区；默认值为 timezone.utc。
    #   clock（Callable[[], datetime] | None）：用于时间比较的可注入时钟函数；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        repository: RankingRepository,
        store: RankingStore | None = None,
        *,
        cap: int = 1000,
        day_timezone: tzinfo = timezone.utc,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= cap <= 10000:
            raise ValueError("Ranking cap must be between 1 and 10000")
        # 实例属性说明：_repository
        # 作用：当前业务依赖的仓储实现。
        self._repository = repository
        # 实例属性说明：_store
        # 作用：榜单快照缓存存储。
        self._store = store
        # 实例属性说明：_cap
        # 作用：当前操作允许的数量上限。
        self._cap = cap
        # 实例属性说明：_timezone
        # 作用：榜单日期窗口使用的时区。
        self._timezone = day_timezone
        # 实例属性说明：_clock
        # 作用：用于时间比较的可注入时钟函数。
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # 方法说明：_snapshot
    # 作用：组装热门榜单读取与重建服务的内部状态快照。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   mode（RankingMode）：当前榜单或运行模式。
    #   now（datetime）：本次时间比较使用的当前时刻。
    # 出参：RankingSnapshot；完整榜单快照。
    def _snapshot(
        self, tenant_id: str, mode: RankingMode, now: datetime
    ) -> RankingSnapshot:
        day = now.astimezone(self._timezone).date()
        start = datetime.combine(day, time.min, self._timezone).astimezone(timezone.utc)
        end = datetime.combine(
            day + timedelta(days=1), time.min, self._timezone
        ).astimezone(timezone.utc)
        rows = self._repository.aggregate(tenant_id, mode, start, end, self._cap + 1)
        return RankingSnapshot(
            mode=mode,
            day=day if mode == "today" else None,
            updated_at=now,
            items=rows[: self._cap],
            truncated=len(rows) > self._cap,
        )

    # 方法说明：read
    # 作用：通过热门榜单读取与重建服务读取目标记录或当前状态。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   mode（RankingMode）：当前榜单或运行模式；默认值为 'today'。
    #   offset（int）：本次分页跳过的记录数量；默认值为 0。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 20。
    # 出参：RankingPage；榜单分页响应。
    def read(
        self,
        tenant_id: str,
        mode: RankingMode = "today",
        offset: int = 0,
        limit: int = 20,
    ) -> RankingPage:
        if (
            mode not in ("today", "popular")
            or not 0 <= offset < self._cap
            or not 1 <= limit <= 50
        ):
            raise InputValidationError("Invalid ranking mode, offset or limit")
        now = self._clock()
        day = now.astimezone(self._timezone).date() if mode == "today" else None
        if self._store is not None:
            cached = self._store.read(tenant_id, mode, day, offset, limit)
            if cached is not None:
                return cached
        snapshot = self._snapshot(tenant_id, mode, now)
        return RankingPage(
            mode=mode,
            day=snapshot.day,
            updated_at=snapshot.updated_at,
            source="database",
            items=tuple(
                RankingItem(**item.model_dump(), rank=offset + i + 1)
                for i, item in enumerate(snapshot.items[offset : offset + limit])
            ),
            ranked_count=len(snapshot.items),
            has_more=offset + limit < len(snapshot.items),
            truncated=snapshot.truncated,
        )

    # 方法说明：refresh_batch
    # 作用：分页刷新一批租户的榜单，供定时恢复任务使用。
    # 入参：
    #   after（str | None）：分页游标或查询下界。
    #   batch_size（int）：单批次处理的最大记录数。
    # 出参：str | None；本批末尾租户游标；没有下一批时为 None。
    def refresh_batch(self, after: str | None, batch_size: int) -> str | None:
        if self._store is None:
            return None
        tenants = self._repository.tenants(after, batch_size)
        for tenant_id in tenants:
            self.refresh_tenant(tenant_id)
        return tenants[-1] if len(tenants) == batch_size else None

    # 方法说明：refresh_tenant
    # 作用：从 SQL 行为事实重建指定租户各模式的榜单快照。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：bool；两个模式的榜单是否刷新成功；失败时为 False，供事件重试。
    def refresh_tenant(self, tenant_id: str) -> bool:
        """Refresh even empty tenants; false means the event must retry."""
        if self._store is None:
            return False
        token = self._store.acquire(tenant_id)
        if token is None:
            return False
        try:
            now = self._clock()
            modes: tuple[RankingMode, ...] = ("today", "popular")
            for mode in modes:
                if not self._store.publish(
                    tenant_id, token, self._snapshot(tenant_id, mode, now)
                ):
                    return False
            return True
        finally:
            self._store.release(tenant_id, token)
