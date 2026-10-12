"""编排入口按需加载，证据模块的导入不应反向初始化整张图。"""

from typing import Any

__all__ = ["build_agent_graph"]


# 方法说明：__getattr__
# 作用：按需装配或加载公开导出符号，避免导入时初始化完整应用。
# 入参：
#   name（str）：当前对象或字段的名称。
# 出参：Any；按名称装配的公开路由或按需加载的公开函数。
def __getattr__(name: str) -> Any:
    if name == "build_agent_graph":
        from .graph import build_agent_graph

        return build_agent_graph
    raise AttributeError(name)
