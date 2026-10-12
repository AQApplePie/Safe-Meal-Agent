"""协调应用启动、健康检查与资源关闭。"""

from safemeal.infrastructure.operations.logging import configure_logging
from safemeal.shared.contracts.observability import HttpMetricsSink
from safemeal.infrastructure.operations.rate_limit import RedisTokenBucket


# 方法说明：create_rate_limiter
# 作用：按配置创建 Redis 令牌桶限流器。
# 入参：
#   url（str）：当前外部资源或服务的连接地址。
# 出参：按实现返回；RedisTokenBucket；当前 HTTP 限流配置使用的令牌桶。
def create_rate_limiter(url: str):
    return RedisTokenBucket(url, prefix="safemeal:http")


__all__ = [
    "configure_logging",
    "get_runtime_readiness",
    "create_rate_limiter",
    "create_runtime_metrics",
]


# 方法说明：get_runtime_readiness
# 作用：综合数据库和检索依赖的探测结果，生成运行就绪状态。
# 入参：
#   无显式入参。
# 出参：JsonObject；当前核心依赖的就绪状态与探测结果。
async def get_runtime_readiness():
    from safemeal.infrastructure.operations.health import get_runtime_readiness as probe

    return await probe()


# 方法说明：create_runtime_metrics
# 作用：创建本进程的请求、SQL 与事件处理指标收集器。
# 入参：
#   无显式入参。
# 出参：HttpMetricsSink；HTTP 请求观测接收器。
def create_runtime_metrics() -> HttpMetricsSink:
    from safemeal.infrastructure.operations.metrics import RuntimeMetrics

    return RuntimeMetrics()
