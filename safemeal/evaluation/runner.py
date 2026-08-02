"""Run the benchmark directly against the current modular-monolith Agent."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter
from typing import Protocol, Sequence

from safemeal.application.agents.graph import build_agent_graph
from safemeal.application.agents.prompts import DEFAULT_PROMPT_BUNDLE, PromptBundle
from safemeal.application.use_cases.agent.graph_runner_service import (
    AgentGraphRunnerService,
)
from safemeal.application.use_cases.recipes import RecipeGenerationService
from safemeal.bootstrap.container import AppContainer
from safemeal.config.settings import settings
from safemeal.evaluation.judge import AnswerJudge, OpenAICompatibleJudge
from safemeal.evaluation.metrics import apply_judge, evaluate_case, summarize_results
from safemeal.evaluation.models import (
    EvaluationCase,
    EvaluationProfile,
    EvaluationReport,
    EvaluationRunConfig,
)
from safemeal.evaluation.paths import atomic_write, result_path
from safemeal.infrastructure.llm.decision_engine import OpenAIDecisionEngine
from safemeal.infrastructure.tools.registry.factory import create_tool_registry
from safemeal.infrastructure.tools.registry.local_registry import LocalToolRegistry
from safemeal.application.contracts.agent import AgentProcessResponse
from safemeal.shared.contracts.agent_context import AgentContext


class AgentProcessor(Protocol):
    async def process(
        self,
        message: str,
        session_id: str,
        *,
        context: AgentContext | None = None,
        include_trace: bool = False,
    ) -> AgentProcessResponse: ...


def _api_key(env_name: str) -> str:
    configured = {
        "LLM_API_KEY": settings.LLM_API_KEY,
        "OPENAI_API_KEY": settings.OPENAI_API_KEY,
        "DASHSCOPE_API_KEY": settings.LLM_API_KEY,
    }
    return (os.getenv(env_name) or configured.get(env_name) or "").strip()


def _prompt_bundle(profile: EvaluationProfile) -> PromptBundle:
    prompts = profile.prompts
    return PromptBundle(
        version=prompts.version,
        planner=prompts.planner or DEFAULT_PROMPT_BUNDLE.planner,
        reflection=prompts.reflection or DEFAULT_PROMPT_BUNDLE.reflection,
        answer=prompts.answer or DEFAULT_PROMPT_BUNDLE.answer,
        recipe_generation=prompts.recipe_generation
        or DEFAULT_PROMPT_BUNDLE.recipe_generation,
    )


def build_evaluation_agent(
    profile: EvaluationProfile,
    container: AppContainer,
) -> AgentGraphRunnerService:
    """Build an isolated Agent so profile changes cannot mutate production singletons."""

    model = profile.model
    engine = OpenAIDecisionEngine(
        model=model.model,
        api_key=_api_key(model.api_key_env),
        base_url=model.base_url,
        prompts=_prompt_bundle(profile),
        decision_temperature=model.decision_temperature,
        answer_temperature=model.answer_temperature,
    )
    enabled = profile.tools.enabled_tools
    if enabled is None:
        enabled = [
            "search_recipes",
            "get_recipe",
            "recommend_recipes",
            "generate_recipe",
        ]
        if settings.ENABLE_MILVUS and settings.ENABLE_EMBEDDINGS:
            enabled.append("milvus_vector_search")
        if settings.ENABLE_NEO4J:
            enabled.append("dietary_safe_recipe_query")
    runtime = create_tool_registry(
        knowledge_provider=container.get_knowledge_service,
        recipe_service=container.get_recipe_service(),
        recipe_generation_service=RecipeGenerationService(engine),
        enabled_tools=enabled,
        timeout_seconds=profile.tools.timeout_seconds,
    )
    graph = build_agent_graph(
        engine=engine,
        registry=LocalToolRegistry(runtime),
        max_iterations=profile.tools.max_iterations,
        history_messages=settings.AGENT_HISTORY_MESSAGES,
        max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
        max_model_tokens=settings.AGENT_MAX_MODEL_TOKENS,
        max_model_cost=settings.AGENT_MAX_COST,
    )
    return AgentGraphRunnerService(
        graph,
        timeout_seconds=settings.AGENT_TIMEOUT,
        model_name=model.model,
        max_concurrency=1,
    )


class EvaluationRunner:
    def __init__(
        self,
        profile: EvaluationProfile,
        *,
        service: AgentProcessor | None = None,
        judge: AnswerJudge | None = None,
        enable_judge: bool | None = None,
    ) -> None:
        self.profile = profile
        self._service = service
        self._judge = judge
        self._enable_judge = (
            profile.judge.enabled if enable_judge is None else enable_judge
        )
        self._container: AppContainer | None = None

    def _ensure_runtime(self) -> AgentProcessor:
        if self._service is None:
            self._container = AppContainer()
            self._service = build_evaluation_agent(self.profile, self._container)
        if self._enable_judge and self._judge is None:
            self._judge = OpenAICompatibleJudge(
                self.profile.judge,
                self.profile.model,
                fallback_api_key=_api_key(self.profile.judge.api_key_env),
            )
        return self._service

    async def run(
        self,
        cases: Sequence[EvaluationCase],
        *,
        dataset_path: Path,
        profile_path: Path,
    ) -> EvaluationReport:
        service = self._ensure_runtime()
        results = []
        try:
            for case in cases:
                started = perf_counter()
                try:
                    response = await service.process(
                        case.question,
                        f"eval-{case.id}",
                        context=case.context,
                        include_trace=True,
                    )
                except Exception as exc:
                    response = AgentProcessResponse(
                        status="error",
                        message="评测执行异常。",
                        route="error",
                        metadata={
                            "trace": {
                                "status": "error",
                                "error": str(exc),
                                "total_latency_ms": round(
                                    (perf_counter() - started) * 1000, 3
                                ),
                                "tool_calls": [],
                            }
                        },
                        error_code="evaluation_execution_failed",
                    )
                result = evaluate_case(case, response)
                if self._judge is not None:
                    apply_judge(result, await self._judge.evaluate(case, result))
                results.append(result)
        finally:
            if self._container is not None:
                await self._container.shutdown()
        summary = summarize_results(results)
        config = EvaluationRunConfig(
            dataset=str(dataset_path),
            profile=str(profile_path),
            model=self.profile.model.model,
            prompt_version=self.profile.prompts.version,
            tool_strategy=self.profile.tools.strategy,
            judge_model=(
                (self.profile.judge.model or self.profile.model.model)
                if self._enable_judge
                else None
            ),
            selected_cases=len(cases),
        )
        return EvaluationReport(
            config=config,
            summary=summary,
            results=results,
        )


def write_report(report: EvaluationReport, path: str | Path) -> Path:
    resolved = result_path(path, suffixes={".json"})
    return atomic_write(resolved, report.model_dump_json(indent=2))


__all__ = [
    "EvaluationRunner",
    "build_evaluation_agent",
    "write_report",
]
