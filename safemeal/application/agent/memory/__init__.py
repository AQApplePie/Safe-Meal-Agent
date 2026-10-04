"""Agent memory/context consumption layer.

Workflow owns persistence and retrieval. This layer only converts the trusted
``AgentContext`` supplied by Workflow into safe observations for the Agent loop.
"""

from .context import build_memory_observations

__all__ = ["build_memory_observations"]
