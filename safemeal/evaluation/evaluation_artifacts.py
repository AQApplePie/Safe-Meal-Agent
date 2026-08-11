"""Load, validate and persist the frozen artifacts used by offline evaluation."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from uuid import uuid4

from safemeal.evaluation.evaluation_contracts import (
    EvaluationCase,
    EvaluationProfile,
    EvaluationReport,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = (PROJECT_ROOT / "data" / "evaluation").resolve()
RESULTS_ROOT = (PROJECT_ROOT / "evaluation_results").resolve()
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


class EvaluationArtifactError(ValueError):
    """An evaluation artifact is outside its root or has an invalid shape."""


def _resolve(
    value: str | Path,
    *,
    root: Path,
    suffixes: set[str],
    must_exist: bool,
) -> Path:
    raw = Path(value).expanduser()
    resolved = (raw if raw.is_absolute() else PROJECT_ROOT / raw).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise EvaluationArtifactError(f"path must stay under {root}: {value}") from exc
    if resolved.suffix.casefold() not in suffixes:
        raise EvaluationArtifactError(f"unsupported suffix: {resolved.suffix}")
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _data_path(value: str | Path, suffixes: set[str]) -> Path:
    return _resolve(value, root=DATA_ROOT, suffixes=suffixes, must_exist=True)


def _result_path(value: str | Path) -> Path:
    return _resolve(value, root=RESULTS_ROOT, suffixes={".json"}, must_exist=False)


@dataclass(frozen=True, slots=True)
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


def load_dataset(path: str | Path) -> tuple[list[EvaluationCase], Path]:
    """Load a validated JSONL benchmark and return its canonical path."""

    resolved = _data_path(path, {".jsonl"})
    if resolved.stat().st_size > MAX_DATASET_BYTES:
        raise EvaluationArtifactError("evaluation dataset exceeds 20 MiB")
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if len(raw.encode("utf-8")) > MAX_LINE_BYTES:
                raise EvaluationArtifactError(
                    f"{resolved}:{line_number} exceeds 256 KiB"
                )
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            try:
                case = EvaluationCase.model_validate_json(raw)
            except Exception as exc:
                raise EvaluationArtifactError(
                    f"{resolved}:{line_number}: invalid case: {exc}"
                ) from exc
            if case.id in seen:
                raise EvaluationArtifactError(
                    f"duplicate evaluation case id: {case.id}"
                )
            seen.add(case.id)
            cases.append(case)
    if not cases:
        raise EvaluationArtifactError("evaluation dataset is empty")
    return cases, resolved


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
    if missing := sorted(REQUIRED_PATHS - paths.keys()):
        issues.append(f"missing path types: {missing}")
    if missing := sorted(REQUIRED_STYLES - styles.keys()):
        issues.append(f"missing language styles: {missing}")
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
        contradictions = [
            term
            for term in case.answer.forbidden_terms
            if term.casefold() in case.reference_answer.casefold()
        ]
        if contradictions:
            issues.append(
                f"{case.id}: forbidden terms also occur in reference answer: "
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
        {"passed": audit.passed, **asdict(audit)},
        ensure_ascii=False,
        indent=2,
        default=list,
    )


def load_profile(path: str | Path) -> tuple[EvaluationProfile, Path]:
    resolved = _data_path(path, {".json"})
    return (
        EvaluationProfile.model_validate_json(resolved.read_text(encoding="utf-8")),
        resolved,
    )


def load_corpus(path: str | Path) -> list[dict[str, str]]:
    resolved = _data_path(path, {".jsonl"})
    documents: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        resolved.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        item = json.loads(line)
        required = {"document_id", "title", "content"}
        if not isinstance(item, dict) or not required <= item.keys():
            raise EvaluationArtifactError(
                f"{resolved}:{line_number}: corpus fields must include "
                f"{sorted(required)}"
            )
        normalized = {key: str(item[key]).strip() for key in required}
        if not all(normalized.values()):
            raise EvaluationArtifactError(
                f"{resolved}:{line_number}: corpus fields cannot be blank"
            )
        document_id = normalized["document_id"]
        if document_id in seen:
            raise EvaluationArtifactError(
                f"duplicate corpus document_id: {document_id}"
            )
        seen.add(document_id)
        documents.append(normalized)
    return documents


async def prepare_corpus(documents: list[dict[str, str]]) -> dict[str, int]:
    """Explicitly replace the frozen retrieval benchmark documents."""

    from safemeal.bootstrap.application_container import ApplicationContainer

    container = ApplicationContainer()
    try:
        document_knowledge = await container.get_document_knowledge_service()
        added = 0
        for item in documents:
            added += int(
                await document_knowledge.ingest_document(
                    doc_id=item["document_id"],
                    title=item["title"],
                    content=item["content"],
                    metadata={"dataset": "agent_eval_v3", "category": "evaluation"},
                )
            )
        return {"documents": len(documents), "milvus_documents_replaced": added}
    finally:
        await container.shutdown()


def write_report(report: EvaluationReport, path: str | Path) -> Path:
    resolved = _result_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(report.model_dump_json(indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
    finally:
        temporary.unlink(missing_ok=True)
    return resolved


__all__ = [
    "DatasetAudit",
    "EvaluationArtifactError",
    "audit_as_json",
    "audit_dataset",
    "load_corpus",
    "load_dataset",
    "load_profile",
    "prepare_corpus",
    "write_report",
]
