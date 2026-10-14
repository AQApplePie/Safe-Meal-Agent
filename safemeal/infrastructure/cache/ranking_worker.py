"""生命周期内的定时统计任务；失败下一周期重试，不占 HTTP 写入链路。"""

import asyncio
from loguru import logger
from safemeal.modules.interaction.application.ranking_service import RankingService


# 类说明（业务或基础设施实现类）：RankingWorker
# 作用：实现周期性榜单恢复工作者，封装该组件的业务处理与依赖协作。
class RankingWorker:
    # 方法说明：__init__
    # 作用：初始化周期性榜单恢复工作者，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   service（RankingService）：热门榜单读取与重建服务。
    #   interval_seconds（float）：后台处理周期，单位秒。
    #   batch_size（int）：单批次处理的最大记录数。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self, service: RankingService, interval_seconds: float, batch_size: int
    ) -> None:
        # 实例属性说明：_service
        # 作用：当前路由注入的业务服务。
        self._service = service
        # 实例属性说明：_interval
        # 作用：后台处理周期，单位秒。
        self._interval = interval_seconds
        # 实例属性说明：_batch_size
        # 作用：单批次处理的最大记录数。
        self._batch_size = batch_size
        # 实例属性说明：_stop
        # 作用：停止后台循环的同步信号。
        self._stop = asyncio.Event()
        # 实例属性说明：_task
        # 作用：后台协程任务句柄，用于启动、等待和停止。
        # 类型：asyncio.Task[None] | None。
        # 初始值：None。
        self._task: asyncio.Task[None] | None = None

    # 方法说明：start
    # 作用：启动周期性榜单恢复工作者的后台处理循环。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="recipe-ranking-refresh")

    # 方法说明：_run
    # 作用：运行周期性榜单恢复工作者封装的底层执行逻辑。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def _run(self) -> None:
        cursor = None
        while not self._stop.is_set():
            try:
                cursor = await asyncio.to_thread(
                    self._service.refresh_batch, cursor, self._batch_size
                )
            except Exception:
                logger.exception("recipe.ranking.refresh_failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
