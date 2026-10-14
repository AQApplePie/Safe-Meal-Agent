"""Process-local bounded metrics; no SDK, identity labels or external writes."""

from collections import defaultdict
from threading import Lock
from time import time
import json

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


# 类说明（业务或基础设施实现类）：RuntimeMetrics
# 作用：实现HTTP SQL 与事件运行指标收集器，封装该组件的业务处理与依赖协作。
class RuntimeMetrics:
    # 方法说明：__init__
    # 作用：初始化HTTP SQL 与事件运行指标收集器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self) -> None:
        # 实例属性说明：_lock
        # 作用：保护共享状态的互斥锁。
        self._lock = Lock()
        # 实例属性说明：_http
        # 作用：按 HTTP 请求维度保存的统计指标。
        # 类型：dict[tuple[str, str, int], list[float]]。
        # 初始值：{}。
        self._http: dict[tuple[str, str, int], list[float]] = {}
        # 实例属性说明：_reads
        # 作用：累计读取次数。
        # 类型：dict[tuple[str, str], int]。
        self._reads: dict[tuple[str, str], int] = defaultdict(int)
        # 实例属性说明：_cache_errors
        # 作用：缓存操作失败次数。
        # 类型：dict[str, int]。
        self._cache_errors: dict[str, int] = defaultdict(int)
        # 实例属性说明：_behavior
        # 作用：按事件结果或类型累计的行为处理指标。
        # 类型：dict[str, int]。
        self._behavior: dict[str, int] = defaultdict(int)
        # 实例属性说明：_last_success
        # 作用：最近一次处理成功时间。
        # 初始值：0.0。
        self._last_success = 0.0

    # 方法说明：http
    # 作用：登记 HTTP 方法、路由、状态码和处理耗时指标。
    # 入参：
    #   method（str）：HTTP 请求方法。
    #   route（str）：HTTP 路由模板或业务路由标识。
    #   status（int）：HTTP 状态码或业务状态。
    #   seconds（float）：当前操作耗时或持续时长，单位秒。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def http(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            values = self._http.setdefault(
                (method, route, status), [0.0] * (len(BUCKETS) + 2)
            )
            for i, bound in enumerate(BUCKETS):
                values[i] += seconds <= bound
            values[-2] += 1
            values[-1] += seconds

    # 方法说明：recipe_read
    # 作用：登记一次食谱查询的耗时及结果状态指标。
    # 入参：
    #   kind（str）：当前业务记录或操作的类型。
    #   source（str）：数据来源标识或提供该数据的对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def recipe_read(self, kind: str, source: str) -> None:
        if kind not in ("list", "detail"):
            return
        with self._lock:
            if source in ("l1", "redis", "database"):
                self._reads[kind, source] += 1
            elif source in ("redis_read_error", "redis_write_error", "decode_error"):
                self._cache_errors[source] += 1

    # 方法说明：behavior
    # 作用：登记行为事件处理结果指标。
    # 入参：
    #   outcome（str）：本次事件或查询处理的结果类别。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def behavior(self, outcome: str) -> None:
        if outcome not in (
            "published",
            "completed",
            "refresh_failed",
            "ignored",
            "invalid",
            "cycle_failed",
            "cycle_success",
        ):
            return
        with self._lock:
            self._behavior[outcome] += 1
            if outcome == "cycle_success":
                self._last_success = time()

    # 方法说明：render
    # 作用：将HTTP SQL 与事件运行指标收集器的结构化内容渲染为文本。
    # 入参：
    #   outbox（dict[str, float]）：同事务行为事件持久化组件。
    # 出参：str；文本字符串。
    def render(self, outbox: dict[str, float]) -> str:
        # 方法说明：labels
        # 作用：转义并编码 Prometheus 指标标签。
        # 入参：
        #   **values（按调用签名约定）：当前待处理的值集合。
        # 出参：str；经过转义的 Prometheus 标签文本。
        def labels(**values) -> str:
            return (
                "{"
                + ",".join(
                    f"{key}={json.dumps(str(value), ensure_ascii=False)}"
                    for key, value in values.items()
                )
                + "}"
            )

        with self._lock:
            lines = [
                "# TYPE safemeal_http_requests_total counter",
                "# TYPE safemeal_http_request_duration_seconds histogram",
            ]
            for (method, route, status), values in sorted(self._http.items()):
                base = dict(method=method, route=route, status=status)
                lines.append(
                    f"safemeal_http_requests_total{labels(**base)} {values[-2]:.17g}"
                )
                for bound, count in zip(BUCKETS, values):
                    lines.append(
                        f"safemeal_http_request_duration_seconds_bucket{labels(**base, le=bound)} {count:.17g}"
                    )
                lines.extend(
                    (
                        f"safemeal_http_request_duration_seconds_bucket{labels(**base, le='+Inf')} {values[-2]:.17g}",
                        f"safemeal_http_request_duration_seconds_count{labels(**base)} {values[-2]:.17g}",
                        f"safemeal_http_request_duration_seconds_sum{labels(**base)} {values[-1]:.17g}",
                    )
                )
            lines.append("# TYPE safemeal_recipe_cache_requests_total counter")
            for (kind, source), count in sorted(self._reads.items()):
                lines.append(
                    f"safemeal_recipe_cache_requests_total{labels(kind=kind, source=source)} {count}"
                )
            lines.append("# TYPE safemeal_recipe_cache_errors_total counter")
            for operation, count in sorted(self._cache_errors.items()):
                lines.append(
                    f"safemeal_recipe_cache_errors_total{labels(operation=operation)} {count}"
                )
            lines.append("# TYPE safemeal_behavior_events_total counter")
            for outcome, count in sorted(self._behavior.items()):
                lines.append(
                    f"safemeal_behavior_events_total{labels(outcome=outcome)} {count}"
                )
            lines.extend(
                (
                    "# TYPE safemeal_behavior_last_success_unixtime gauge",
                    f"safemeal_behavior_last_success_unixtime {self._last_success:.17g}",
                )
            )
        for name, value in sorted(outbox.items()):
            lines.extend(
                (
                    f"# TYPE safemeal_outbox_{name} gauge",
                    f"safemeal_outbox_{name} {value:.17g}",
                )
            )
        return "\n".join(lines) + "\n"
