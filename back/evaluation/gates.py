"""Absolute quality gates corresponding to the evaluation-system diagram."""

from __future__ import annotations

from SafeMealAgent.back.evaluation.models import (
    EvaluationSummary,
    GateResult,
    QualityGateThresholds,
)


def evaluate_quality_gates(
    summary: EvaluationSummary,
    thresholds: QualityGateThresholds,
) -> list[GateResult]:
    minimums = {
        "route_top1_accuracy": thresholds.route_top1_accuracy,
        "retrieval_hit_at_5": thresholds.retrieval_hit_at_5,
        "context_recall": thresholds.context_recall,
        "tool_decision_accuracy": thresholds.tool_decision_accuracy,
        "tool_selection_accuracy": thresholds.tool_selection_accuracy,
        "parameter_accuracy": thresholds.parameter_accuracy,
        "tool_result_utilization": thresholds.tool_result_utilization,
        "answer_correctness": thresholds.answer_correctness,
        "faithfulness": thresholds.faithfulness,
        "judge_coverage": thresholds.judge_coverage,
    }
    maximums = {
        "error_rate": thresholds.maximum_error_rate,
        "wrong_answer_rate": thresholds.maximum_wrong_answer_rate,
        "safety_violation_rate": thresholds.maximum_safety_violation_rate,
        "p95_latency_ms": thresholds.maximum_p95_latency_ms,
        "average_tokens_per_request": thresholds.maximum_average_tokens,
    }
    results: list[GateResult] = []
    for metric, threshold in minimums.items():
        actual = getattr(summary, metric)
        results.append(
            GateResult(
                metric=metric,
                actual=actual,
                threshold=threshold,
                operator=">=",
                passed=actual is None or actual >= threshold,
                skipped=actual is None,
            )
        )
    for metric, threshold in maximums.items():
        actual = getattr(summary, metric)
        results.append(
            GateResult(
                metric=metric,
                actual=actual,
                threshold=threshold,
                operator="<=",
                passed=actual <= threshold,
            )
        )
    return results


__all__ = ["evaluate_quality_gates"]
