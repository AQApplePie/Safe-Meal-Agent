"""Request-local document scope, supplied only by authenticated entry points."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_tenant: ContextVar[str] = ContextVar("knowledge_tenant", default="public")


# 方法说明：knowledge_tenant
# 作用：读取当前请求可信知识检索租户。
# 入参：
#   无显式入参。
# 出参：str；当前可信检索租户；无请求绑定时为 public。
def knowledge_tenant() -> str:
    return _tenant.get()


# 方法说明：knowledge_scope
# 作用：临时绑定可信知识租户范围，并在退出时恢复原上下文。
# 入参：
#   tenant_id（str）：可信租户标识，用于业务数据隔离。
# 出参：Iterator[None]；None（未取得结果）的迭代器。
@contextmanager
def knowledge_scope(tenant_id: str) -> Iterator[None]:
    if not tenant_id.strip():
        raise ValueError("tenant_id cannot be blank")
    token = _tenant.set(tenant_id)
    try:
        yield
    finally:
        _tenant.reset(token)
