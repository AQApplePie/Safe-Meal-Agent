"""Typed contracts for datasets, deterministic scores and Judge reports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from safemeal.application.contracts.agent.context import AgentContext
from safemeal.shared.types import JsonObject, JsonValue


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Difficulty = Literal["easy", "medium", "hard"]
PathType = Literal[
    "direct",
    "kb_only",
    "tool_only",
    "kb_tool",
    "clarification",
    "refusal",
]
LanguageStyle = Literal["natural", "oral", "typo", "ambiguous"]


class RouteExpectation(BaseModel):
    """Gold label for the first routing decision."""

    model_config = ConfigDict(extra="forbid")

    requires_tool: bool
    behavior: Literal["answer", "tool", "clarify", "refuse"]
    top1_tools: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_route(self) -> "RouteExpectation":
        if self.requires_tool and not self.top1_tools:
            raise ValueError(
                "tool routes must label at least one acceptable first tool"
            )
        if not self.requires_tool and self.top1_tools:
            raise ValueError("non-tools routes cannot declare top1_tools")
        return self


class ToolExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=list, max_length=20)
    optional: list[str] = Field(default_factory=list, max_length=20)


class ArgumentExpectation(BaseModel):
    """Semantic assertions for at least one invocation of a tools."""

    model_config = ConfigDict(extra="forbid")

    tool_name: NonBlank
    required_keys: list[str] = Field(default_factory=list)
    string_contains: dict[str, list[str]] = Field(default_factory=dict)
    allowed_values: dict[str, list[JsonValue]] = Field(default_factory=dict)


class ResultExpectation(BaseModel):
    """Facts that must occur in a successful tools result."""

    model_config = ConfigDict(extra="forbid")

    tool_name: NonBlank
    expected_values: list[JsonValue] = Field(default_factory=list)
    minimum_items: int | None = Field(default=None, ge=0)
    exact_items: int | None = Field(default=None, ge=0)


class AnswerExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_term_groups: list[list[str]] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    required_sources: list[str] = Field(default_factory=list)


class RetrievalExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_doc_ids: list[str] = Field(default_factory=list)
    expected_evidence_points: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=100)


class DietaryTruthRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonBlank
    ingredients: list[str] = Field(default_factory=list)
    matched_allergens: list[str] = Field(default_factory=list)
    safety: Literal["safe", "unsafe", "unknown"]


class DietaryTruthExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allergens: list[str] = Field(min_length=1)
    safe_recipes: list[DietaryTruthRecipe] = Field(default_factory=list)
    unsafe_recipes: list[DietaryTruthRecipe] = Field(default_factory=list)
    unknown_recipes: list[DietaryTruthRecipe] = Field(default_factory=list)
    target_dish: str | None = None
    expected_target_safety: Literal["safe", "unsafe", "unknown"] | None = None
    min_safe_recommendations: int = Field(default=0, ge=0)


class AnnotationMetadata(BaseModel):
    """Provenance required for a reviewable benchmark label."""

    model_config = ConfigDict(extra="forbid")

    source: NonBlank
    annotator: NonBlank
    reviewed: bool = True
    review_notes: str = ""


class EvaluationCase(BaseModel):
    """One fully labelled, repeatable Agent evaluation case."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["3"] = "3"
    id: NonBlank
    category: NonBlank
    intent_label: NonBlank
    question: str = Field(min_length=1, max_length=5_000)
    reference_answer: str = Field(min_length=1, max_length=10_000)
    description: str = ""
    tags: list[str] = Field(default_factory=list, max_length=30)
    difficulty: Difficulty
    path_type: PathType
    language_style: LanguageStyle = "natural"
    route: RouteExpectation
    tools: ToolExpectation = Field(default_factory=ToolExpectation)
    arguments: list[ArgumentExpectation] = Field(default_factory=list)
    results: list[ResultExpectation] = Field(default_factory=list)
    answer: AnswerExpectation = Field(default_factory=AnswerExpectation)
    retrieval: RetrievalExpectation = Field(default_factory=RetrievalExpectation)
    dietary_truth: DietaryTruthExpectation | None = None
    context: AgentContext = Field(default_factory=AgentContext)
    max_iterations: int | None = Field(default=None, ge=0, le=20)
    required_features: list[str] = Field(default_factory=list)
    annotation: AnnotationMetadata

    @model_validator(mode="after")
    def validate_labels(self) -> "EvaluationCase":
        required = set(self.tools.required)
        optional = set(self.tools.optional)
        if required & optional:
            raise ValueError("required and optional tools must not overlap")
        if self.route.requires_tool != bool(required):
            raise ValueError(
                "route.requires_tool must match whether required tools are labelled"
            )
        if (
            self.route.top1_tools
            and not set(self.route.top1_tools) <= required | optional
        ):
            raise ValueError("top1_tools must be required or optional tools")
        if self.path_type in {"kb_only", "kb_tool"}:
            if not (
                self.retrieval.expected_doc_ids
                or self.retrieval.expected_evidence_points
            ):
                raise ValueError(
                    "knowledge paths require document IDs or evidence-point labels"
                )
        if self.path_type == "clarification" and self.route.behavior != "clarify":
            raise ValueError("clarification cases must use clarify behavior")
        if self.path_type == "refusal" and self.route.behavior != "refuse":
            raise ValueError("refusal cases must use refuse behavior")
        if any("dietary" in tag or "allergy" in tag for tag in self.tags):
            if self.dietary_truth is None:
                raise ValueError(
                    "dietary/allergy cases require an independent truth set"
                )
        return self


class RouteScore(BaseModel):
    decision_correct: bool
    top1_correct: bool
    actual_requires_tool: bool
    actual_first_tool: str | None = None


class ToolSelectionScore(BaseModel):
    required_recall: float = Field(ge=0, le=1)
    exact_match: bool
    actual_tools: list[str]
    missing_required: list[str] = Field(default_factory=list)
    unexpected: list[str] = Field(default_factory=list)


class ParameterScore(BaseModel):
    total_calls: int = Field(ge=0)
    schema_valid_calls: int = Field(ge=0)
    schema_validity: float = Field(ge=0, le=1)
    semantic_rules: int = Field(ge=0)
    semantic_rules_passed: int = Field(ge=0)
    semantic_accuracy: float = Field(ge=0, le=1)
    failures: list[str] = Field(default_factory=list)


class ResultScore(BaseModel):
    assertions: int = Field(ge=0)
    passed: int = Field(ge=0)
    accuracy: float = Field(ge=0, le=1)
    failures: list[str] = Field(default_factory=list)


class RetrievalScore(BaseModel):
    enabled: bool
    retrieved_doc_ids: list[str] = Field(default_factory=list)
    top1_hit: float | None = Field(default=None, ge=0, le=1)
    hit_at_k: float | None = Field(default=None, ge=0, le=1)
    context_recall: float | None = Field(default=None, ge=0, le=1)


class DietarySafetyScore(BaseModel):
    enabled: bool
    safety_passed: bool
    usefulness_passed: bool
    false_rejection: bool = False
    false_rejection_eligible: bool = False
    violations: list[str] = Field(default_factory=list)


class TaskScore(BaseModel):
    completed: bool
    checks: int = Field(ge=0)
    passed: int = Field(ge=0)
    failures: list[str] = Field(default_factory=list)


class ClaimAssessment(BaseModel):
    claim: str
    requires_evidence: bool = True
    supported: bool
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str


class JudgeResult(BaseModel):
    answer_correctness: float = Field(ge=0, le=1)
    faithfulness: float = Field(ge=0, le=1)
    task_completed: bool
    rationale: str
    claims: list[ClaimAssessment] = Field(default_factory=list)
    judge_model: str
    latency_ms: float = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    usage_available: bool = False
    error: str | None = None


class CaseEvaluationResult(BaseModel):
    case_id: str
    category: str
    difficulty: Difficulty
    path_type: PathType
    question: str
    reference_answer: str
    answer: str
    agent_status: str
    route: RouteScore
    tool_selection: ToolSelectionScore
    parameters: ParameterScore
    result_correctness: ResultScore
    retrieval: RetrievalScore
    dietary_safety: DietarySafetyScore
    task: TaskScore
    iterations: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    token_usage_complete: bool
    deterministic_answer_correctness: float = Field(ge=0, le=1)
    safety_redline: bool = False
    safety_redline_passed: bool = True
    judge: JudgeResult | None = None
    trace: JsonObject = Field(default_factory=dict)


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    base_url: str
    api_key_env: str = "LLM_API_KEY"
    decision_temperature: float = Field(default=0, ge=0, le=2)
    answer_temperature: float = Field(default=0.2, ge=0, le=2)


class PromptProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "default-v1"
    planner: str | None = None
    reflection: str | None = None
    answer: str | None = None
    recipe_generation: str | None = None


class ToolProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled_tools: list[str] | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=300)
    max_iterations: int = Field(default=4, ge=1, le=6)


class JudgeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    model: str = "deepseek-v4-pro"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = Field(default=0, ge=0, le=2)


class EvaluationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    model: ModelProfile
    prompts: PromptProfile = Field(default_factory=PromptProfile)
    tools: ToolProfile = Field(default_factory=ToolProfile)
    judge: JudgeProfile = Field(default_factory=JudgeProfile)


class EvaluationRunConfig(BaseModel):
    dataset: str
    profile: str
    model: str
    prompt_version: str
    judge_model: str | None = None
    selected_cases: int = Field(default=0, ge=0)


class EvaluationSummary(BaseModel):
    cases: int = Field(ge=0)
    route_top1_accuracy: float = Field(ge=0, le=1)
    tool_decision_accuracy: float = Field(ge=0, le=1)
    required_tool_recall: float = Field(ge=0, le=1)
    tool_selection_accuracy: float = Field(ge=0, le=1)
    parameter_schema_validity: float = Field(ge=0, le=1)
    parameter_accuracy: float = Field(ge=0, le=1)
    tool_result_accuracy: float = Field(ge=0, le=1)
    retrieval_top1_accuracy: float | None = Field(default=None, ge=0, le=1)
    retrieval_hit_at_5: float | None = Field(default=None, ge=0, le=1)
    context_recall: float | None = Field(default=None, ge=0, le=1)
    answer_correctness: float = Field(ge=0, le=1)
    faithfulness: float | None = Field(default=None, ge=0, le=1)
    judge_coverage: float = Field(ge=0, le=1)
    task_completion_rate: float = Field(ge=0, le=1)
    error_rate: float = Field(ge=0, le=1)
    false_rejection_rate: float | None = Field(default=None, ge=0, le=1)
    safety_violation_rate: float = Field(ge=0, le=1)
    average_iterations: float = Field(ge=0)
    average_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    average_tokens_per_request: float = Field(ge=0)
    token_usage_coverage: float = Field(ge=0, le=1)
    metrics_by_difficulty: dict[str, JsonObject] = Field(default_factory=dict)
    metrics_by_path_type: dict[str, JsonObject] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config: EvaluationRunConfig
    summary: EvaluationSummary
    results: list[CaseEvaluationResult]


__all__ = [name for name in globals() if not name.startswith("_")]
