"""SafeMeal Agent offline evaluation toolkit.

The package root intentionally exposes only dependency-light contracts.  Import
``EvaluationRunner`` from :mod:`back.evaluation.runner` when an actual model run
is required; dataset auditing and metric unit tests should not initialise the
application composition root.
"""

from .dataset import DatasetAudit, audit_dataset, load_dataset
from .gates import evaluate_quality_gates
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
    "evaluate_quality_gates",
    "load_dataset",
    "summarize_results",
]
