"""Run the benchmark directly against the current modular-monolith Agent."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Sequence

from safemeal.application.agent.execution_service import (
    AgentExecutionService,
)
from safemeal.application.contracts.agent.api import AgentProcessResponse
from safemeal.application.service.composition.application_container import ApplicationContainer
from safemeal.config.settings import settings
from safemeal.evaluation.llm_judge import AnswerJudge, OpenAICompatibleJudge
from safemeal.evaluation.scoring import apply_judge, evaluate_case, summarize_results
from safemeal.application.contracts.evaluation.models import (
    EvaluationCase,
    EvaluationProfile,
    EvaluationReport,
    EvaluationRunConfig,
)
from safemeal.application.service.composition.evaluation_factory import (
    build_evaluation_agent,
    _enabled_tools,
)


_MYSQL_TOOLS = {"search_recipes", "get_recipe", "recommend_recipes"}
_CONTEXT_FEATURES = {"user_memory", "conversation_memory"}


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
