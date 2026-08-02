"""Dataset loading plus the construction-standard audit shown in the design image."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

from safemeal.evaluation.models import EvaluationCase
from safemeal.evaluation.paths import data_path


MAX_DATASET_BYTES = 20 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024
MIN_CORE_CASES = 50
MAX_CORE_CASES = 200
REQUIRED_PATHS = {
    "direct",
    "kb_only",
    "tool_only",
    "kb_tool",
    "clarification",
    "refusal",
}
REQUIRED_STYLES = {"natural", "oral", "typo", "ambiguous"}


@dataclass(frozen=True)
class DatasetAudit:
    cases: int
    path_counts: dict[str, int]
    difficulty_counts: dict[str, int]
    language_style_counts: dict[str, int]
    tool_case_ratio: float
    hard_case_ratio: float
    reviewed_ratio: float
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def load_dataset(path: str | Path) -> list[EvaluationCase]:
    resolved = data_path(path, suffixes={".jsonl"})
    if resolved.stat().st_size > MAX_DATASET_BYTES:
        raise ValueError("evaluation dataset exceeds 20 MiB")
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if len(raw.encode("utf-8")) > MAX_LINE_BYTES:
                raise ValueError(f"{resolved}:{line_number} exceeds 256 KiB")
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            try:
                case = EvaluationCase.model_validate_json(raw)
            except Exception as exc:
                raise ValueError(
                    f"{resolved}:{line_number}: invalid case: {exc}"
                ) from exc
            if case.id in seen:
                raise ValueError(f"duplicate evaluation case id: {case.id}")
            seen.add(case.id)
            cases.append(case)
    if not cases:
        raise ValueError("evaluation dataset is empty")
    return cases


def audit_dataset(
    cases: list[EvaluationCase], *, enforce_scale: bool = True
) -> DatasetAudit:
    paths = Counter(case.path_type for case in cases)
    difficulties = Counter(case.difficulty for case in cases)
    styles = Counter(case.language_style for case in cases)
    issues: list[str] = []
    if enforce_scale and not MIN_CORE_CASES <= len(cases) <= MAX_CORE_CASES:
        issues.append(
            f"case count must be between {MIN_CORE_CASES} and {MAX_CORE_CASES}"
        )
    missing_paths = sorted(REQUIRED_PATHS - paths.keys())
    if missing_paths:
        issues.append(f"missing path types: {missing_paths}")
    missing_styles = sorted(REQUIRED_STYLES - styles.keys())
    if missing_styles:
        issues.append(f"missing language styles: {missing_styles}")
    tool_ratio = sum(case.route.requires_tool for case in cases) / len(cases)
    hard_ratio = difficulties["hard"] / len(cases)
    reviewed_ratio = sum(case.annotation.reviewed for case in cases) / len(cases)
    if tool_ratio < 0.30:
        issues.append("tool-required cases must cover at least 30% of the dataset")
    if hard_ratio < 0.30:
        issues.append("hard cases must cover at least 30% of the dataset")
    if reviewed_ratio < 1.0:
        issues.append("all benchmark cases must be reviewed before a full evaluation")
    for case in cases:
        if case.path_type != "refusal":
            continue
        reference = case.reference_answer.casefold()
        contradictions = [
            term for term in case.answer.forbidden_terms if term.casefold() in reference
        ]
        if contradictions:
            issues.append(
                f"{case.id}: forbidden answer terms also occur in reference answer: "
                f"{contradictions}"
            )

    return DatasetAudit(
        cases=len(cases),
        path_counts=dict(sorted(paths.items())),
        difficulty_counts=dict(sorted(difficulties.items())),
        language_style_counts=dict(sorted(styles.items())),
        tool_case_ratio=round(tool_ratio, 6),
        hard_case_ratio=round(hard_ratio, 6),
        reviewed_ratio=round(reviewed_ratio, 6),
        issues=tuple(issues),
    )


def audit_as_json(audit: DatasetAudit) -> str:
    return json.dumps(
        {
            "passed": audit.passed,
            "cases": audit.cases,
            "path_counts": audit.path_counts,
            "difficulty_counts": audit.difficulty_counts,
            "language_style_counts": audit.language_style_counts,
            "tool_case_ratio": audit.tool_case_ratio,
            "hard_case_ratio": audit.hard_case_ratio,
            "reviewed_ratio": audit.reviewed_ratio,
            "issues": audit.issues,
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = ["DatasetAudit", "audit_as_json", "audit_dataset", "load_dataset"]
