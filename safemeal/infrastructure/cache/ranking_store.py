"""Redis ZSet 快照；租约隔离刷新，临时键与 Lua 原子发布/读取。"""

from datetime import date
from hashlib import sha256
import json
from uuid import uuid4
from redis import Redis
from redis.exceptions import RedisError
from pydantic import ValidationError
from safemeal.modules.interaction.contracts.ranking import (
    RankingMode,
    RankingPage,
    RankingSnapshot,
    RankingItem,
)

_PUBLISH = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call('EXISTS', KEYS[4]) == 0 then return 0 end
local n = tonumber(ARGV[3])
if n > 0 and (redis.call('ZCARD', KEYS[2]) ~= n or redis.call('HLEN', KEYS[3]) ~= n) then return 0 end
redis.call('DEL', KEYS[5], KEYS[6])
if n > 0 then
 redis.call('RENAME', KEYS[2], KEYS[5])
 redis.call('RENAME', KEYS[3], KEYS[6])
 redis.call('EXPIRE', KEYS[5], ARGV[2])
 redis.call('EXPIRE', KEYS[6], ARGV[2])
end
redis.call('RENAME', KEYS[4], KEYS[7])
redis.call('EXPIRE', KEYS[7], ARGV[2])
return 1
"""
_READ = """
local meta = redis.call('GET', KEYS[3])
if not meta then return nil end
local n = redis.call('ZCARD', KEYS[1])
if redis.call('HLEN', KEYS[2]) ~= n then return nil end
local rows = redis.call('ZREVRANGE', KEYS[1], ARGV[1], ARGV[2], 'WITHSCORES')
local result = {meta, tostring(n)}
for i=1,#rows,2 do
 local name = redis.call('HGET', KEYS[2], rows[i])
 if not name then return nil end
 table.insert(result, rows[i]); table.insert(result, rows[i+1]); table.insert(result, name)
end
return result
"""
_RELEASE = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"


# 类说明（业务或基础设施实现类）：RedisRankingStore
# 作用：实现Redis 榜单快照与租约存储，封装该组件的业务处理与依赖协作。
class RedisRankingStore:
    # 方法说明：__init__
    # 作用：初始化Redis 榜单快照与租约存储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   client（Redis）：底层外部服务客户端。
    #   ttl_seconds（int）：缓存或记录的有效时长，单位秒；默认值为 300。
    #   lease_seconds（int）：处理租约的有效时长，单位秒；默认值为 120。
    #   profile（str）：食材营养与功效资料；默认值为 'default'。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        client: Redis,
        *,
        ttl_seconds: int = 300,
        lease_seconds: int = 120,
        profile: str = "default",
    ) -> None:
        # 实例属性说明：_profile
        # 作用：食材营养与功效资料。
        self._profile = sha256(profile.encode()).hexdigest()
        # 实例属性说明：_client
        # 作用：底层外部服务客户端。
        self._client = client
        # 实例属性说明：_ttl
        # 作用：缓存或记录的有效时长，单位秒。
        self._ttl = ttl_seconds
        # 实例属性说明：_lease
        # 作用：处理租约的有效时长，单位秒。
        self._lease = lease_seconds
        # 实例属性说明：_publish_script
        # 作用：发布缓存或排名数据的 Redis Lua 脚本。
        self._publish_script = client.register_script(_PUBLISH)
        # 实例属性说明：_read_script
        # 作用：读取 Redis 数据的 Lua 脚本。
        self._read_script = client.register_script(_READ)
        # 实例属性说明：_release_script
        # 作用：释放持有资源的 Redis Lua 脚本。
        self._release_script = client.register_script(_RELEASE)

    # 方法说明：_prefix
    # 作用：生成包含租户边界的榜单缓存键前缀。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：str；隔离当前租户数据的缓存键前缀。
    def _prefix(self, tenant_id: str) -> str:
        return (
            "safemeal:rankings:v1:{"
            + sha256(tenant_id.encode()).hexdigest()
            + "}:"
            + self._profile
        )

    # 方法说明：_keys
    # 作用：生成榜单分数、有序条目名称及快照元数据的 Redis 键。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   mode（RankingMode）：当前榜单或运行模式。
    #   day（date | None）：今日榜单对应的日期。
    # 出参：tuple[str, str, str]；当前榜单使用的 Redis 键元组。
    def _keys(
        self, tenant_id: str, mode: RankingMode, day: date | None
    ) -> tuple[str, str, str]:
        prefix = (
            self._prefix(tenant_id) + f":{mode}:{day.isoformat() if day else 'all'}"
        )
        return prefix + ":scores", prefix + ":names", prefix + ":meta"

    # 方法说明：acquire
    # 作用：尝试取得受限资源的使用权，并返回本次取得结果。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：str | None；文本字符串或None（未取得结果）。
    def acquire(self, tenant_id: str) -> str | None:
        token = uuid4().hex
        try:
            return (
                token
                if self._client.set(
                    self._prefix(tenant_id) + ":lease", token, nx=True, ex=self._lease
                )
                else None
            )
        except RedisError:
            return None

    # 方法说明：release
    # 作用：仅在令牌匹配时释放榜单刷新租约。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   token（str）：令牌或本次租约的处理凭证。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def release(self, tenant_id: str, token: str) -> None:
        try:
            self._release_script(
                keys=[self._prefix(tenant_id) + ":lease"], args=[token]
            )
        except RedisError:
            pass

    # 方法说明：publish
    # 作用：在租约有效时发布完整榜单快照，原子切换可见数据。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   token（str）：令牌或本次租约的处理凭证。
    #   snapshot（RankingSnapshot）：完整榜单快照。
    # 出参：bool；当前有效租约下是否成功发布完整榜单。
    def publish(self, tenant_id: str, token: str, snapshot: RankingSnapshot) -> bool:
        keys = self._keys(tenant_id, snapshot.mode, snapshot.day)
        temporary = tuple(key + ":tmp:" + uuid4().hex for key in keys)
        metadata = snapshot.model_dump(mode="json", exclude={"items"})
        metadata["ranked_count"] = len(snapshot.items)
        try:
            with self._client.pipeline(transaction=True) as pipeline:
                if snapshot.items:
                    pipeline.zadd(
                        temporary[0],
                        {
                            f"{item.recipe_id:010d}": item.score
                            for item in snapshot.items
                        },
                    )
                    pipeline.hset(
                        temporary[1],
                        mapping={
                            f"{item.recipe_id:010d}": item.recipe_name
                            for item in snapshot.items
                        },
                    )
                    pipeline.expire(temporary[0], self._lease)
                    pipeline.expire(temporary[1], self._lease)
                pipeline.set(temporary[2], json.dumps(metadata), ex=self._lease)
                pipeline.execute()
            return bool(
                self._publish_script(
                    keys=[self._prefix(tenant_id) + ":lease", *temporary, *keys],
                    args=[token, self._ttl, len(snapshot.items)],
                )
            )
        except RedisError:
            return False
        finally:
            try:
                self._client.delete(*temporary)
            except RedisError:
                pass

    # 方法说明：read
    # 作用：通过Redis 榜单快照与租约存储读取目标记录或当前状态。
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
    ) -> RankingPage | None:
        try:
            rows = self._read_script(
                keys=list(self._keys(tenant_id, mode, day)),
                args=[offset, offset + limit - 1],
            )
            if not rows:
                return None
            meta = json.loads(rows[0])
            count = int(rows[1])
            if (
                meta["ranked_count"] != count
                or meta["mode"] != mode
                or meta["day"] != (day.isoformat() if day else None)
            ):
                return None
            items: list[RankingItem] = []
            for i in range(2, len(rows), 3):
                score = float(rows[i + 1])
                if not score.is_integer():
                    return None
                items.append(
                    RankingItem(
                        recipe_id=int(rows[i]),
                        recipe_name=rows[i + 2],
                        score=int(score),
                        rank=offset + len(items) + 1,
                    )
                )
            return RankingPage(
                **meta,
                source="redis",
                items=tuple(items),
                has_more=offset + limit < count,
            )
        except (
            RedisError,
            ValueError,
            TypeError,
            KeyError,
            UnicodeError,
            ValidationError,
        ):
            return None
