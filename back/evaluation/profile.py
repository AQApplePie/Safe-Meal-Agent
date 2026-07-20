"""Strict loading and hashing of versioned evaluation profiles."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from SafeMealAgent.back.evaluation.models import EvaluationProfile
from SafeMealAgent.back.evaluation.paths import data_path


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_profile(path: str | Path) -> tuple[EvaluationProfile, Path, str]:
    resolved = data_path(path, suffixes={".json"})
    return (
        EvaluationProfile.model_validate_json(resolved.read_text(encoding="utf-8")),
        resolved,
        file_sha256(resolved),
    )


__all__ = ["file_sha256", "load_profile"]
