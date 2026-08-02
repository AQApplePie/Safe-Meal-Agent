"""Application use cases orchestrating domain, ports and external adapters.

本包放“应用用例编排”，不是可独立部署的服务。

``safemeal.application.use_cases``只负责进程内部的一次业务用例编排。
"""

__all__ = [
    "agent",
    "chat",
    "knowledge",
    "memory",
    "upload",
]
