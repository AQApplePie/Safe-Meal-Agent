"""把可信上下文转换为智能体可消费的观察。"""

from .observations import (
    build_dietary_context_observation,
    build_user_memory_observation,
)
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.contracts.decisions import Observation
from safemeal.modules.dietary.contracts.constraints import DietaryConstraint


def build_memory_observations(
    context: AgentContext,
    dietary_constraint: DietaryConstraint,
) -> list[Observation]:

    candidates = (
        build_user_memory_observation(context.user_memories),
        build_dietary_context_observation(dietary_constraint),
    )
    return [item for item in candidates if item is not None]


__all__ = ["build_memory_observations"]
