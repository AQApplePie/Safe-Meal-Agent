"""食谱仓储的缓存装饰器；不参与推荐、约束或 Agent 决策。"""

from collections import OrderedDict
from hashlib import sha256
import random
from threading import Lock
from time import monotonic
from typing import Callable, TypeVar

from loguru import logger
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import RedisError

from safemeal.modules.recipe.contracts.catalog import RecipeQuery, RecipeSearchResult
from safemeal.modules.recipe.contracts.models import Recipe
from safemeal.modules.recipe.ports.recipe_repository import RecipeRepository

T = TypeVar("T", Recipe, RecipeSearchResult)


# 类说明（业务或基础设施实现类）：CachedRecipeRepository
# 作用：Redis cache-aside + 有界 L1；锁条带合并同进程热点回源。
class CachedRecipeRepository:
    """Redis cache-aside + 有界 L1；锁条带合并同进程热点回源。"""

    # 字段说明：_MAX_CACHE_VALUE_BYTES
    # 作用：最大缓存VALUEBYTES，供该组件初始化及运行控制使用。
    _MAX_CACHE_VALUE_BYTES = 256 * 1024

    # 方法说明：__init__
    # 作用：初始化菜谱两级缓存仓储装饰器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   repository（RecipeRepository）：当前业务依赖的仓储实现。
    #   redis（Redis）：Redis 客户端。
    #   ttl_seconds（int）：缓存或记录的有效时长，单位秒；默认值为 60。
    #   negative_ttl_seconds（int）：不存在记录的空值缓存时长，单位秒；默认值为 10。
    #   local_ttl_seconds（float）：进程内缓存有效时长，单位秒；默认值为 1.0。
    #   local_capacity（int）：进程内缓存允许保存的最大条目数；默认值为 256。
    #   observer（Callable[[str, str], None] | None）：请求指标或轨迹观察组件；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        repository: RecipeRepository,
        redis: Redis,
        *,
        ttl_seconds: int = 60,
        negative_ttl_seconds: int = 10,
        local_ttl_seconds: float = 1.0,
        local_capacity: int = 256,
        observer: Callable[[str, str], None] | None = None,
    ) -> None:
        if (
            ttl_seconds <= 0
            or negative_ttl_seconds <= 0
            or local_capacity <= 0
            or local_ttl_seconds < 0
        ):
            raise ValueError(
                "Cache TTL/capacity must be positive; local TTL must be nonnegative"
            )
        # 实例属性说明：_observer
        # 作用：请求指标或轨迹观察组件。
        self._observer = observer
        # 实例属性说明：_repository
        # 作用：当前业务依赖的仓储实现。
        self._repository = repository
        # 实例属性说明：_redis
        # 作用：Redis 客户端。
        self._redis = redis
        # 实例属性说明：_ttl
        # 作用：缓存或记录的有效时长，单位秒。
        self._ttl = ttl_seconds
        # 实例属性说明：_negative_ttl
        # 作用：不存在记录的空值缓存时长，单位秒。
        self._negative_ttl = negative_ttl_seconds
        # 实例属性说明：_local_ttl
        # 作用：进程内缓存有效时长，单位秒。
        self._local_ttl = local_ttl_seconds
        # 实例属性说明：_capacity
        # 作用：同时执行的最大任务数。
        self._capacity = local_capacity
        # 实例属性说明：_local
        # 作用：当前进程的缓存或线程本地状态。
        # 类型：OrderedDict[str, tuple[float, str]]。
        self._local: OrderedDict[str, tuple[float, str]] = OrderedDict()
        # 实例属性说明：_local_lock
        # 作用：保护当前进程缓存的互斥锁。
        self._local_lock = Lock()
        # 实例属性说明：_load_locks
        # 作用：按键分段的本进程加载锁，减少同键并发回源。
        self._load_locks = [Lock() for _ in range(64)]

    # 方法说明：search
    # 作用：通过菜谱两级缓存仓储装饰器按查询条件检索候选及其证据。
    # 入参：
    #   query（RecipeQuery）：食谱筛选与推荐查询。
    # 出参：RecipeSearchResult；食谱查询与推荐结果。
    def search(self, query: RecipeQuery) -> RecipeSearchResult:
        # 参数完整参与 Key；列表顺序保持不变，不能与另一组过滤或分页混用。
        digest = sha256(query.model_dump_json().encode()).hexdigest()
        result = self._read(
            f"safemeal:recipes:v1:list:{digest}",
            RecipeSearchResult,
            lambda: self._repository.search(query),
        )
        assert result is not None
        return result

    # 方法说明：get
    # 作用：通过菜谱两级缓存仓储装饰器读取指定标识对应的业务对象。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    # 出参：Recipe | None；完整食谱业务模型或None（未取得结果）。
    def get(self, recipe_id: int) -> Recipe | None:
        return self._read(
            f"safemeal:recipes:v1:detail:{recipe_id}",
            Recipe,
            lambda: self._repository.get(recipe_id),
        )

    # 方法说明：_observe
    # 作用：向指标收集器登记本次缓存读取或事件处理结果。
    # 入参：
    #   kind（str）：当前业务记录或操作的类型。
    #   source（str）：数据来源标识或提供该数据的对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def _observe(self, kind: str, source: str) -> None:
        if self._observer is not None:
            try:
                self._observer(kind, source)
            except Exception:
                logger.debug("recipe.cache.observer_failed")

    # 方法说明：_read
    # 作用：在菜谱两级缓存仓储装饰器内部读取底层响应或持久数据。
    # 入参：
    #   key（str）：业务缓存键或记录键。
    #   model（type[T]）：当前调用使用的模型名称。
    #   load（Callable[[], T | None]）：是否加载集合以供查询。
    # 出参：T | None；由泛型调用约定决定的结果或None（未取得结果）。
    def _read(self, key: str, model: type[T], load: Callable[[], T | None]) -> T | None:
        kind = "list" if model is RecipeSearchResult else "detail"

        # 方法说明：cached
        # 作用：依次检查 L1 与 Redis 缓存，校验载荷并返回缓存命中情况。
        # 入参：
        #   无显式入参。
        # 出参：tuple[bool, T | None, str]；缓存是否命中、解析后的业务结果以及命中来源的三元组。
        def cached() -> tuple[bool, T | None, str]:
            payload: str | bytes | None = self._local_get(key)
            source = "l1" if payload is not None else "redis"
            if payload is None:
                try:
                    raw = self._redis.get(key)
                    payload = raw if isinstance(raw, (str, bytes)) else None
                except RedisError:
                    self._observe(kind, "redis_read_error")
                    logger.debug("Recipe cache unavailable; falling back to repository")
            if payload is None:
                return False, None, source
            if isinstance(payload, bytes):
                try:
                    payload = payload.decode("utf-8")
                except UnicodeDecodeError:
                    self._observe(kind, "decode_error")
                    return False, None, source
            try:
                if payload == "null" and model is not Recipe:
                    return False, None, source
                value = (
                    None if payload == "null" else model.model_validate_json(payload)
                )
            except (ValidationError, ValueError, TypeError):
                self._observe(kind, "decode_error")
                # 损坏/过期 schema 的缓存不能伪装成业务结果。
                return False, None, source
            self._local_set(key, payload)
            return True, value, source

        hit, value, source = cached()
        if hit:
            self._observe(kind, source)
            return value
        stripe = int(sha256(key.encode()).hexdigest(), 16) % len(self._load_locks)
        with self._load_locks[stripe]:
            hit, value, source = cached()
            if hit:
                self._observe(kind, source)
                return value
            self._observe(kind, "database")
            value = load()  # 数据库失败直接传播，绝不写成空结果缓存。
            payload = "null" if value is None else value.model_dump_json()
            if len(payload.encode("utf-8")) > self._MAX_CACHE_VALUE_BYTES:
                return value
            ttl = self._negative_ttl if value is None else self._ttl
            ttl += random.randint(0, max(1, ttl // 5))
            try:
                self._redis.set(key, payload, ex=ttl)
            except RedisError:
                self._observe(kind, "redis_write_error")
                logger.debug("Recipe cache write failed; returning repository result")
            self._local_set(key, payload)
            return value

    # 方法说明：_local_get
    # 作用：读取进程内缓存并检查过期时间。
    # 入参：
    #   key（str）：业务缓存键或记录键。
    # 出参：str | None；尚未过期的 L1 缓存载荷；未命中时为 None。
    def _local_get(self, key: str) -> str | None:
        with self._local_lock:
            item = self._local.get(key)
            if item is None:
                return None
            if item[0] <= monotonic():
                del self._local[key]
                return None
            self._local.move_to_end(key)
            return item[1]

    # 方法说明：_local_set
    # 作用：写入进程内缓存，并按容量限制淘汰旧项。
    # 入参：
    #   key（str）：业务缓存键或记录键。
    #   payload（str）：当前协议或持久化操作的数据载荷。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def _local_set(self, key: str, payload: str) -> None:
        with self._local_lock:
            if key not in self._local and len(self._local) >= self._capacity:
                self._local.popitem(last=False)
            # 命中不刷新过期时间，持续访问也必须重新读取 Redis/数据库。
            existing = self._local.get(key)
            deadline = (
                existing[0] if existing is not None else monotonic() + self._local_ttl
            )
            self._local[key] = (deadline, payload)
            self._local.move_to_end(key)
