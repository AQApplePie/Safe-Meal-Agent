"""SafeMeal Agent offline evaluation toolkit.

The package root intentionally exposes only dependency-light contracts.  Import
``EvaluationRunner`` from :mod:`safemeal.evaluation.runner` when an actual model run
is required; dataset auditing and metric unit tests should not initialise the
application composition root.
"""

from .dataset import DatasetAudit, audit_dataset, load_dataset
from .metrics import evaluate_case, summarize_results
from .models import (
    CaseEvaluationResult,
    EvaluationCase,
    EvaluationProfile,
    EvaluationReport,
    EvaluationSummary,
)

__all__ = [
    "CaseEvaluationResult",
    "DatasetAudit",
    "EvaluationCase",
    "EvaluationProfile",
    "EvaluationReport",
    "EvaluationSummary",
    "audit_dataset",
    "evaluate_case",
    "load_dataset",
    "summarize_results",
]
