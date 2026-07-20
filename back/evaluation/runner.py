"""Run the benchmark directly against the current modular-monolith Agent."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from typing import Protocol, Sequence

from SafeMealAgent.back.application.agents.graph import build_agent_graph
from SafeMealAgent.back.application.agents.prompts import DEFAULT_PROMPT_BUNDLE, PromptBundle
from SafeMealAgent.back.application.use_cases.agent.graph_runner_service import (
    AgentGraphRunnerService,
)
from SafeMealAgent.back.application.use_cases.recipes import RecipeGenerationService
from SafeMealAgent.back.bootstrap.container import AppContainer
from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.evaluation.gates import evaluate_quality_gates
from SafeMealAgent.back.evaluation.judge import AnswerJudge, OpenAICompatibleJudge
from SafeMealAgent.back.evaluation.metrics import apply_judge, evaluate_case, summarize_results
from SafeMealAgent.back.evaluation.models import (
    CaseEvaluationResult,
    EvaluationCase,
    EvaluationProfile,
    EvaluationReport,
    EvaluationRunConfig,
)
from SafeMealAgent.back.evaluation.paths import atomic_write, result_path
from SafeMealAgent.back.evaluation.profile import file_sha256
from SafeMealAgent.back.infrastructure.llm.decision_engine import OpenAIDecisionEngine
from SafeMealAgent.back.infrastructure.tools.registry.factory import create_tool_registry
from SafeMealAgent.back.infrastructure.tools.registry.local_registry import LocalToolRegistry
from SafeMealAgent.back.shared.contracts.agent import AgentProcessResponse
from SafeMealAgent.back.shared.contracts.agent_context import AgentContext


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
            enabled.extend(
                ["neo4j_schema", "neo4j_readonly_query", "dietary_safe_recipe_query"]
            )
        if settings.ENABLE_LIGHTRAG:
            enabled.append("lightrag_search")
    runtime = create_tool_registry(
        knowledge_provider=container.get_knowledge_service,
        lightrag_provider=container.get_lightrag_service,
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
        progress_path: Path | None = None,
    ) -> EvaluationReport:
        manifest = {
            "type": "evaluation_progress",
            "dataset_sha256": file_sha256(dataset_path),
            "profile_sha256": file_sha256(profile_path),
            "judge_enabled": self._enable_judge,
            "case_ids": [case.id for case in cases],
        }
        completed = self._load_progress(progress_path, manifest)
        results_by_id = {result.case_id: result for result in completed}
        pending = [case for case in cases if case.id not in results_by_id]
        service = self._ensure_runtime() if pending else self._service
        try:
            for index, case in enumerate(cases, start=1):
                if case.id in results_by_id:
                    continue
                assert service is not None
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
                results_by_id[case.id] = result
                if progress_path is not None:
                    progress_path.parent.mkdir(parents=True, exist_ok=True)
                    with progress_path.open("a", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps(
                                {
                                    "type": "case_result",
                                    "index": index,
                                    **result.model_dump(mode="json"),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
        finally:
            if self._container is not None:
                await self._container.shutdown()
        results = [results_by_id[case.id] for case in cases]
        summary = summarize_results(results)
        gates = evaluate_quality_gates(summary, self.profile.gates)
        config = EvaluationRunConfig(
            dataset=str(dataset_path),
            dataset_sha256=file_sha256(dataset_path),
            profile=str(profile_path),
            profile_sha256=file_sha256(profile_path),
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
            gates=gates,
            gates_passed=all(gate.passed for gate in gates),
            results=results,
        )

    @staticmethod
    def _load_progress(
        progress_path: Path | None,
        manifest: dict,
    ) -> list[CaseEvaluationResult]:
        if progress_path is None:
            return []
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        if not progress_path.exists():
            progress_path.write_text(
                json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            return []
        lines = [
            line for line in progress_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not lines:
            progress_path.write_text(
                json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            return []
        stored_manifest = json.loads(lines[0])
        if stored_manifest != manifest:
            raise ValueError(
                "progress manifest does not match the selected dataset/profile/cases; "
                "use a different --progress path or remove the stale file"
            )
        results: list[CaseEvaluationResult] = []
        seen: set[str] = set()
        for line in lines[1:]:
            payload = json.loads(line)
            if payload.pop("type", None) != "case_result":
                raise ValueError("invalid evaluation progress record")
            payload.pop("index", None)
            result = CaseEvaluationResult.model_validate(payload)
            if result.case_id in seen:
                raise ValueError(f"duplicate progress result for {result.case_id}")
            seen.add(result.case_id)
            results.append(result)
        return results


def write_report(report: EvaluationReport, path: str | Path) -> Path:
    resolved = result_path(path, suffixes={".json"})
    return atomic_write(resolved, report.model_dump_json(indent=2))


def merge_progress_reports(
    cases: Sequence[EvaluationCase],
    *,
    progress_paths: Sequence[str | Path],
    replacement_progress_paths: Sequence[str | Path] = (),
    dataset_path: Path,
    profile: EvaluationProfile,
    profile_path: Path,
) -> EvaluationReport:
    """Merge completed, non-overlapping shards into one auditable report."""

    expected = {case.id for case in cases}
    by_id: dict[str, CaseEvaluationResult] = {}
    def ingest(raw_path: str | Path, *, replacement: bool) -> None:
        path = result_path(raw_path, suffixes={".jsonl"}, must_exist=True)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("type") == "evaluation_progress":
                continue
            payload.pop("type", None)
            payload.pop("index", None)
            result = CaseEvaluationResult.model_validate(payload)
            if result.case_id not in expected:
                raise ValueError(
                    f"{path}:{line_number}: unexpected case {result.case_id}"
                )
            if result.case_id in by_id:
                if not replacement:
                    raise ValueError(f"duplicate result for case {result.case_id}")
            elif replacement:
                raise ValueError(
                    f"replacement result has no original case: {result.case_id}"
                )
            by_id[result.case_id] = result
    for raw_path in progress_paths:
        ingest(raw_path, replacement=False)
    for raw_path in replacement_progress_paths:
        ingest(raw_path, replacement=True)
    missing = [case.id for case in cases if case.id not in by_id]
    if missing:
        raise ValueError("progress shards are incomplete: " + ", ".join(missing))
    results = [by_id[case.id] for case in cases]
    summary = summarize_results(results)
    gates = evaluate_quality_gates(summary, profile.gates)
    return EvaluationReport(
        config=EvaluationRunConfig(
            dataset=str(dataset_path),
            dataset_sha256=file_sha256(dataset_path),
            profile=str(profile_path),
            profile_sha256=file_sha256(profile_path),
            model=profile.model.model,
            prompt_version=profile.prompts.version,
            tool_strategy=profile.tools.strategy,
            judge_model=(
                profile.judge.model or profile.model.model
                if profile.judge.enabled
                else None
            ),
            selected_cases=len(cases),
        ),
        summary=summary,
        gates=gates,
        gates_passed=all(gate.passed for gate in gates),
        results=results,
    )


__all__ = [
    "EvaluationRunner",
    "build_evaluation_agent",
    "merge_progress_reports",
    "write_report",
]
