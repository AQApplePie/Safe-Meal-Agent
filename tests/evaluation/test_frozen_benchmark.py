"""Validate oracle integrity and scoring independently of benchmark pass rates."""

import pytest

from scripts.evaluate_agent_contracts import grade, load_cases, predict


def test_frozen_dataset_is_stratified_and_has_explicit_oracles():
    cases = load_cases()
    assert len(cases) == 120
    assert len({(c["message"], str(c["recent_context"])) for c in cases}) == 120
    assert all(c["expected"] and c["source"] for c in cases)
    for group in {c["group"] for c in cases}:
        assert {c["split"] for c in cases if c["group"] == group} == {"dev", "test"}


def test_grader_detects_constraint_and_memory_failures():
    expected = dict(
        primary_task="recipe_recommendation",
        required_constraints=[["allergy", "花生"]],
        forbidden_memory_values=["鱼"],
    )
    assert grade(
        expected,
        dict(
            primary_task="recipe_recommendation", constraints=[], memory_values=["鱼"]
        ),
    ) == ["required_constraints", "forbidden_memory_values"]
    assert (
        grade(
            expected,
            dict(
                primary_task="recipe_recommendation",
                constraints=[["allergy", "花生"]],
                memory_values=[],
            ),
        )
        == []
    )


def test_baseline_cannot_access_oracle_and_context_ablation_is_real():
    case = next(c for c in load_cases() if c["group"] == "reference")
    original = predict(case, "production_rules")
    assert (
        predict({**case, "expected": {"primary_task": "wrong"}}, "production_rules")
        == original
    )
    assert original["recipe_name"]
    assert predict(case, "stateless_rules")["primary_task"] == "clarify"


def test_checksum_rejects_changed_dataset(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text("{}")
    path.with_suffix(".sha256").write_text("invalid")
    with pytest.raises(ValueError, match="checksum"):
        load_cases(path)
