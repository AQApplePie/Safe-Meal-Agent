"""Agent 图执行用例服务。

本服务封装一次 Agent 调用的输入准备、异常转换和 Trace 回传，
让 HTTP 层不直接感知 Agent 图的内部状态结构。
"""

from safemeal.application.contracts.agent.decisions import DeterministicRouteDecision

import asyncio
import re
from collections.abc import Sequence
from time import perf_counter
from typing import Any, Literal, Mapping, Protocol
from langgraph.types import Command

from loguru import logger

from safemeal.application.contracts.conversation.models import AnswerSource, RouterInfo
from safemeal.application.contracts.agent.state import (
    AgentInputState,
    AgentState,
)
from safemeal.application.observability import (
    AgentTraceRecorder,
    current_request_id,
    trace_json,
    use_trace,
)
from safemeal.application.observability.store import AgentTraceStore
from safemeal.application.observability.cost import ModelPrice
from safemeal.application.contracts.agent.api import AgentProcessResponse, AgentResumeResult
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.shared.types import JsonObject, to_json_object
from safemeal.modules.recipe_catalog.generated_recipe import GeneratedRecipe
from safemeal.application.exceptions import ModelOutputValidationError
from safemeal.application.ports.telemetry import TraceExporter
from collections.abc import Callable


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
    """The durable graph paused before one or more guarded tool calls."""

    def __init__(self, calls: list[object]) -> None:
        super().__init__("human approval is required")
        self.calls = calls


class UnsafeRequestDetector:
    """Detect explicit requests outside the Agent's authority boundary."""

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
        model_name: str = "unknown",
        max_concurrency: int = 8,
        trace_store: AgentTraceStore | None = None,
        model_pricing: Mapping[str, ModelPrice] | None = None,
        cost_currency: str = "CNY",
        unsafe_request_detector: UnsafeRequestDetector | None = None,
        llmops_exporter: TraceExporter | None = None,
        trace_exporter: Callable[[JsonObject], None] | None = None,
    ) -> None:
        """初始化 Agent 执行服务。

        Args:
            agent_graph: 已由 Composition Root 完成装配的 LangGraph 实例。
        """

        self._graph = agent_graph
        self._timeout_seconds = timeout_seconds
        self._model_name = model_name
        self._concurrency = asyncio.Semaphore(max(1, max_concurrency))
        self._trace_store = trace_store
        self._model_pricing = dict(model_pricing or {})
        self._cost_currency = cost_currency
        self._unsafe_request_detector = (
            unsafe_request_detector or UnsafeRequestDetector()
        )
        self._llmops_exporter = llmops_exporter
        self._trace_exporter = trace_exporter

    async def process(
        self,
        message: str,
        session_id: str,
        *,
        context: AgentContext | None = None,
        include_trace: bool = False,
    ) -> AgentProcessResponse:
        """执行一次 Agent 请求。

        Args:
            message: 当前用户问题。
            session_id: 会话 ID。
            context: 已聚合的 Agent 输入上下文。
            include_trace: 是否在响应 metadata 中附加完整 Trace。
        """

        deterministic_route = self._unsafe_request_detector.detect(message)
        if deterministic_route is not None:
            return AgentProcessResponse(
                status="ok",
                message=deterministic_route.message,
                route=deterministic_route.route,
                route_logic="unsafe_request_guard",
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

        # 每个请求创建独立 recorder。ContextVar 会让 Planner、并行 Tool 调用和
        # Responder 自动找到它，同时不会把 Trace 参数污染进业务方法签名。
        recorder = AgentTraceRecorder(
            question=message,
            session_id=session_id,
            model=self._model_name,
            request_id=current_request_id(),
            model_pricing=self._model_pricing,
            cost_currency=self._cost_currency,
        )
        request_started = perf_counter()
        logger.info(
            "agent.run.start run_id={} session_id={} timeout_seconds={} "
            "history_messages={} question_chars={}",
            recorder.trace.run_id,
            session_id,
            self._timeout_seconds,
            len(context.conversation_history),
            len(message),
        )
        with use_trace(recorder):
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
                recorder.finish(
                    status="error" if outcome_status == "error" else "ok",
                    iterations=result.get("iteration", 0),
                    final_answer=answer,
                    sources=[to_json_object(source) for source in sources],
                )
                metadata: JsonObject = {
                    "session_id": session_id,
                    "iteration": result.get("iteration", 0),
                    "tool_call_count": result.get("tool_call_count", 0),
                    "budget_exhausted": result.get("budget_exhausted", False),
                    "loop_stop_reason": result.get("loop_stop_reason", ""),
                    "token_usage": to_json_object(recorder.trace.token_usage),
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
                }
                if generated_recipe is not None:
                    metadata["generated_recipe"] = to_json_object(generated_recipe)
                response = AgentProcessResponse(
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
                logger.info(
                    "agent.run.completed run_id={} session_id={} status={} "
                    "iterations={} sources={} elapsed_ms={:.3f}",
                    recorder.trace.run_id,
                    session_id,
                    outcome_status,
                    recorder.trace.iterations,
                    len(sources),
                    (perf_counter() - request_started) * 1000,
                )
            except HumanApprovalPending as exc:
                recorder.finish(status="ok")
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
                recorder.finish(
                    status="error",
                    error=str(exc),
                )
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
                logger.error(
                    "agent.run.completed run_id={} session_id={} status=error "
                    "elapsed_ms={:.3f} error={}",
                    recorder.trace.run_id,
                    session_id,
                    (perf_counter() - request_started) * 1000,
                    exc,
                )

        trace_payload = trace_json(
            recorder.trace,
            model_pricing=self._model_pricing,
            cost_currency=self._cost_currency,
        )
        response.metadata["cost_usage"] = trace_payload.get("cost_usage", {})
        response.metadata["cost_usage_complete"] = trace_payload.get(
            "cost_usage_complete", False
        )
        if self._trace_store is not None:
            try:
                await asyncio.to_thread(self._trace_store.record, trace_payload)
            except Exception:
                logger.exception(
                    "agent.trace.persistence_failed run_id={}", recorder.trace.run_id
                )
        if self._trace_exporter is not None:
            self._trace_exporter(trace_payload)
        if self._llmops_exporter is not None:
            try:
                await self._llmops_exporter.export(trace_payload)
            except Exception:
                logger.exception(
                    "agent.llmops.export_failed run_id={}", recorder.trace.run_id
                )

        # 完整Trace含工具参数和结果，不能默认暴露给公开Chat API；只有受信任
        # 的内部调用可以显式开启。
        if include_trace:
            response.metadata["trace"] = trace_payload
        return response

    async def resume(self, session_id: str, *, approved: bool) -> AgentResumeResult:
        """Return a resumed draft plus its trusted checkpoint context for review."""
        if self._graph is None:
            return AgentResumeResult(
                response=AgentProcessResponse(
                    status="error",
                    message="Agent LLM is disabled",
                    error_code="feature_unavailable",
                )
            )
        try:
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
