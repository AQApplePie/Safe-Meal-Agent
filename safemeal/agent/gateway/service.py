"""Agent 入口网关服务。

本层封装一次 Agent 调用的输入准备、预算控制、流式事件与异常转换，
让 Workflow 和 HTTP 调用方不直接感知 Agent 图的内部状态结构。
"""

from safemeal.agent.safety.dietary_safety_service import DietarySafetyService
from safemeal.agent.contracts.decisions import DeterministicRouteDecision

import asyncio
import re
from uuid import uuid4
from time import perf_counter
from collections.abc import Sequence
from typing import Any, Literal, Mapping, Protocol
from langgraph.types import Command

from loguru import logger

from safemeal.modules.conversation.contracts.conversation.models import (
    AnswerSource,
    RouterInfo,
)
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


# 类说明（接口类）：AgentGraph
# 作用：Agent 图最小运行接口。
class AgentGraph(Protocol):
    """Agent 图最小运行接口。

    这里不依赖 LangGraph 的具体实现类，只要求装配后的对象支持异步调用。
    """

    # 方法说明：ainvoke
    # 作用：异步调用已装配的图并返回完成后的状态。
    # 入参：
    #   input_state（AgentInputState | Command）：图调用的初始状态。
    #   config（Mapping[str, Any] | None）：图调用或检查点配置；默认值为 None。
    # 出参：AgentState；Agent 完整图状态。
    async def ainvoke(
        self,
        input_state: AgentInputState | Command,
        config: Mapping[str, Any] | None = None,
    ) -> AgentState: ...


# 类说明（异常类）：HumanApprovalPending
# 作用：表示人工审批暂停信号，供上层识别并映射错误响应。
class HumanApprovalPending(Exception):
    """持久化图在受保护工具执行前暂停，等待人工审批。"""

    # 方法说明：__init__
    # 作用：初始化人工审批暂停信号，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   calls（list[object]）：待执行或待审核的工具调用列表。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, calls: list[object]) -> None:
        super().__init__("human approval is required")
        # 实例属性说明：calls
        # 作用：待执行或待审核的工具调用列表。
        self.calls = calls


# 类说明（业务或基础设施实现类）：UnsafeRequestDetector
# 作用：识别明确超出 Agent 权限边界的请求。
class UnsafeRequestDetector:
    """识别明确超出 Agent 权限边界的请求。"""

    # 字段说明：_DESTRUCTIVE_REQUEST
    # 作用：DESTRUCTIVE请求，供该组件初始化及运行控制使用。
    _DESTRUCTIVE_REQUEST = re.compile(
        r"(?:绕过|跳过|无视|规避).{0,12}(?:权限|鉴权|授权|限制)"
        r"|(?:删除|清空|销毁|修改).{0,12}(?:全部|所有).{0,12}"
        r"(?:数据库|数据|菜谱|用户|记录)"
    )
    # 字段说明：_SECRET_EXFILTRATION
    # 作用：签名密钥EXFILTRATION，供该组件初始化及运行控制使用。
    _SECRET_EXFILTRATION = re.compile(
        r"(?:输出|显示|泄露|透露|给我|打印|导出).{0,16}"
        r"(?:系统提示词|隐藏提示词|其他用户.{0,6}(?:隐私|数据)|密钥|密码|令牌)"
    )

    # 方法说明：detect
    # 作用：识别请求中不允许执行的越权或危险操作意图。
    # 入参：
    #   message（str）：本轮用户消息或问题文本。
    # 出参：DeterministicRouteDecision | None；规则路由判定或None（未取得结果）。
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


# 类说明（业务或基础设施实现类）：AgentExecutionService
# 作用：负责调用 Agent 图并把运行状态整理成应用层结果。
class AgentExecutionService:
    """负责调用 Agent 图并把运行状态整理成应用层结果。"""

    # 方法说明：__init__
    # 作用：初始化Agent 图执行服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   agent_graph（AgentGraph | None）：已编译的 Agent 执行图。
    #   timeout_seconds（float）：操作超时上限，单位秒；默认值为 300.0。
    #   max_concurrency（int）：同时执行的最大任务数；默认值为 8。
    #   model_pricing（Mapping[str, ModelPrice] | None）：模型输入输出及缓存用量的价格配置；默认值为
    # None。
    #   unsafe_request_detector（UnsafeRequestDetector | None）：越权或危险请求检测器；默认值为
    # None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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

        # 实例属性说明：_graph
        # 作用：图执行对象或图数据库封装。
        self._graph = agent_graph
        # 实例属性说明：_timeout_seconds
        # 作用：操作超时上限，单位秒。
        self._timeout_seconds = timeout_seconds
        # 实例属性说明：_concurrency
        # 作用：控制同时执行任务或工具数量的异步信号量。
        self._concurrency = asyncio.Semaphore(max(1, max_concurrency))
        # 实例属性说明：_model_pricing
        # 作用：模型输入输出及缓存用量的价格配置。
        self._model_pricing = dict(model_pricing or {})
        # 实例属性说明：_unsafe_request_detector
        # 作用：越权或危险请求检测器。
        self._unsafe_request_detector = (
            unsafe_request_detector or UnsafeRequestDetector()
        )

    # 方法说明：process
    # 作用：执行一次 Agent 请求。
    # 入参：
    #   message（str）：本轮用户消息或问题文本。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   context（AgentContext | None）：本轮执行上下文；默认值为 None。
    # 出参：AgentProcessResponse；Agent 内部处理响应。
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

        context = (
            context.model_copy(deep=True) if context is not None else AgentContext()
        )
        if context.requirements is None:
            context.requirements = DietarySafetyService().resolve_constraints(
                message, context
            )
        input_state: AgentInputState = {
            "messages": [
                *context.conversation_history,
                {"role": "user", "content": message},
            ],
            "agent_context": to_json_object(context),
        }

        with use_model_budget(self._model_pricing):
            try:
                result = await self._invoke(input_state, session_id)
                if result.get("__interrupt__") or result.get("pending_calls"):
                    raise HumanApprovalPending(list(result["pending_calls"]))
                response = self._build_response(result, context, session_id)
            except HumanApprovalPending as exc:
                response = AgentProcessResponse(
                    status="degraded",
                    message="操作已暂停，等待人工确认后继续执行。",
                    route="human_approval",
                    route_logic="langgraph_interrupt",
                    metadata={
                        "session_id": session_id,
                        "approval_required": True,
                        "approval_state": "pending",
                        "approval_id": str(uuid4()),
                        "pending_calls": [to_json_object(call) for call in exc.calls],
                    },
                    error_code="human_approval_required",
                )
            except Exception as exc:
                logger.exception("Agent query failed: {}", exc)
                response = AgentProcessResponse(
                    status="error",
                    message="抱歉，处理您的请求时出现了错误。请稍后重试。",
                    route="error",
                    route_logic="agent execution failed",
                    sources=[],
                    metadata={"session_id": session_id},
                    error_code=self._execution_error_code(exc),
                )

        return response

    # 方法说明：resume
    # 作用：恢复暂停任务，并返回草稿及发布复核所需的可信上下文。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   approved（bool）：用户是否明确同意执行当前待审批操作。
    # 出参：AgentResumeResult；Agent 审批恢复结果。
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
        started = perf_counter()
        try:
            get_state = getattr(self._graph, "aget_state", None)
            if get_state is not None:
                snapshot = await asyncio.wait_for(
                    get_state({"configurable": {"thread_id": session_id}}),
                    timeout=self._timeout_seconds,
                )
                if not any(task.interrupts for task in snapshot.tasks):
                    return AgentResumeResult(
                        response=AgentProcessResponse(
                            status="error",
                            message="待审批检查点不存在或已经恢复，不能再次执行。",
                            error_code="approval_checkpoint_unavailable",
                        )
                    )
            with use_model_budget(self._model_pricing):
                result = await self._invoke(
                    Command(resume={"approved": approved}),
                    session_id,
                    timeout_seconds=max(
                        0.001, self._timeout_seconds - (perf_counter() - started)
                    ),
                )
            context = AgentContext.model_validate(result.get("agent_context") or {})
            context.dietary_constraints = result.get("dietary_constraints")
            question = result.get("question", "")
            if result.get("__interrupt__") or result.get("pending_calls"):
                response = AgentProcessResponse(
                    status="degraded",
                    message="仍有操作等待人工确认。",
                    route="human_approval",
                    metadata={
                        "approval_required": True,
                        "session_id": session_id,
                        "approval_id": str(uuid4()),
                        "pending_calls": [
                            to_json_object(call)
                            for call in result.get("pending_calls", [])
                        ],
                    },
                )
            else:
                response = self._build_response(result, context, session_id)
                response.route = "human_approval_resumed"
                response.metadata["approved"] = approved
            return AgentResumeResult(
                response=response, message=question, context=context
            )
        except Exception as exc:
            logger.exception("agent.resume.failed session_id={}", session_id)
            return AgentResumeResult(
                response=AgentProcessResponse(
                    status="error",
                    message="恢复 Agent 执行失败，请确认会话仍处于待审批状态。",
                    route="error",
                    error_code=self._execution_error_code(exc),
                )
            )

    # 方法说明：_invoke
    # 作用：整个调用（包括等待容量）共享相同超时与并发边界。
    # 入参：
    #   input_state（AgentInputState | Command）：图调用的初始状态。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   timeout_seconds（float | None）：操作超时上限，单位秒；默认值为 None。
    # 出参：AgentState；Agent 完整图状态。
    async def _invoke(
        self,
        input_state: AgentInputState | Command,
        session_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentState:
        """整个调用（包括等待容量）共享相同超时与并发边界。"""
        graph = self._graph
        assert graph is not None

        # 方法说明：invoke_with_capacity
        # 作用：在资源容量限制内执行图调用，避免无限并发。
        # 入参：
        #   无显式入参。
        # 出参：AgentState；Agent 完整图状态。
        async def invoke_with_capacity() -> AgentState:
            async with self._concurrency:
                return await graph.ainvoke(
                    input_state, config={"configurable": {"thread_id": session_id}}
                )

        return await asyncio.wait_for(
            invoke_with_capacity(),
            timeout=self._timeout_seconds
            if timeout_seconds is None
            else timeout_seconds,
        )

    # 方法说明：_execution_error_code
    # 作用：将执行异常映射为对外稳定的错误码。
    # 入参：
    #   exc（Exception）：当前捕获或退出上下文时传入的异常对象。
    # 出参：str；可向接口调用方返回的稳定错误码。
    @staticmethod
    def _execution_error_code(exc: Exception) -> str:
        return (
            "agent_timeout"
            if isinstance(exc, TimeoutError)
            else "agent_execution_failed"
        )

    # 方法说明：_build_response
    # 作用：首次执行和恢复共同使用证据分类、菜单状态及输出契约。
    # 入参：
    #   result（AgentState）：Agent 完整图状态。
    #   context（AgentContext）：本轮执行上下文。
    #   session_id（str）：聊天会话或图检查点线程标识。
    # 出参：AgentProcessResponse；Agent 内部处理响应。
    def _build_response(
        self, result: AgentState, context: AgentContext, session_id: str
    ) -> AgentProcessResponse:
        """首次执行和恢复共同使用证据分类、菜单状态及输出契约。"""
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
                generated_recipe = GeneratedRecipe.model_validate(observation.data)
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
            item for item in actual_tool_observations if item.ok and item.has_data
        ]
        failed_evidence = [item for item in actual_tool_observations if not item.ok]
        outcome_status: Literal["ok", "degraded", "error"]
        if failed_core and not successful_evidence:
            outcome_status = "error"
            outcome_error_code = failed_core[0].error_code or "recipe_data_unavailable"
            answer = "抱歉，当前无法读取可靠的菜谱数据，请稍后重试。"
            sources = []
        elif failed_evidence:
            outcome_status = "degraded"
            outcome_error_code = "partial_evidence_unavailable"
        elif actual_tool_observations and not result.get("evidence_sufficient", False):
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
                for index, name in enumerate(dict.fromkeys(rendered_names), start=1)
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
            current_plan.get("required") if isinstance(current_plan, dict) else None
        )
        if isinstance(current_required, dict) and current_required:
            if isinstance(previous_active, dict) and isinstance(modification, dict):
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
        return AgentProcessResponse(
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

    # 方法说明：_response_text
    # 作用：从模型响应中提取可用文本内容。
    # 入参：
    #   result（AgentState）：Agent 完整图状态。
    # 出参：str；从模型或图结果中取出的回答文本。
    @staticmethod
    def _response_text(result: AgentState) -> str:
        messages = result.get("messages") or []
        if not messages:
            return ""
        last_message = messages[-1]
        if isinstance(last_message, dict):
            return str(last_message.get("content", ""))
        return str(getattr(last_message, "content", ""))

    # 方法说明：_normalize_sources
    # 作用：去重并转换答案来源，保留可追踪的证据标识。
    # 入参：
    #   sources（Sequence[AnswerSource | JsonObject | str] |
    # None）：当前答案或上下文的证据来源集合。
    # 出参：list[AnswerSource]；答案来源与引用片段的集合。
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

    # 方法说明：_normalize_router
    # 作用：把 LangGraph 状态中的路由信息规整为稳定模型。
    # 入参：
    #   router（RouterInfo | JsonObject | None）：HTTP 路由对象或回答路由说明。
    # 出参：RouterInfo；最终回答路由说明。
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
