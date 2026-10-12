"""把可信上下文转换为智能体可消费的观察。"""

from .observations import (
    build_dietary_context_observation,
    build_user_memory_observation,
)
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.contracts.decisions import Observation
from safemeal.modules.dietary.contracts.constraints import DietaryConstraint


# 方法说明：build_memory_observations
# 作用：将选中的长期记忆转换为规划与回答所需的观察信息。
# 入参：
#   context（AgentContext）：本轮执行上下文。
#   dietary_constraint（DietaryConstraint）：当前饮食硬约束。
# 出参：list[Observation]；标准化工具观察的集合。
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
