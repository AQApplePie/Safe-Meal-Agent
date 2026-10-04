"""Agent aggregation layer.

This layer merges observations, attributes sources and creates the final Agent
draft. Workflow still owns the independent business safety gate.
"""

from .responder import create_responder_node
from .sources import collect_answer_sources

__all__ = ["collect_answer_sources", "create_responder_node"]
