from __future__ import annotations

from pathlib import Path

from safemeal.evaluation.dataset import audit_dataset, load_dataset
from safemeal.evaluation.metrics import evaluate_case, summarize_results
from safemeal.application.contracts.agent import AgentProcessResponse
from safemeal.shared.contracts.common import AnswerSource


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


def test_summary_keeps_core_agent_and_judge_metrics() -> None:
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
    assert summary.cases == 1
    assert summary.error_rate == 1
    assert summary.judge_coverage == 0
