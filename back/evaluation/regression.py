"""Compare a candidate report with an immutable baseline report."""

from __future__ import annotations

from pathlib import Path

from SafeMealAgent.back.evaluation.models import EvaluationReport, MetricDelta, RegressionReport
from SafeMealAgent.back.evaluation.paths import result_path


HIGHER_IS_BETTER = (
    "route_top1_accuracy",
    "retrieval_hit_at_5",
    "context_recall",
    "tool_decision_accuracy",
    "tool_selection_accuracy",
    "parameter_accuracy",
    "tool_result_utilization",
    "answer_correctness",
    "faithfulness",
    "task_completion_rate",
)
LOWER_QUALITY_IS_BETTER = (
    "error_rate",
    "wrong_answer_rate",
    "safety_violation_rate",
)
RESOURCE_IS_BETTER_LOWER = (
    "p95_latency_ms",
    "average_tokens_per_request",
)


def load_report(path: str | Path) -> EvaluationReport:
    resolved = result_path(path, suffixes={".json"}, must_exist=True)
    return EvaluationReport.model_validate_json(resolved.read_text(encoding="utf-8"))


def compare_reports(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    *,
    allowed_quality_drop: float = 0.02,
    allowed_cost_increase: float = 0.10,
) -> RegressionReport:
    comparable_fields = (
        "dataset_sha256",
        "profile_sha256",
        "model",
        "prompt_version",
        "tool_strategy",
        "judge_model",
        "selected_cases",
    )
    incompatible = [
        field
        for field in comparable_fields
        if getattr(baseline.config, field) != getattr(candidate.config, field)
    ]
    if incompatible:
        raise ValueError(
            "baseline and candidate are not comparable; mismatched config: "
            + ", ".join(incompatible)
        )
    deltas: list[MetricDelta] = []
    for metric in HIGHER_IS_BETTER:
        old = getattr(baseline.summary, metric)
        new = getattr(candidate.summary, metric)
        if old is None or new is None:
            continue
        delta = float(new - old)
        deltas.append(
            MetricDelta(
                metric=metric,
                baseline=old,
                candidate=new,
                delta=delta,
                allowed_drop=allowed_quality_drop,
                regressed=delta < -allowed_quality_drop,
            )
        )
    for metric in LOWER_QUALITY_IS_BETTER:
        old = float(getattr(baseline.summary, metric))
        new = float(getattr(candidate.summary, metric))
        delta = new - old
        deltas.append(
            MetricDelta(
                metric=metric,
                baseline=old,
                candidate=new,
                delta=delta,
                allowed_drop=allowed_quality_drop,
                regressed=delta > allowed_quality_drop,
            )
        )
    for metric in RESOURCE_IS_BETTER_LOWER:
        old = float(getattr(baseline.summary, metric))
        new = float(getattr(candidate.summary, metric))
        allowance = allowed_cost_increase * max(abs(old), 1.0)
        delta = new - old
        deltas.append(
            MetricDelta(
                metric=metric,
                baseline=old,
                candidate=new,
                delta=delta,
                allowed_drop=allowance,
                regressed=delta > allowance,
            )
        )
    return RegressionReport(
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        passed=not any(item.regressed for item in deltas),
        deltas=deltas,
    )


__all__ = ["compare_reports", "load_report"]
