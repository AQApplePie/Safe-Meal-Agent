"""Command-line entrypoints for audit, corpus preparation, run and regression."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

from SafeMealAgent.back.evaluation.dataset import audit_as_json, audit_dataset, load_dataset
from SafeMealAgent.back.evaluation.models import EvaluationCase


DEFAULT_DATASET = "data/evaluation/agent_eval_v3.jsonl"
DEFAULT_PROFILE = "data/evaluation/profiles/current_default.json"
DEFAULT_CORPUS = "data/evaluation/retrieval_corpus.jsonl"
DEFAULT_OUTPUT = "evaluation_results/latest.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SafeMeal Agent 离线评测")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="审计评测集覆盖率和标注完整性")
    audit.add_argument("--dataset", default=DEFAULT_DATASET)
    audit.add_argument("--allow-small", action="store_true")

    prepare = sub.add_parser("prepare", help="显式写入冻结的检索评测语料")
    prepare.add_argument("--corpus", default=DEFAULT_CORPUS)
    prepare.add_argument(
        "--target", choices=("both", "milvus", "lightrag"), default="both"
    )

    run = sub.add_parser("run", help="直接调用当前本地 Agent 执行评测")
    run.add_argument("--dataset", default=DEFAULT_DATASET)
    run.add_argument("--profile", default=DEFAULT_PROFILE)
    run.add_argument("--output", default=DEFAULT_OUTPUT)
    run.add_argument(
        "--progress", default=None, help="evaluation_results 下的 JSONL 断点记录"
    )
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--case-id", action="append", default=[])
    run.add_argument("--category", action="append", default=[])
    run.add_argument("--path", action="append", default=[])
    run.add_argument(
        "--difficulty", action="append", choices=("easy", "medium", "hard"), default=[]
    )
    run.add_argument(
        "--available-feature",
        action="append",
        default=[],
        help="仅运行所需特性均已就绪的样本，可重复",
    )
    run.add_argument("--no-judge", action="store_true")
    run.add_argument("--enforce-gates", action="store_true")

    regression = sub.add_parser("regression", help="候选报告与基线做退化比较")
    regression.add_argument("--baseline", required=True)
    regression.add_argument("--candidate", required=True)
    regression.add_argument("--quality-drop", type=float, default=0.02)
    regression.add_argument("--cost-increase", type=float, default=0.10)
    regression.add_argument(
        "--output", default="evaluation_results/regression-latest.json"
    )

    merge = sub.add_parser(
        "merge", help="合并多个无重叠分片进度并生成完整门禁报告"
    )
    merge.add_argument("--dataset", default=DEFAULT_DATASET)
    merge.add_argument("--profile", default=DEFAULT_PROFILE)
    merge.add_argument("--progress", action="append", required=True)
    merge.add_argument("--replacement-progress", action="append", default=[])
    merge.add_argument("--output", required=True)
    merge.add_argument("--enforce-gates", action="store_true")
    return parser


def _select(
    cases: list[EvaluationCase], args: argparse.Namespace
) -> list[EvaluationCase]:
    selected = cases
    if args.case_id:
        requested = set(args.case_id)
        selected = [case for case in selected if case.id in requested]
        missing = sorted(requested - {case.id for case in selected})
        if missing:
            raise ValueError("unknown --case-id values: " + ", ".join(missing))
    if args.category:
        selected = [case for case in selected if case.category in set(args.category)]
    if args.path:
        selected = [case for case in selected if case.path_type in set(args.path)]
    if args.difficulty:
        selected = [
            case for case in selected if case.difficulty in set(args.difficulty)
        ]
    if args.available_feature:
        ready = set(args.available_feature)
        tool_features = {
            "search_recipes": "mysql",
            "get_recipe": "mysql",
            "recommend_recipes": "mysql",
            "milvus_vector_search": "milvus",
            "neo4j_schema": "neo4j",
            "neo4j_readonly_query": "neo4j",
            "dietary_safe_recipe_query": "neo4j",
            "lightrag_search": "lightrag",
        }

        def features_for(case: EvaluationCase) -> set[str]:
            labelled = set(case.required_features)
            labelled.update(
                tool_features[tool]
                for tool in case.tools.required
                if tool in tool_features
            )
            return labelled

        selected = [case for case in selected if features_for(case) <= ready]
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        selected = selected[: args.limit]
    if not selected:
        raise ValueError("filters selected zero evaluation cases")
    return selected


async def _run(args: argparse.Namespace) -> int:
    from SafeMealAgent.back.evaluation.paths import result_path
    from SafeMealAgent.back.evaluation.profile import load_profile
    from SafeMealAgent.back.evaluation.runner import EvaluationRunner, write_report

    cases = _select(load_dataset(args.dataset), args)
    profile, profile_path, _ = load_profile(args.profile)
    dataset_path = Path(args.dataset).resolve()
    progress = (
        result_path(args.progress, suffixes={".jsonl"}) if args.progress else None
    )
    report = await EvaluationRunner(
        profile,
        enable_judge=not args.no_judge,
    ).run(
        cases,
        dataset_path=dataset_path,
        profile_path=profile_path,
        progress_path=progress,
    )
    output = write_report(report, args.output)
    print(
        json.dumps(
            {
                "run_id": report.run_id,
                "report": str(output),
                "gates_passed": report.gates_passed,
                "summary": report.summary.model_dump(mode="json"),
                "failed_gates": [
                    gate.model_dump(mode="json")
                    for gate in report.gates
                    if not gate.passed
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if args.enforce_gates and not report.gates_passed else 0


def _merge(args: argparse.Namespace) -> int:
    from SafeMealAgent.back.evaluation.profile import load_profile
    from SafeMealAgent.back.evaluation.runner import merge_progress_reports, write_report

    cases = load_dataset(args.dataset)
    profile, profile_path, _ = load_profile(args.profile)
    report = merge_progress_reports(
        cases,
        progress_paths=args.progress,
        replacement_progress_paths=args.replacement_progress,
        dataset_path=Path(args.dataset).resolve(),
        profile=profile,
        profile_path=profile_path,
    )
    output = write_report(report, args.output)
    print(
        json.dumps(
            {
                "report": str(output),
                "gates_passed": report.gates_passed,
                "cases": report.summary.cases,
                "failed_gates": [
                    gate.model_dump(mode="json")
                    for gate in report.gates
                    if not gate.passed
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if args.enforce_gates and not report.gates_passed else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "audit":
        audit = audit_dataset(
            load_dataset(args.dataset), enforce_scale=not args.allow_small
        )
        print(audit_as_json(audit))
        return 0 if audit.passed else 2
    if args.command == "prepare":
        from SafeMealAgent.back.evaluation.corpus import load_corpus, prepare_corpus

        result = asyncio.run(
            prepare_corpus(load_corpus(args.corpus), target=args.target)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        return asyncio.run(_run(args))
    if args.command == "merge":
        return _merge(args)
    if args.command == "regression":
        from SafeMealAgent.back.evaluation.regression import compare_reports, load_report

        report = compare_reports(
            load_report(args.baseline),
            load_report(args.candidate),
            allowed_quality_drop=args.quality_drop,
            allowed_cost_increase=args.cost_increase,
        )
        from SafeMealAgent.back.evaluation.paths import atomic_write, result_path

        output = result_path(args.output, suffixes={".json"})
        atomic_write(output, report.model_dump_json(indent=2))
        print(report.model_dump_json(indent=2))
        return 0 if report.passed else 2
    raise RuntimeError(f"unsupported command: {args.command}")


__all__ = ["main"]
