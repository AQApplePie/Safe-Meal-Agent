"""Small CLI for dataset audit, Milvus preparation and Agent evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

from safemeal.evaluation.dataset import audit_as_json, audit_dataset, load_dataset
from safemeal.evaluation.models import EvaluationCase


DEFAULT_DATASET = "data/evaluation/agent_eval_v3.jsonl"
DEFAULT_PROFILE = "data/evaluation/profiles/current_default.json"
DEFAULT_CORPUS = "data/evaluation/retrieval_corpus.jsonl"
DEFAULT_OUTPUT = "evaluation_results/latest.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SafeMeal Agent 离线评测")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="审计评测数据集")
    audit.add_argument("--dataset", default=DEFAULT_DATASET)
    audit.add_argument("--allow-small", action="store_true")

    prepare = sub.add_parser("prepare", help="把冻结语料写入 Milvus")
    prepare.add_argument("--corpus", default=DEFAULT_CORPUS)

    run = sub.add_parser("run", help="运行 Agent + LLM Judge 评测")
    run.add_argument("--dataset", default=DEFAULT_DATASET)
    run.add_argument("--profile", default=DEFAULT_PROFILE)
    run.add_argument("--output", default=DEFAULT_OUTPUT)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--case-id", action="append", default=[])
    run.add_argument("--category", action="append", default=[])
    run.add_argument("--no-judge", action="store_true")
    return parser


def _select(
    cases: list[EvaluationCase], args: argparse.Namespace
) -> list[EvaluationCase]:
    selected = cases
    if args.case_id:
        requested = set(args.case_id)
        selected = [case for case in selected if case.id in requested]
    if args.category:
        selected = [case for case in selected if case.category in set(args.category)]
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        selected = selected[: args.limit]
    if not selected:
        raise ValueError("filters selected zero evaluation cases")
    return selected


async def _run(args: argparse.Namespace) -> int:
    from safemeal.evaluation.profile import load_profile
    from safemeal.evaluation.runner import EvaluationRunner, write_report

    cases = _select(load_dataset(args.dataset), args)
    profile, profile_path = load_profile(args.profile)
    report = await EvaluationRunner(
        profile,
        enable_judge=not args.no_judge,
    ).run(
        cases,
        dataset_path=Path(args.dataset).resolve(),
        profile_path=profile_path,
    )
    output = write_report(report, args.output)
    print(
        json.dumps(
            {
                "run_id": report.run_id,
                "report": str(output),
                "summary": report.summary.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "audit":
        audit = audit_dataset(
            load_dataset(args.dataset), enforce_scale=not args.allow_small
        )
        print(audit_as_json(audit))
        return 0 if audit.passed else 2
    if args.command == "prepare":
        from safemeal.evaluation.corpus import load_corpus, prepare_corpus

        result = asyncio.run(prepare_corpus(load_corpus(args.corpus)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        return asyncio.run(_run(args))
    raise RuntimeError(f"unsupported command: {args.command}")


__all__ = ["main"]
