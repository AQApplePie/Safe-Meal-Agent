from __future__ import annotations

import json
from pathlib import Path

import pytest

from safemeal.evaluation.evaluation_contracts import EvaluationCase


DATASET = Path("data/evaluation/agent_eval_v3.jsonl")


@pytest.mark.regression
def test_frozen_agent_dataset_is_reviewed_and_unique() -> None:
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) >= 25
    assert len({case.id for case in cases}) == len(cases)
    assert all(case.annotation.reviewed for case in cases)
    assert {case.path_type for case in cases} >= {
        "direct",
        "tool_only",
        "clarification",
        "refusal",
    }


@pytest.mark.regression
def test_retrieval_corpus_is_valid_jsonl() -> None:
    rows = [
        json.loads(line)
        for line in Path("data/evaluation/retrieval_corpus.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert rows
    assert all(row.get("document_id") and row.get("content") for row in rows)
