"""LangGraph 初始化节点。

本模块只服务于 Initializer 节点：从消息和可信 AgentContext 构建本轮问题、
对话历史、饮食约束及初始 Observation。
"""

from collections.abc import Sequence
from safemeal.agent.safety.dietary_safety_service import hard_constraints
from safemeal.modules.dietary.contracts.constraints import DietaryConstraint

from safemeal.agent.contracts.state import (
    AgentState,
    AgentStateUpdate,
    MessageInput,
)
from safemeal.agent.contracts.decisions import Observation
from safemeal.agent.contracts.context import AgentContext
from safemeal.shared.types import to_json_object

from safemeal.agent.runtime.memory.context import build_memory_observations
from safemeal.agent.contracts.menu_planning import initialize_menu_task


# 获取当前问题 读取messages中最后一条信息的内容
# 方法说明：_question_from_messages
# 作用：从历史消息中提取本次模型请求的用户问题。
# 入参：
#   messages（Sequence[MessageInput]）：按顺序组织的历史对话消息。
# 出参：str；最新用户角色消息中的问题文本。
def _question_from_messages(messages: Sequence[MessageInput]) -> str:
    if not messages:
        return ""
    message = messages[-1]
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))


# 方法说明：create_initializer_node
# 作用：构造规范化初始输入和运行预算的图节点。
# 入参：
#   max_iterations（int）：Agent 循环最多执行次数。
#   max_tool_calls（int）：当前请求允许执行的工具调用总数。
#   max_model_tokens（int）：当前请求模型调用的 Token 总量上限。
#   max_model_cost（float）：当前请求模型调用的成本上限。
# 出参：按实现返回；绑定当前依赖的图节点函数，接收图状态并返回局部状态更新。
def create_initializer_node(
    *,
    max_iterations: int,
    max_tool_calls: int,
    max_model_tokens: int,
    max_model_cost: float,
):
    # 方法说明：initialize
    # 作用：初始化 Agent 输入、工具预算与循环状态。
    # 入参：
    #   state（AgentState）：Agent 完整图状态。
    # 出参：AgentStateUpdate；Agent 图节点局部状态更新。
    async def initialize(state: AgentState) -> AgentStateUpdate:
        messages = state.get("messages", [])
        agent_context = AgentContext.model_validate(state.get("agent_context") or {})
        question = _question_from_messages(messages)
        conversation_history = agent_context.conversation_history
        # Workflow 或 Gateway 已解析约束；缺少输入时不能用空约束掩盖安全事实。
        if agent_context.requirements is None:
            raise ValueError("Agent input requires resolved dietary requirements")
        dietary_constraint = (
            DietaryConstraint.model_validate(agent_context.dietary_constraints)
            if agent_context.dietary_constraints is not None
            else hard_constraints(agent_context.requirements)
        )
        agent_context.dietary_constraints = dietary_constraint.model_dump(mode="json")

        initial_observations = build_memory_observations(
            agent_context, dietary_constraint
        )
        menu_execution_plan = None
        menu_task_progress = None
        if (
            agent_context.request_frame is not None
            and agent_context.request_frame.menu_planning is not None
        ):
            plan, progress = initialize_menu_task(
                agent_context.request_frame.menu_planning,
                scenario=agent_context.request_frame.scenario,
            )
            menu_execution_plan = plan.model_dump(mode="json")
            modification = agent_context.context_metadata.get("menu_modification")
            if isinstance(modification, dict):
                progress = progress.model_copy(
                    update={
                        "excluded_recipe_ids": tuple(
                            int(item)
                            for item in modification.get("exclude_recipe_ids", [])
                        ),
                        "excluded_recipe_names": tuple(
                            str(item)
                            for item in modification.get("exclude_recipe_names", [])
                        ),
                    }
                )
            menu_task_progress = progress.model_dump(mode="json")
        task_payload = {
            "intent": agent_context.intent,
            "profile": agent_context.user_profile,
            "requirements": agent_context.requirements.model_dump(mode="json"),
        }
        initial_observations.append(
            Observation(
                call_id="task_context",
                tool_name="task_context",
                purpose="本轮任务与偏好",
                success_criteria="在硬约束内满足本轮要求",
                ok=True,
                has_data=True,
                summary=str(task_payload),
                data=to_json_object(task_payload),
            )
        )
        initial_observations = [
            *initial_observations,
            *(Observation.model_validate(item) for item in agent_context.observations),
        ]
        output: AgentStateUpdate = {
            "intent": None,
            "agent_context": to_json_object(agent_context),
            "question": question,
            "conversation_history": conversation_history,
            "pending_calls": [],
            "tool_results": [],
            "observations": initial_observations,
            "iteration": 0,
            "max_iterations": max_iterations,
            "evidence_sufficient": False,
            "missing_information": [],
            # LangGraph state 只传递 JSON DTO，不直接传递 Pydantic 领域对象。
            "dietary_constraints": to_json_object(dietary_constraint),
            "route": "plan",
            "executed_call_signatures": [],
            "tool_call_count": 0,
            "max_tool_calls": max_tool_calls,
            "max_model_tokens": max_model_tokens,
            "max_model_cost": max_model_cost,
            "budget_exhausted": False,
            "loop_stop_reason": "",
            "direct_answer": "",
            "planning_rationale": "",
            "reflection_rationale": "",
            "sources": [],
            "menu_execution_plan": to_json_object(menu_execution_plan or {}),
            "menu_task_progress": to_json_object(menu_task_progress or {}),
            "tool_trace": [],
        }
        return output

    return initialize


__all__ = ["create_initializer_node"]
