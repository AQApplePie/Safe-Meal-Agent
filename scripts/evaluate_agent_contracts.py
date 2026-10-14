"""Frozen offline request-contract benchmark; never calls a model or database."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "tests/evaluation/datasets/request_contract_v1.json"


def load_cases(path: Path = DATASET) -> list[dict[str, Any]]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != path.with_suffix(".sha256").read_text().strip():
        raise ValueError("Frozen dataset checksum mismatch")
    cases = json.loads(path.read_text())["cases"]
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    if any(c["split"] not in {"dev", "test"} for c in cases):
        raise ValueError("Unknown split")
    return cases


def predict(case: dict[str, Any], system: str) -> dict[str, Any]:
    if system in {"production_rules", "stateless_rules"}:
        frame = RequestUnderstandingService().understand(
            case["message"],
            case["recent_context"] if system == "production_rules" else [],
        )
        return dict(
            primary_task=frame.primary_task,
            recommendation_count=frame.recommendation_count,
            servings=frame.servings,
            recipe_name=frame.target.recipe_name,
            requested_fields=list(frame.requested_fields),
            constraints=[[c.kind, c.value] for c in frame.current_constraints],
            memory_values=[c.value for c in frame.memory_updates],
        )
    # Deliberately simple stateless baseline, no expected answer access.
    text = case["message"]
    count = re.search(r"(\d+)道", text)
    return dict(
        primary_task="recipe_recommendation" if "推荐" in text else "out_of_scope",
        recommendation_count=int(count[1]) if count else None,
        servings=None,
        recipe_name=None,
        requested_fields=[],
        constraints=[],
        memory_values=[],
    )


def grade(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    failures = []
    for key, value in expected.items():
        if key == "required_constraints":
            if any(item not in actual.get("constraints", []) for item in value):
                failures.append(key)
        elif key == "forbidden_memory_values":
            if set(value) & set(actual.get("memory_values", [])):
                failures.append(key)
        elif actual.get(key) != value:
            failures.append(key)
    return failures


def evaluate(split: str, repeats: int) -> dict[str, Any]:
    cases = [c for c in load_cases() if split == "all" or c["split"] == split]
    rows = []
    for system in ("stateless_keyword", "stateless_rules", "production_rules"):
        for repeat in range(repeats):
            for case in cases:
                try:
                    actual = predict(case, system)
                    errors = grade(case["expected"], actual)
                except Exception as exc:
                    actual = {}
                    errors = ["execution_error:" + type(exc).__name__]
                rows.append(
                    dict(
                        case_id=case["id"],
                        group=case["group"],
                        split=case["split"],
                        system=system,
                        repeat=repeat,
                        actual=actual,
                        failures=errors,
                        passed=not errors,
                    )
                )
    summary = {}
    for system in ("stateless_keyword", "stateless_rules", "production_rules"):
        selected = [r for r in rows if r["system"] == system]
        groups = {}
        for group in sorted({r["group"] for r in selected}):
            subset = [r for r in selected if r["group"] == group]
            groups[group] = dict(
                total=len(subset), passed=sum(r["passed"] for r in subset)
            )
        summary[system] = dict(
            total=len(selected),
            passed=sum(r["passed"] for r in selected),
            by_group=groups,
            failure_fields=dict(Counter(f for r in selected for f in r["failures"])),
        )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    sources = [Path(__file__), *sorted((ROOT / "safemeal").rglob("*.py"))]
    return dict(
        mode="offline_deterministic_contract",
        model=None,
        prompt=None,
        live_model_quality_measured=False,
        stochastic_stability_measured=False,
        dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        revision=revision,
        dirty=bool(status),
        python=platform.python_version(),
        source_sha256={
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
        split=split,
        repeats=repeats,
        unique_cases=len(cases),
        summary=summary,
        rows=rows,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.split, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return int(
        any(
            f.startswith("execution_error:")
            for f in report["summary"]["production_rules"]["failure_fields"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
