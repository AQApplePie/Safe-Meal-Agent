"""Convert trusted context into bounded observations consumed by the Agent.

No database, Redis or vector store is accessed here. Keeping this function pure
prevents the Agent from bypassing Workflow ownership and makes memory behaviour
straightforward to unit test.
"""

from .observations import (
    build_dietary_context_observation,
    build_user_memory_observation,
)
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.contracts.dietary_safety.constraints import DietaryConstraint


def build_memory_observations(
    context: AgentContext,
    dietary_constraint: DietaryConstraint,
) -> list[Observation]:
    """Build safe observations for structured memories and hard constraints."""

    candidates = (
        build_user_memory_observation(context.user_memories),
        build_dietary_context_observation(dietary_constraint),
    )
    return [item for item in candidates if item is not None]


__all__ = ["build_memory_observations"]
