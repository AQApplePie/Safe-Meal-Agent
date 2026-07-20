"""Confine evaluation inputs and outputs to repository-owned directories."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = (PROJECT_ROOT / "data" / "evaluation").resolve()
RESULTS_ROOT = (PROJECT_ROOT / "evaluation_results").resolve()


class EvaluationPathError(ValueError):
    pass


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
        raise EvaluationPathError(f"path must stay under {root}: {value}") from exc
    if suffixes and resolved.suffix.casefold() not in suffixes:
        raise EvaluationPathError(f"unsupported suffix: {resolved.suffix}")
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def data_path(
    value: str | Path, *, suffixes: set[str], must_exist: bool = True
) -> Path:
    return _resolve(value, root=DATA_ROOT, suffixes=suffixes, must_exist=must_exist)


def result_path(
    value: str | Path, *, suffixes: set[str], must_exist: bool = False
) -> Path:
    return _resolve(value, root=RESULTS_ROOT, suffixes=suffixes, must_exist=must_exist)


def atomic_write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


__all__ = [
    "DATA_ROOT",
    "RESULTS_ROOT",
    "EvaluationPathError",
    "atomic_write",
    "data_path",
    "result_path",
]
