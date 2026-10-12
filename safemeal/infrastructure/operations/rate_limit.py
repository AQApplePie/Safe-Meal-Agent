"""实现运行期运维能力。"""

from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis


_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local values = redis.call('HMGET', key, 'tokens', 'updated_ms')
local tokens = tonumber(values[1]) or capacity
local updated = tonumber(values[2]) or now_ms
tokens = math.min(capacity, tokens + math.max(0, now_ms - updated) * refill / 1000)
local allowed = 0
local retry_ms = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  retry_ms = math.ceil((requested - tokens) / refill * 1000)
end
redis.call('HMSET', key, 'tokens', tokens, 'updated_ms', now_ms)
redis.call('PEXPIRE', key, math.ceil(capacity / refill * 2000))
return {allowed, tostring(tokens), retry_ms}
"""


# 类说明（数据契约类）：TokenBucketDecision
# 作用：描述令牌桶允许或拒绝结果的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class TokenBucketDecision:
    # 字段说明：allowed
    # 作用：当前操作是否获准执行。
    # 类型：bool。
    allowed: bool
    # 字段说明：remaining
    # 作用：尚未完成的配额或剩余可用预算。
    # 类型：float。
    remaining: float
    # 字段说明：retry_after_ms
    # 作用：建议重试前等待的时间，单位为毫秒。
    # 类型：int。
    retry_after_ms: int


# 类说明（业务或基础设施实现类）：RedisTokenBucket
# 作用：实现Redis 原子令牌桶限流器，封装该组件的业务处理与依赖协作。
class RedisTokenBucket:
    # 方法说明：__init__
    # 作用：初始化Redis 原子令牌桶限流器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   url（str）：当前外部资源或服务的连接地址。
    #   prefix（str）：待匹配的名称或键前缀；默认值为 'safemeal:rate'。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, url: str, *, prefix: str = "safemeal:rate") -> None:
        # 实例属性说明：client
        # 作用：底层外部服务客户端。
        self.client = redis.from_url(
            url, decode_responses=True, socket_connect_timeout=0.2, socket_timeout=0.2
        )
        # 实例属性说明：prefix
        # 作用：待匹配的名称或键前缀。
        self.prefix = prefix

    # 方法说明：acquire
    # 作用：尝试取得受限资源的使用权，并返回本次取得结果。
    # 入参：
    #   key（str）：业务缓存键或记录键。
    #   capacity（int）：同时执行的最大任务数。
    #   refill_per_second（float）：令牌桶每秒补充的令牌数。
    #   tokens（int）：待统计或消费的 Token 数；默认值为 1。
    # 出参：TokenBucketDecision；令牌桶允许或拒绝结果。
    async def acquire(
        self,
        key: str,
        *,
        capacity: int,
        refill_per_second: float,
        tokens: int = 1,
    ) -> TokenBucketDecision:
        if capacity < 1 or refill_per_second <= 0 or tokens < 1:
            raise ValueError("token bucket values must be positive")
        result = await self.client.eval(
            _TOKEN_BUCKET_LUA,
            1,
            f"{self.prefix}:{key}",
            capacity,
            refill_per_second,
            tokens,
        )
        return TokenBucketDecision(
            allowed=bool(int(result[0])),
            remaining=float(result[1]),
            retry_after_ms=int(result[2]),
        )

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def close(self) -> None:
        await self.client.aclose()


__all__ = ["RedisTokenBucket", "TokenBucketDecision"]
