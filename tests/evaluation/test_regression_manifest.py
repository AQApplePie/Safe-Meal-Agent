"""Keep regression IDs and failure taxonomy machine-readable and stable."""

import json
from pathlib import Path


KNOWN_TAGS = {
    "NLU_TASK_ERROR",
    "NLU_ENTITY_ERROR",
    "NLU_COUNT_ERROR",
    "NLU_FIELD_ERROR",
    "REFERENCE_RESOLUTION_ERROR",
    "REQUESTFRAME_CONTRACT_ERROR",
    "PLANNER_TOOL_SELECTION_ERROR",
    "PLANNER_ARGUMENT_ERROR",
    "RETRIEVAL_COUNT_ERROR",
    "RETRIEVAL_FILTER_ERROR",
    "CATEGORY_TAXONOMY_ERROR",
    "FIELD_MISSING_ERROR",
    "MEMORY_SCOPE_ERROR",
    "SAFETY_ERROR",
    "GOAL_VERIFICATION_ERROR",
    "PREMATURE_COMPLETION",
    "TOOL_ERROR_MISCLASSIFIED",
    "LOOP_CONTROL_ERROR",
}


def test_regression_manifest_has_unique_ids_groups_and_known_failure_tags():
    path = Path(__file__).with_name("regression_cases.json")
    cases = json.loads(path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in cases]

    assert len(cases) >= 20
    assert len(ids) == len(set(ids))
    assert all(item["group"] and item["query"] for item in cases)
    assert all(set(item["tags"]) <= KNOWN_TAGS for item in cases)
