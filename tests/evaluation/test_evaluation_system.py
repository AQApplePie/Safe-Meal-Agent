from __future__ import annotations

from pathlib import Path
import json

from SafeMealAgent.back.evaluation.dataset import audit_dataset, load_dataset
from SafeMealAgent.back.evaluation.gates import evaluate_quality_gates
from SafeMealAgent.back.evaluation.metrics import evaluate_case, summarize_results
from SafeMealAgent.back.evaluation.models import QualityGateThresholds
from SafeMealAgent.back.evaluation.profile import load_profile
from SafeMealAgent.back.evaluation.runner import EvaluationRunner, merge_progress_reports
from SafeMealAgent.back.shared.contracts.agent import AgentProcessResponse
from SafeMealAgent.back.shared.contracts.common import AnswerSource


ROOT = Path(__file__).resolve().parents[2]


def test_v3_dataset_meets_construction_standard() -> None:
    cases = load_dataset(ROOT / "data/evaluation/agent_eval_v3.jsonl")
    audit = audit_dataset(cases)
    assert audit.passed, audit.issues
    assert audit.cases == 58
    assert audit.tool_case_ratio >= 0.30
    assert audit.hard_case_ratio >= 0.30
    for case in cases:
        if case.path_type == "refusal":
            assert not any(
                term.casefold() in case.reference_answer.casefold()
                for term in case.answer.forbidden_terms
            )


def test_trace_scores_route_parameters_retrieval_and_utilization() -> None:
    case = next(
        item
        for item in load_dataset(ROOT / "data/evaluation/agent_eval_v3.jsonl")
        if item.id == "kb-001"
    )
    response = AgentProcessResponse(
        message="宫保鸡丁包含鸡肉、花生，项目样例总用时35分钟。",
        sources=[
            AnswerSource(source="milvus", tool="milvus_vector_search", call_id="c1")
        ],
        metadata={
            "trace": {
                "iterations": 1,
                "total_latency_ms": 120,
                "token_usage": {
                    "input_tokens": 10,
                    "output_tokens": 8,
                    "total_tokens": 18,
                },
                "token_usage_complete": True,
                "tool_calls": [
                    {
                        "call_id": "c1",
                        "tool_name": "milvus_vector_search",
                        "arguments": {"query": "宫保鸡丁"},
                        "arguments_valid": True,
                        "ok": True,
                        "result": {
                            "documents": [
                                {
                                    "document_id": "eval-doc-gongbao",
                                    "content": "核心食材包括鸡肉、花生，总用时35分钟",
                                }
                            ]
                        },
                    }
                ],
            }
        },
    )
    result = evaluate_case(case, response)
    assert result.route.top1_correct
    assert result.parameters.semantic_accuracy == 1
    assert result.retrieval.hit_at_k == 1
    assert result.retrieval.context_recall == 1
    assert result.tool_utilization.rate == 1


def test_quality_gates_report_absolute_failures_and_optional_skips() -> None:
    case = next(
        item
        for item in load_dataset(ROOT / "data/evaluation/agent_eval_v3.jsonl")
        if item.id == "tool-001"
    )
    result = evaluate_case(
        case,
        AgentProcessResponse(status="error", message="失败", metadata={"trace": {}}),
    )
    summary = summarize_results([result])
    gates = evaluate_quality_gates(summary, QualityGateThresholds())
    by_name = {gate.metric: gate for gate in gates}
    assert not by_name["route_top1_accuracy"].passed
    assert by_name["retrieval_hit_at_5"].skipped
    assert not by_name["judge_coverage"].passed
    assert not by_name["error_rate"].passed


def test_progress_records_are_resumable_and_manifest_bound(tmp_path, monkeypatch) -> None:
    case = load_dataset(ROOT / "data/evaluation/agent_eval_v3.jsonl")[0]
    result = evaluate_case(
        case,
        AgentProcessResponse(message="完成", metadata={"trace": {}}),
    )
    manifest = {
        "type": "evaluation_progress",
        "dataset_sha256": "dataset",
        "profile_sha256": "profile",
        "judge_enabled": True,
        "case_ids": [case.id],
    }
    path = tmp_path / "progress.jsonl"
    path.write_text(
        json.dumps(manifest)
        + "\n"
        + json.dumps(
            {"type": "case_result", "index": 1, **result.model_dump(mode="json")}
        )
        + "\n",
        encoding="utf-8",
    )

    restored = EvaluationRunner._load_progress(path, manifest)

    assert [item.case_id for item in restored] == [case.id]

    profile, profile_path, _ = load_profile(
        ROOT / "data/evaluation/profiles/current_default.json"
    )
    monkeypatch.setattr("back.evaluation.paths.RESULTS_ROOT", tmp_path)
    report = merge_progress_reports(
        [case],
        progress_paths=[path],
        dataset_path=ROOT / "data/evaluation/agent_eval_v3.jsonl",
        profile=profile,
        profile_path=profile_path,
    )
    assert report.summary.cases == 1
