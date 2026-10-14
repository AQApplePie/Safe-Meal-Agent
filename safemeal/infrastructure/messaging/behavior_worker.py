"""Redis Streams delivery backed by a SQL outbox; no request-side network calls."""

import asyncio
from uuid import UUID, uuid4
from typing import Any, cast
from collections.abc import Callable

from loguru import logger
from redis import Redis
from redis.exceptions import ResponseError

from safemeal.infrastructure.persistence.behavior_outbox import SqlBehaviorOutbox
from safemeal.modules.interaction.application.ranking_service import RankingService

STREAM = "safemeal:behavior:v1"
GROUP = "ranking-v1"
DEAD_STREAM = "safemeal:behavior:invalid:v1"


# 类说明（业务或基础设施实现类）：BehaviorWorker
# 作用：实现行为事件投递与消费后台工作者，封装该组件的业务处理与依赖协作。
class BehaviorWorker:
    # 方法说明：__init__
    # 作用：初始化行为事件投递与消费后台工作者，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   outbox（SqlBehaviorOutbox）：同事务行为事件持久化组件。
    #   client（Redis）：底层外部服务客户端。
    #   ranking（RankingService）：热门榜单刷新与查询业务服务。
    #   batch_size（int）：单批次处理的最大记录数；默认值为 100。
    #   interval_seconds（float）：后台处理周期，单位秒；默认值为 1。
    #   max_attempts（int）：完整数据库事务最多尝试次数；默认值为 5。
    #   observer（Callable[[str], None] | None）：请求指标或轨迹观察组件；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        outbox: SqlBehaviorOutbox,
        client: Redis,
        ranking: RankingService,
        *,
        batch_size: int = 100,
        interval_seconds: float = 1,
        max_attempts: int = 5,
        observer: Callable[[str], None] | None = None,
    ) -> None:
        # 实例属性说明：_observer
        # 作用：请求指标或轨迹观察组件。
        self._observer = observer
        self._outbox, self._client, self._ranking = outbox, client, ranking
        self._batch, self._interval, self._max_attempts = (
            batch_size,
            interval_seconds,
            max_attempts,
        )
        # 实例属性说明：_consumer
        # 作用：消息消费者标识。
        self._consumer = str(uuid4())
        # 实例属性说明：_cursor
        # 作用：下一页起始位置的游标。
        # 初始值：'0-0'。
        self._cursor = "0-0"
        # 实例属性说明：_stop
        # 作用：停止后台循环的同步信号。
        self._stop = asyncio.Event()
        # 实例属性说明：_task
        # 作用：后台协程任务句柄，用于启动、等待和停止。
        # 类型：asyncio.Task[None] | None。
        # 初始值：None。
        self._task: asyncio.Task[None] | None = None

    # 方法说明：_observe
    # 作用：向指标收集器登记本次缓存读取或事件处理结果。
    # 入参：
    #   outcome（str）：本次事件或查询处理的结果类别。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def _observe(self, outcome: str) -> None:
        if self._observer is not None:
            try:
                self._observer(outcome)
            except Exception:
                logger.debug("behavior.event.observer_failed")

    # 方法说明：_ensure_group
    # 作用：确保 Redis Stream 消费组已创建，兼容重复初始化。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def _ensure_group(self) -> None:
        try:
            self._client.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    # 方法说明：relay
    # 作用：查询到期 outbox 事件并向 Redis Stream 投递通知。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def relay(self) -> None:
        for event_id in self._outbox.due(self._batch):
            self._client.xadd(STREAM, {"event_id": event_id})
            self._outbox.published(event_id)
            self._observe("published")

    # 方法说明：consume
    # 作用：消费本批行为通知，并通过持久事件状态驱动榜单刷新。
    # 入参：
    #   message_id（str）：聊天消息标识。
    #   fields（dict[str, str]）：待读取或校验字段集合。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def consume(self, message_id: str, fields: dict[str, str]) -> None:
        event_id = fields.get("event_id", "")
        try:
            if str(UUID(event_id)) != event_id or set(fields) != {"event_id"}:
                raise ValueError("Invalid event envelope")
        except (ValueError, TypeError, AttributeError):
            self._observe("invalid")
            # Do not echo untrusted payloads or identity into logs/dead letters.
            self._client.xadd(
                DEAD_STREAM,
                {"message_id": message_id, "reason": "invalid-envelope"},
                maxlen=1000,
                approximate=True,
            )
        else:
            claim = self._outbox.claim(event_id)
            if claim is not None:
                token, tenant_id = claim
                error = None
                try:
                    if not self._ranking.refresh_tenant(tenant_id):
                        error = "ranking-unavailable"
                except Exception:
                    # Avoid retaining exception text containing credentials or identity.
                    error = "ranking-refresh-failed"
                    logger.warning("behavior.event.refresh_failed")
                finalized = self._outbox.finish(
                    event_id, token, error, self._max_attempts
                )
                self._observe(
                    ("completed" if error is None else "refresh_failed")
                    if finalized
                    else "ignored"
                )
            else:
                self._observe("ignored")
        # Unknown/duplicate/leased notifications are safe to ack: SQL retains
        # every incomplete event and republishes after failures or worker crashes.
        self._client.xack(STREAM, GROUP, message_id)
        self._client.xdel(STREAM, message_id)

    # 方法说明：run_once
    # 作用：执行行为事件投递与消费后台工作者的一次后台处理周期。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def run_once(self) -> None:
        try:
            self._run_once()
        except Exception:
            self._observe("cycle_failed")
            raise
        else:
            self._observe("cycle_success")

    # 方法说明：_run_once
    # 作用：执行行为事件投递与消费后台工作者的一次后台处理周期。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def _run_once(self) -> None:
        self._ensure_group()
        self.relay()
        recovered = cast(
            Any,
            self._client.xautoclaim(
                STREAM,
                GROUP,
                self._consumer,
                min_idle_time=30000,
                start_id=self._cursor,
                count=self._batch,
            ),
        )
        self._cursor = recovered[0]
        for message_id, fields in recovered[1]:
            self.consume(message_id, fields)
        for _, messages in cast(
            Any,
            self._client.xreadgroup(
                GROUP,
                self._consumer,
                {STREAM: ">"},
                count=self._batch,
            ),
        ):
            for message_id, fields in messages:
                self.consume(message_id, fields)

    # 方法说明：start
    # 作用：启动行为事件投递与消费后台工作者的后台处理循环。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="behavior-events")

    # 方法说明：_run
    # 作用：运行行为事件投递与消费后台工作者封装的底层执行逻辑。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                logger.warning("behavior.event.worker_unavailable")
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
