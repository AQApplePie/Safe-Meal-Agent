"""传统后端组合根；不导入模型、检索或 Agent checkpoint。"""

from __future__ import annotations
import asyncio
from contextlib import ExitStack
from threading import RLock
from time import monotonic, time
from zoneinfo import ZoneInfo
from redis import ConnectionPool, Redis
from loguru import logger
from safemeal.config.platform import PlatformSettings
from safemeal.infrastructure.operations.metrics import RuntimeMetrics
from safemeal.infrastructure.persistence.database import (
    configure_database,
    dispose_engine,
)
from safemeal.infrastructure.persistence.behavior_outbox import SqlBehaviorOutbox
from safemeal.infrastructure.messaging.behavior_worker import BehaviorWorker
from safemeal.infrastructure.persistence.ranking_repository import (
    SqlAlchemyRankingRepository,
)
from safemeal.infrastructure.cache.ranking_store import RedisRankingStore
from safemeal.infrastructure.cache.ranking_worker import RankingWorker
from safemeal.infrastructure.persistence.history_repository import (
    SqlAlchemyHistoryRepository,
)
from safemeal.infrastructure.persistence.reaction_repository import (
    SqlAlchemyReactionRepository,
)
from safemeal.infrastructure.cache.recipe_repository import CachedRecipeRepository
from safemeal.infrastructure.persistence.recipe_repository import (
    SqlAlchemyRecipeRepository,
)
from safemeal.infrastructure.persistence.auth_repository import (
    sqlalchemy_auth_unit_of_work,
)
from safemeal.infrastructure.security import Argon2PasswordHasher, JwtTokenIssuer
from safemeal.modules.interaction.application.ranking_service import RankingService
from safemeal.modules.interaction.application.history_service import HistoryService
from safemeal.modules.interaction.application.interaction_service import (
    InteractionService,
)
from safemeal.modules.recipe.application import RecipeService
from safemeal.modules.recipe.ports.recipe_repository import RecipeRepository
from safemeal.modules.identity.application import AuthService


# 类说明（依赖装配类）：PlatformContainer
# 作用：集中构建与管理传统平台依赖容器中的业务服务和基础设施资源。
class PlatformContainer:
    # 方法说明：__init__
    # 作用：初始化传统平台依赖容器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   config（PlatformSettings）：图调用或检查点配置。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, config: PlatformSettings) -> None:
        # 实例属性说明：config
        # 作用：图调用或检查点配置。
        self.config = config
        # 实例属性说明：metrics
        # 作用：运行指标收集组件。
        self.metrics = RuntimeMetrics()
        # 实例属性说明：_metrics_lock
        # 作用：保护指标采集状态的互斥锁。
        self._metrics_lock = asyncio.Lock()
        # 实例属性说明：_metrics_checked_at
        # 作用：上一次采集监控指标的时间。
        # 初始值：0.0。
        self._metrics_checked_at = 0.0
        # 实例属性说明：_outbox_metrics
        # 作用：事务发件箱状态统计快照。
        # 类型：dict[str, float]。
        # 初始值：{}。
        self._outbox_metrics: dict[str, float] = {}
        configure_database(
            config.DATABASE_URL,
            debug=config.DEBUG,
            connect_timeout=config.DB_CONNECT_TIMEOUT,
            lock_wait_timeout=config.DB_LOCK_WAIT_TIMEOUT_SECONDS,
        )
        # 实例属性说明：_singleton_lock
        # 作用：保护单例依赖创建的互斥锁。
        self._singleton_lock = RLock()
        # 实例属性说明：_resource_stack
        # 作用：统一管理依赖资源的退出栈。
        self._resource_stack = ExitStack()
        # 实例属性说明：_behavior_worker
        # 作用：延迟创建的行为事件后台处理器。
        # 类型：BehaviorWorker | None。
        # 初始值：None。
        self._behavior_worker: BehaviorWorker | None = None
        # 实例属性说明：_behavior_outbox
        # 作用：SQL 行为事务发件箱，记录待异步处理事件；未启用行为事件时为 None。
        self._behavior_outbox = (
            SqlBehaviorOutbox() if config.BEHAVIOR_EVENT_REDIS_URL else None
        )
        # 实例属性说明：_ranking_service
        # 作用：延迟创建的热门菜谱榜单查询服务。
        # 类型：RankingService | None。
        # 初始值：None。
        self._ranking_service: RankingService | None = None
        # 实例属性说明：_ranking_worker
        # 作用：延迟创建的榜单刷新后台处理器。
        # 类型：RankingWorker | None。
        # 初始值：None。
        self._ranking_worker: RankingWorker | None = None
        # 实例属性说明：_history_service
        # 作用：历史消息及活动菜单读取服务。
        # 类型：HistoryService | None。
        # 初始值：None。
        self._history_service: HistoryService | None = None
        # 实例属性说明：_interaction_service
        # 作用：延迟创建的点赞、收藏和浏览历史业务服务。
        # 类型：InteractionService | None。
        # 初始值：None。
        self._interaction_service: InteractionService | None = None
        # 实例属性说明：_recipe_browse_service
        # 作用：延迟创建的菜谱列表与详情查询服务。
        # 类型：RecipeService | None。
        # 初始值：None。
        self._recipe_browse_service: RecipeService | None = None
        # 实例属性说明：_recipe_repository
        # 作用：延迟创建的菜谱数据库仓储。
        # 类型：RecipeRepository | None。
        # 初始值：None。
        self._recipe_repository: RecipeRepository | None = None
        # 实例属性说明：_auth_service
        # 作用：身份认证与令牌业务服务。
        # 类型：AuthService | None。
        # 初始值：None。
        self._auth_service: AuthService | None = None

    # 方法说明：_get_recipe_repository
    # 作用：取得当前装配的菜谱仓储，供图检索读取结构化详情。
    # 入参：
    #   无显式入参。
    # 出参：RecipeRepository；食谱仓储接口。
    def _get_recipe_repository(self) -> RecipeRepository:
        with self._singleton_lock:
            if self._recipe_repository is None:
                repository: RecipeRepository = SqlAlchemyRecipeRepository()
                if self.config.RECIPE_CACHE_URL:
                    pool = ConnectionPool.from_url(
                        self.config.RECIPE_CACHE_URL,
                        decode_responses=True,
                        socket_connect_timeout=0.2,
                        socket_timeout=0.2,
                    )
                    cache = Redis(connection_pool=pool)
                    self._resource_stack.callback(pool.disconnect)
                    self._resource_stack.callback(cache.close)
                    repository = CachedRecipeRepository(
                        repository,
                        cache,
                        ttl_seconds=self.config.RECIPE_CACHE_TTL_SECONDS,
                        observer=self.metrics.recipe_read
                        if self.config.METRICS_ENABLED
                        else None,
                    )
                self._recipe_repository = repository
            return self._recipe_repository

    # 方法说明：get_ranking_service
    # 作用：提供热门榜单读取与刷新服务。
    # 入参：
    #   无显式入参。
    # 出参：RankingService；热门榜单读取与重建服务。
    def get_ranking_service(self) -> RankingService:
        with self._singleton_lock:
            if self._ranking_service is None:
                store = None
                if self.config.RECIPE_RANKING_REDIS_URL:
                    pool = ConnectionPool.from_url(
                        self.config.RECIPE_RANKING_REDIS_URL,
                        decode_responses=True,
                        socket_connect_timeout=0.2,
                        socket_timeout=0.2,
                    )
                    client = Redis(connection_pool=pool)
                    self._resource_stack.callback(pool.disconnect)
                    self._resource_stack.callback(client.close)
                    store = RedisRankingStore(
                        client,
                        ttl_seconds=self.config.RECIPE_RANKING_TTL_SECONDS,
                        profile=f"{self.config.RECIPE_RANKING_TIMEZONE}:{self.config.RECIPE_RANKING_CAP}",
                    )
                self._ranking_service = RankingService(
                    SqlAlchemyRankingRepository(),
                    store,
                    cap=self.config.RECIPE_RANKING_CAP,
                    day_timezone=ZoneInfo(self.config.RECIPE_RANKING_TIMEZONE),
                )
            return self._ranking_service

    # 方法说明：start_ranking_worker
    # 作用：按配置启动周期性榜单恢复任务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def start_ranking_worker(self) -> None:
        self.start_behavior_worker()
        if self.config.RECIPE_RANKING_REDIS_URL and self._ranking_worker is None:
            self._ranking_worker = RankingWorker(
                self.get_ranking_service(),
                self.config.RECIPE_RANKING_REFRESH_SECONDS,
                self.config.RECIPE_RANKING_TENANT_BATCH,
            )
            self._ranking_worker.start()

    # 方法说明：start_behavior_worker
    # 作用：按应用配置启动行为 outbox 投递和消费后台任务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def start_behavior_worker(self) -> None:
        if self._behavior_outbox is None or self._behavior_worker is not None:
            return
        if not self.config.RECIPE_RANKING_REDIS_URL:
            raise ValueError("Behavior events require RECIPE_RANKING_REDIS_URL")
        pool = ConnectionPool.from_url(
            self.config.BEHAVIOR_EVENT_REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        client = Redis(connection_pool=pool)
        self._resource_stack.callback(pool.disconnect)
        self._resource_stack.callback(client.close)
        self._behavior_worker = BehaviorWorker(
            self._behavior_outbox,
            client,
            self.get_ranking_service(),
            batch_size=self.config.BEHAVIOR_EVENT_BATCH,
            interval_seconds=self.config.BEHAVIOR_EVENT_POLL_SECONDS,
            max_attempts=self.config.BEHAVIOR_EVENT_MAX_ATTEMPTS,
            observer=self.metrics.behavior if self.config.METRICS_ENABLED else None,
        )
        self._behavior_worker.start()

    # 方法说明：get_history_service
    # 作用：提供浏览历史写入及分页查询服务。
    # 入参：
    #   无显式入参。
    # 出参：HistoryService；浏览历史业务服务。
    def get_history_service(self) -> HistoryService:
        with self._singleton_lock:
            if self._history_service is None:
                self._history_service = HistoryService(
                    SqlAlchemyHistoryRepository(
                        outbox=self._behavior_outbox,
                        transaction_attempts=self.config.DB_TRANSACTION_MAX_ATTEMPTS,
                    )
                )
            return self._history_service

    # 方法说明：get_interaction_service
    # 作用：提供点赞、收藏及批量状态查询服务。
    # 入参：
    #   无显式入参。
    # 出参：InteractionService；点赞收藏业务服务。
    def get_interaction_service(self) -> InteractionService:
        with self._singleton_lock:
            if self._interaction_service is None:
                self._interaction_service = InteractionService(
                    SqlAlchemyReactionRepository(
                        outbox=self._behavior_outbox,
                        transaction_attempts=self.config.DB_TRANSACTION_MAX_ATTEMPTS,
                    )
                )
            return self._interaction_service

    # 方法说明：get_recipe_browse_service
    # 作用：公共读取仅需规范仓储，不初始化模型或外部食谱提供者。
    # 入参：
    #   无显式入参。
    # 出参：RecipeService；食谱查询推荐与生成业务服务。
    def get_recipe_browse_service(self) -> RecipeService:
        """公共读取仅需规范仓储，不初始化模型或外部食谱提供者。"""
        with self._singleton_lock:
            if self._recipe_browse_service is None:
                self._recipe_browse_service = RecipeService(
                    self._get_recipe_repository()
                )
            return self._recipe_browse_service

    # 方法说明：get_auth_service
    # 作用：提供注册、登录及令牌验证业务服务。
    # 入参：
    #   无显式入参。
    # 出参：AuthService；注册登录与令牌管理服务。
    def get_auth_service(self) -> AuthService:
        if self._auth_service is None:
            with self._singleton_lock:
                if self._auth_service is None:
                    self._auth_service = AuthService(
                        uow_factory=sqlalchemy_auth_unit_of_work,
                        password_hasher=Argon2PasswordHasher(),
                        token_issuer=JwtTokenIssuer(
                            secret=self.config.AUTH_JWT_SECRET,
                            issuer=self.config.AUTH_JWT_ISSUER,
                            audience=self.config.AUTH_JWT_AUDIENCE,
                            access_token_minutes=self.config.AUTH_ACCESS_TOKEN_MINUTES,
                        ),
                        refresh_token_days=self.config.AUTH_REFRESH_TOKEN_DAYS,
                        default_tenant_id=self.config.DEFAULT_TENANT_ID,
                    )
        return self._auth_service

    # 方法说明：get_outbox_metrics
    # 作用：读取 outbox 状态聚合指标并形成观测结果。
    # 入参：
    #   无显式入参。
    # 出参：dict[str, float]；文本字符串、数值组成的映射。
    async def get_outbox_metrics(self) -> dict[str, float]:
        if self._behavior_outbox is None:
            return {"enabled": 0.0, "collector_up": 0.0}
        async with self._metrics_lock:
            if (
                monotonic() - self._metrics_checked_at
                < self.config.METRICS_OUTBOX_SCRAPE_SECONDS
            ):
                return dict(self._outbox_metrics)
            try:
                snapshot = await asyncio.to_thread(
                    self._behavior_outbox.metrics_snapshot
                )
                self._outbox_metrics = {"enabled": 1.0, "collector_up": 1.0, **snapshot}
            except Exception:
                # Omit stale gauges rather than misreporting an empty healthy queue.
                self._outbox_metrics = {"enabled": 1.0, "collector_up": 0.0}
            self._outbox_metrics["collected_unixtime"] = time()
            self._metrics_checked_at = monotonic()
            return dict(self._outbox_metrics)

    # 方法说明：shutdown
    # 作用：关闭应用依赖与后台任务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def shutdown(self) -> None:
        try:
            workers = [
                worker
                for worker in (self._behavior_worker, self._ranking_worker)
                if worker is not None
            ]
            results = await asyncio.gather(
                *(worker.close() for worker in workers), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    logger.warning(
                        "Background worker shutdown failed: {}", type(result).__name__
                    )
        finally:
            try:
                await asyncio.to_thread(dispose_engine)
            finally:
                self._resource_stack.close()
