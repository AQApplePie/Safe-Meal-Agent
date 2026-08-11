"""Run the benchmark directly against the current modular-monolith Agent."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter
from typing import Sequence

from safemeal.application.agent.graph import build_agent_graph
from safemeal.application.agent.utils.prompts import DEFAULT_PROMPT_BUNDLE, PromptBundle
from safemeal.application.agent.execution_service import (
    AgentExecutionService,
)
from safemeal.application.contracts.agent import AgentProcessResponse
from safemeal.application.use_cases.recipes import RecipeGenerationService
from safemeal.bootstrap.application_container import ApplicationContainer
from safemeal.config.settings import settings
from safemeal.evaluation.llm_judge import AnswerJudge, OpenAICompatibleJudge
from safemeal.evaluation.scoring import apply_judge, evaluate_case, summarize_results
from safemeal.evaluation.evaluation_contracts import (
    EvaluationCase,
    EvaluationProfile,
    EvaluationReport,
    EvaluationRunConfig,
)
from safemeal.infrastructure.llm.openai_language_model_gateway import (
    OpenAILanguageModelGateway,
)
from safemeal.infrastructure.tools.tool_executor_factory import build_tool_executor


_MYSQL_TOOLS = {"search_recipes", "get_recipe", "recommend_recipes"}
_CONTEXT_FEATURES = {"user_memory", "conversation_memory"}


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


def _enabled_tools(profile: EvaluationProfile) -> list[str]:
    configured = profile.tools.enabled_tools
    if configured is not None:
        return configured
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
    return enabled


def _validate_required_features(
    cases: Sequence[EvaluationCase], profile: EvaluationProfile
) -> None:
    tools = set(_enabled_tools(profile))
    available = set(_CONTEXT_FEATURES)
    if tools & _MYSQL_TOOLS:
        available.add("mysql")
    if (
        "milvus_vector_search" in tools
        and settings.ENABLE_MILVUS
        and settings.ENABLE_EMBEDDINGS
    ):
        available.add("milvus")
    if "dietary_safe_recipe_query" in tools and settings.ENABLE_NEO4J:
        available.add("neo4j")
    missing = {
        case.id: sorted(set(case.required_features) - available)
        for case in cases
        if set(case.required_features) - available
    }
    if missing:
        details = "; ".join(
            f"{case_id}={features}" for case_id, features in missing.items()
        )
        raise ValueError(f"evaluation profile is missing required features: {details}")


def build_evaluation_agent(
    profile: EvaluationProfile,
    container: ApplicationContainer,
) -> AgentExecutionService:
    """Build an isolated Agent so profile changes cannot mutate production singletons."""

    model = profile.model
    model_gateway = OpenAILanguageModelGateway(
        model=model.model,
        api_key=_api_key(model.api_key_env),
        base_url=model.base_url,
        prompts=_prompt_bundle(profile),
        decision_temperature=model.decision_temperature,
        answer_temperature=model.answer_temperature,
    )
    enabled = _enabled_tools(profile)
    tool_executor = build_tool_executor(
        document_knowledge_provider=container.get_document_knowledge_service,
        recipe_catalog=container.get_recipe_catalog(),
        recipe_generation_service=RecipeGenerationService(model_gateway),
        enabled_tools=enabled,
        timeout_seconds=profile.tools.timeout_seconds,
    )
    graph = build_agent_graph(
        model_gateway=model_gateway,
        tool_executor=tool_executor,
        max_iterations=profile.tools.max_iterations,
        history_messages=settings.AGENT_HISTORY_MESSAGES,
        max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
        max_model_tokens=settings.AGENT_MAX_MODEL_TOKENS,
        max_model_cost=settings.AGENT_MAX_COST,
    )
    return AgentExecutionService(
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
        service: AgentExecutionService | None = None,
        judge: AnswerJudge | None = None,
        enable_judge: bool | None = None,
    ) -> None:
        self.profile = profile
        self._service = service
        self._judge = judge
        self._enable_judge = (
            profile.judge.enabled if enable_judge is None else enable_judge
        )
        self._container: ApplicationContainer | None = None

    def _ensure_runtime(self) -> AgentExecutionService:
        if self._enable_judge and self._judge is None:
            self._judge = OpenAICompatibleJudge(self.profile.judge)
        if self._service is None:
            self._container = ApplicationContainer()
            self._service = build_evaluation_agent(self.profile, self._container)
        return self._service

    async def run(
        self,
        cases: Sequence[EvaluationCase],
        *,
        dataset_path: Path,
        profile_path: Path,
    ) -> EvaluationReport:
        _validate_required_features(cases, self.profile)
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
            judge_model=(self.profile.judge.model if self._enable_judge else None),
            selected_cases=len(cases),
        )
        return EvaluationReport(
            config=config,
            summary=summary,
            results=results,
        )


__all__ = [
    "EvaluationRunner",
    "build_evaluation_agent",
]
