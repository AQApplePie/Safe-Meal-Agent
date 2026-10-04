"""Agent orchestration layer: plan, approve, execute, observe and reflect.

The layer decides *when* capabilities run. It never owns database connections,
model SDK clients or recipe business implementations.
"""

from .graph import build_agent_graph

__all__ = ["build_agent_graph"]
