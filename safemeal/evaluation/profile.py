"""Strict loading of the local evaluation profile."""

from __future__ import annotations

from pathlib import Path

from safemeal.evaluation.models import EvaluationProfile
from safemeal.evaluation.paths import data_path


def load_profile(path: str | Path) -> tuple[EvaluationProfile, Path]:
    resolved = data_path(path, suffixes={".json"})
    return (
        EvaluationProfile.model_validate_json(resolved.read_text(encoding="utf-8")),
        resolved,
    )


__all__ = ["load_profile"]
