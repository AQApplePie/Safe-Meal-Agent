"""Agent 入口网关服务。

本层封装一次 Agent 调用的输入准备、预算控制、流式事件与异常转换，
让 Workflow 和 HTTP 调用方不直接感知 Agent 图的内部状态结构。
"""

from safemeal.agent.contracts.decisions import DeterministicRouteDecision

import asyncio
import re
from collections.abc import Sequence
from typing import Any, Literal, Mapping, Protocol
from langgraph.types import Command

from loguru import logger

from safemeal.modules.conversation.contracts.conversation.models import AnswerSource, RouterInfo
from safemeal.agent.contracts.state import (
    AgentInputState,
    AgentState,
)
from safemeal.agent.runtime.budget import use_model_budget
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.agent.contracts.budget import ModelPrice
from safemeal.agent.contracts.api import (
    AgentProcessResponse,
    AgentResumeResult,
)
from safemeal.agent.contracts.context import AgentContext
from safemeal.shared.types import JsonObject, to_json_object
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe
from safemeal.shared.exceptions import ModelOutputValidationError
from safemeal.agent.runtime.orchestration.nodes.reflector.assessment import (
    recommendation_completion,
)
from safemeal.agent.context.active_menu import (
    merge_active_menu_replacement,
)


class AgentGraph(Protocol):
    """Agent 图最小运行接口。

    这里不依赖 LangGraph 的具体实现类，只要求装配后的对象支持异步调用。
    """

    async def ainvoke(
        self,
        input_state: AgentInputState | Command,
        config: Mapping[str, Any] | None = None,
    ) -> AgentState: ...


class HumanApprovalPending(Exception):
    """持久化图在受保护工具执行前暂停，等待人工审批。"""

    def __init__(self, calls: list[object]) -> None:
        super().__init__("human approval is required")
        self.calls = calls


class UnsafeRequestDetector:
    """识别明确超出 Agent 权限边界的请求。"""

    _DESTRUCTIVE_REQUEST = re.compile(
        r"(?:绕过|跳过|无视|规避).{0,12}(?:权限|鉴权|授权|限制)"
        r"|(?:删除|清空|销毁|修改).{0,12}(?:全部|所有).{0,12}"
        r"(?:数据库|数据|菜谱|用户|记录)"
    )
    _SECRET_EXFILTRATION = re.compile(
        r"(?:输出|显示|泄露|透露|给我|打印|导出).{0,16}"
        r"(?:系统提示词|隐藏提示词|其他用户.{0,6}(?:隐私|数据)|密钥|密码|令牌)"
    )

    def detect(self, message: str) -> DeterministicRouteDecision | None:
        normalized = " ".join(message.strip().split())
        if self._DESTRUCTIVE_REQUEST.search(normalized):
            return DeterministicRouteDecision(
                route="authorization_guard",
                message=(
                    "不能执行该请求：本服务无权绕过鉴权、提升权限，或删除/修改"
                    "受保护的数据。你可以查询菜谱、获取饮食建议，或操作自己有权"
                    "访问的会话数据。"
                ),
                reason="privilege_escalation_or_destructive_action",
            )
        if self._SECRET_EXFILTRATION.search(normalized):
            return DeterministicRouteDecision(
                route="authorization_guard",
                message=(
                    "不能提供系统提示词、密钥或其他用户的隐私数据。"
                    "我只能处理当前已授权上下文中的菜谱与饮食安全请求。"
                ),
                reason="secret_or_cross_user_data_exfiltration",
            )
        return None


class AgentExecutionService:
    """负责调用 Agent 图并把运行状态整理成应用层结果。"""

    def __init__(
        self,
        agent_graph: AgentGraph | None,
        *,
        timeout_seconds: float = 300.0,
        max_concurrency: int = 8,
        model_pricing: Mapping[str, ModelPrice] | None = None,
        unsafe_request_detector: UnsafeRequestDetector | None = None,
    ) -> None:
        """初始化 Agent 执行服务。

        Args:
            agent_graph: 已由 Composition Root 完成装配的 LangGraph 实例。
        """

        self._graph = agent_graph
        self._timeout_seconds = timeout_seconds
        self._concurrency = asyncio.Semaphore(max(1, max_concurrency))
        self._model_pricing = dict(model_pricing or {})
        self._unsafe_request_detector = (
            unsafe_request_detector or UnsafeRequestDetector()
        )

    async def process(
        self,
        message: str,
        session_id: str,
        *,
        context: AgentContext | None = None,
    ) -> AgentProcessResponse:
        """执行一次 Agent 请求。

        Args:
            message: 当前用户问题。
            session_id: 会话 ID。
            context: 已聚合的 Agent 输入上下文。
        """

        deterministic_route = self._unsafe_request_detector.detect(message)
        if deterministic_route is not None:
            return AgentProcessResponse(
                status="ok",
                message=deterministic_route.message,
                route=deterministic_route.route,
                route_logic="unsafe_request_guard",
                intent=IntentDecision(
                    kind="out_of_scope", reason="unsafe_request_guard"
                ),
                metadata={
                    "deterministic": True,
                    "guard_reason": deterministic_route.reason,
                },
            )

        graph = self._graph
        if graph is None:
            return AgentProcessResponse(
                status="error",
                message="Agent LLM is disabled",
                route="semantic_planner",
                route_logic="llm_required",
                error_code="feature_unavailable",
            )

        context = context or AgentContext()
        input_state: AgentInputState = {
            "messages": [
                *context.conversation_history,
                {"role": "user", "content": message},
            ],
            "agent_context": to_json_object(context),
        }

        with use_model_budget(self._model_pricing):
            try:

                async def invoke_with_capacity() -> AgentState:
                    async with self._concurrency:
                        return await graph.ainvoke(
                            input_state,
                            config={"configurable": {"thread_id": session_id}},
                        )

                result = await asyncio.wait_for(
                    invoke_with_capacity(),
                    timeout=self._timeout_seconds,
                )
                if result.get("__interrupt__") or result.get("pending_calls"):
                    raise HumanApprovalPending(list(result["pending_calls"]))
                router_info = self._normalize_router(result.get("router"))
                answer = self._response_text(result)
                if not answer.strip():
                    raise RuntimeError("Agent graph returned an empty final answer")
                sources = self._normalize_sources(result.get("sources", []))
                observations = result.get("observations", [])
                generated_recipe: GeneratedRecipe | None = None
                for observation in reversed(observations):
                    if observation.tool_name != "generate_recipe" or not observation.ok:
                        continue
                    try:
                        generated_recipe = GeneratedRecipe.model_validate(
                            observation.data
                        )
                    except Exception as exc:
                        raise ModelOutputValidationError(
                            "generate_recipe returned an invalid payload"
                        ) from exc
                    break
                actual_tool_observations = [
                    item
                    for item in observations
                    if item.tool_name
                    not in {
                        "dietary_context",
                        "dietary_safety_filter",
                        "user_memory_context",
                        "task_context",
                    }
                ]
                core_recipe_tools = {
                    "search_recipes",
                    "get_recipe",
                    "recommend_recipes",
                    "generate_recipe",
                }
                failed_core = [
                    item
                    for item in actual_tool_observations
                    if item.tool_name in core_recipe_tools and not item.ok
                ]
                successful_evidence = [
                    item
                    for item in actual_tool_observations
                    if item.ok and item.has_data
                ]
                failed_evidence = [
                    item for item in actual_tool_observations if not item.ok
                ]
                outcome_status: Literal["ok", "degraded", "error"]
                if failed_core and not successful_evidence:
                    outcome_status = "error"
                    outcome_error_code = (
                        failed_core[0].error_code or "recipe_data_unavailable"
                    )
                    answer = "抱歉，当前无法读取可靠的菜谱数据，请稍后重试。"
                    sources = []
                elif failed_evidence:
                    outcome_status = "degraded"
                    outcome_error_code = "partial_evidence_unavailable"
                elif actual_tool_observations and not result.get(
                    "evidence_sufficient", False
                ):
                    outcome_status = "degraded"
                    outcome_error_code = "insufficient_evidence"
                else:
                    outcome_status = "ok"
                    outcome_error_code = None
                metadata: JsonObject = {
                    "session_id": session_id,
                    "iteration": result.get("iteration", 0),
                    "tool_call_count": result.get("tool_call_count", 0),
                    "budget_exhausted": result.get("budget_exhausted", False),
                    "loop_stop_reason": result.get("loop_stop_reason", ""),
                    "evidence_sufficient": result.get("evidence_sufficient", False),
                    "missing_information": result.get("missing_information", []),
                    "user_memory_count": len(context.user_memories),
                    "episodic_memory_count": len(context.episodic_memories),
                    "has_user_profile": context.user_profile is not None,
                    "observations": [
                        {
                            "tools": item.tool_name,
                            "ok": item.ok,
                            "status": item.status,
                            "error_code": item.error_code,
                            "has_data": item.has_data,
                        }
                        for item in observations
                    ],
                    "agent_status": outcome_status,
                    "tool_trace": result.get("tool_trace", []),
                    "request_frame": (
                        to_json_object(context.request_frame)
                        if context.request_frame is not None
                        else None
                    ),
                    "resolved_constraints": (
                        to_json_object(context.requirements)
                        if context.requirements is not None
                        else {}
                    ),
                    "reflect": {
                        "rationale": result.get("reflection_rationale", ""),
                        "evidence_sufficient": result.get("evidence_sufficient", False),
                        "missing_information": result.get("missing_information", []),
                    },
                }
                rendered_names = re.findall(r"「([^」]{1,40})」", answer)
                if rendered_names:
                    # 保存真实展示顺序，供审计和下一轮结构化引用使用。
                    metadata["rendered_recipe_refs"] = [
                        {"position": index, "name": name}
                        for index, name in enumerate(
                            dict.fromkeys(rendered_names), start=1
                        )
                    ]
                understanding_keys = {
                    "request_understanding_backend",
                    "request_understanding_confidence",
                    "understanding_status",
                    "request_tasks",
                    "context_needs",
                    "fallback_used",
                    "loaded_context_types",
                }
                for key in understanding_keys:
                    if key in context.context_metadata:
                        metadata[key] = context.context_metadata[key]
                if generated_recipe is not None:
                    metadata["generated_recipe"] = to_json_object(generated_recipe)
                # Workflow 发布复核只接收最终入选菜单，不接收工具的过采样候选。
                if result.get("menu_execution_plan") is not None:
                    metadata["menu_execution_plan"] = to_json_object(
                        result["menu_execution_plan"]
                    )
                if result.get("menu_task_progress") is not None:
                    metadata["menu_task_progress"] = to_json_object(
                        result["menu_task_progress"]
                    )
                previous_active = context.context_metadata.get("active_menu")
                modification = context.context_metadata.get("menu_modification")
                current_plan = metadata.get("menu_execution_plan")
                current_required = (
                    current_plan.get("required")
                    if isinstance(current_plan, dict)
                    else None
                )
                if isinstance(current_required, dict) and current_required:
                    if isinstance(previous_active, dict) and isinstance(
                        modification, dict
                    ):
                        metadata["active_menu"] = merge_active_menu_replacement(
                            previous_active,
                            metadata["menu_execution_plan"],
                            metadata["menu_task_progress"],
                            modification,
                        )
                        metadata["menu_modification"] = modification
                    else:
                        metadata["active_menu"] = {
                            "plan": metadata["menu_execution_plan"],
                            "progress": metadata["menu_task_progress"],
                        }
                elif isinstance(previous_active, dict) and previous_active:
                    # 非菜单轮次可以读取活动菜单，但不能用空计划覆盖它。
                    metadata["active_menu"] = to_json_object(previous_active)
                completion = recommendation_completion(observations)
                if completion is not None:
                    requested, fulfilled, complete = completion
                    metadata["recommendation_completion"] = {
                        "requested": requested,
                        "fulfilled": fulfilled,
                        "complete": complete,
                    }
                response = AgentProcessResponse(
                    intent=result.get("intent"),
                    status=outcome_status,
                    message=answer,
                    route=router_info.type,
                    route_logic="agent-tools-loop",
                    sources=sources,
                    metadata=metadata,
                    error_code=outcome_error_code,
                    recipe=generated_recipe,
                    evidence=[item.model_dump(mode="json") for item in observations],
                )
            except HumanApprovalPending as exc:
                response = AgentProcessResponse(
                    status="degraded",
                    message="操作已暂停，等待人工确认后继续执行。",
                    route="human_approval",
                    route_logic="langgraph_interrupt",
                    metadata={
                        "session_id": session_id,
                        "approval_required": True,
                        "pending_calls": [to_json_object(call) for call in exc.calls],
                    },
                    error_code="human_approval_required",
                )
            except Exception as exc:
                logger.exception("Agent query failed: {}", exc)
                error_code = (
                    "agent_timeout"
                    if isinstance(exc, (asyncio.TimeoutError, TimeoutError))
                    else "agent_execution_failed"
                )
                response = AgentProcessResponse(
                    status="error",
                    message="抱歉，处理您的请求时出现了错误。请稍后重试。",
                    route="error",
                    route_logic="agent execution failed",
                    sources=[],
                    metadata={"session_id": session_id},
                    error_code=error_code,
                )

        return response

    async def resume(self, session_id: str, *, approved: bool) -> AgentResumeResult:
        """恢复暂停任务，并返回草稿及发布复核所需的可信上下文。"""
        if self._graph is None:
            return AgentResumeResult(
                response=AgentProcessResponse(
                    status="error",
                    message="Agent LLM is disabled",
                    error_code="feature_unavailable",
                )
            )
        try:
            with use_model_budget(self._model_pricing):
                async with self._concurrency:
                    result = await asyncio.wait_for(
                        self._graph.ainvoke(
                            Command(resume={"approved": approved}),
                            config={"configurable": {"thread_id": session_id}},
                        ),
                        timeout=self._timeout_seconds,
                    )
            context = AgentContext.model_validate(result.get("agent_context") or {})
            context.dietary_constraints = result.get("dietary_constraints")
            question = result.get("question", "")
            if result.get("__interrupt__") or result.get("pending_calls"):
                response = AgentProcessResponse(
                    status="degraded",
                    message="仍有操作等待人工确认。",
                    route="human_approval",
                    metadata={"approval_required": True, "session_id": session_id},
                )
            else:
                observations = result.get("observations", [])
                generated = next(
                    (
                        GeneratedRecipe.model_validate(item.data)
                        for item in reversed(observations)
                        if item.tool_name == "generate_recipe" and item.ok
                    ),
                    None,
                )
                response = AgentProcessResponse(
                    intent=result.get("intent"),
                    message=self._response_text(result),
                    route="human_approval_resumed",
                    recipe=generated,
                    metadata={"session_id": session_id, "approved": approved},
                    evidence=[item.model_dump(mode="json") for item in observations],
                    sources=self._normalize_sources(result.get("sources", [])),
                )
            return AgentResumeResult(
                response=response, message=question, context=context
            )
        except Exception:
            logger.exception("agent.resume.failed session_id={}", session_id)
            return AgentResumeResult(
                response=AgentProcessResponse(
                    status="error",
                    message="恢复 Agent 执行失败，请确认会话仍处于待审批状态。",
                    route="error",
                    error_code="agent_execution_failed",
                )
            )

    @staticmethod
    def _response_text(result: AgentState) -> str:
        messages = result.get("messages") or []
        if not messages:
            return ""
        last_message = messages[-1]
        if isinstance(last_message, dict):
            return str(last_message.get("content", ""))
        return str(getattr(last_message, "content", ""))

    @staticmethod
    def _normalize_sources(
        sources: Sequence[AnswerSource | JsonObject | str] | None,
    ) -> list[AnswerSource]:
        if not sources:
            return []
        normalized: list[AnswerSource] = []
        for source in sources:
            if isinstance(source, str):
                normalized.append(AnswerSource(source=source))
            elif isinstance(source, AnswerSource):
                normalized.append(source)
            elif isinstance(source, dict):
                normalized.append(AnswerSource.model_validate(source))
        return normalized

    @staticmethod
    def _normalize_router(router: RouterInfo | JsonObject | None) -> RouterInfo:
        """把 LangGraph 状态中的路由信息规整为稳定模型。"""

        if isinstance(router, RouterInfo):
            return router
        if isinstance(router, dict):
            return RouterInfo(
                type=str(router.get("type", "")),
                logic=str(router.get("logic", "")),
            )
        return RouterInfo(type="", logic="")
