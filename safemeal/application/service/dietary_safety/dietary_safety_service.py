"""解析饮食要求并复核菜谱安全性。"""

import re
from typing import Literal

from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.contracts.dietary_safety.constraints import DietaryConstraint
from safemeal.application.contracts.dietary_safety.requirements import (
    DietaryPreference,
    DietaryRequirements,
    DietaryReviewResult,
    RecipeReview,
)
from safemeal.application.contracts.conversation.models import ConversationHistory
from .constraints import (
    dietary_constraint_from_user_memories,
    extract_dietary_constraint,
    merge_dietary_constraints,
    build_dietary_safety_result,
)
from .preference_rules import (
    assess_preference,
    preference_from_memory,
    preferences_from_text,
)
from .constraint_resolver import ConstraintResolver


def hard_constraints(requirements: DietaryRequirements) -> DietaryConstraint:
    return merge_dietary_constraints(
        [requirements.allergies, requirements.restrictions],
        strictness="workflow_hard_exclusion",
    )


class DietarySafetyService:
    def resolve_constraints(
        self, message: str, history: ConversationHistory, context: AgentContext
    ) -> DietaryRequirements:
        allergies = [
            dietary_constraint_from_user_memories(
                [
                    m
                    for m in context.user_memories
                    if m.get("memory_type") == "dietary_allergy"
                ]
            )
        ]
        restrictions = [
            dietary_constraint_from_user_memories(
                [
                    m
                    for m in context.user_memories
                    if m.get("memory_type") == "dietary_restriction"
                ]
            )
        ]
        preferences: list[DietaryPreference] = []
        for memory in context.user_memories:
            if memory.get("memory_type") in {"dietary_allergy", "dietary_restriction"}:
                continue


            preference = preference_from_memory(memory)
            if preference is not None:
                preferences.append(preference)
        if context.requirements is not None:
            allergies.append(context.requirements.allergies)
            restrictions.append(context.requirements.restrictions)
            preferences.extend(context.requirements.preferences)
        if context.dietary_constraints:
            restrictions.append(
                DietaryConstraint.model_validate(context.dietary_constraints)
            )

        profile = context.user_profile or {}
        if isinstance(profile.get("taste"), str):
            preferences.extend(
                preferences_from_text("喜欢" + str(profile["taste"]), "provided")
            )
        frame = context.request_frame
        if frame is not None:



            preferences.extend(frame.turn_preferences)
        else:




            texts: list[tuple[str, Literal["input"]]] = [(message, "input")]
            for text, source in texts:
                clauses = re.split(
                    r"[，,。；;！？!?\n]|但是|但|推荐|喜欢|偏好|想吃|想要", text
                )
                for clause in clauses:
                    constraint = extract_dietary_constraint(clause)
                    (allergies if "过敏" in clause else restrictions).append(
                        constraint
                    )
                preferences.extend(preferences_from_text(text, source))

        selected: dict[tuple[str, str], DietaryPreference] = {}
        for preference in preferences:
            key = (
                preference.kind,
                preference.value
                if preference.kind
                in {"include_ingredient", "avoid_ingredient", "other"}
                else "",
            )
            selected[key] = preference
        resolved = (
            ConstraintResolver().resolve(
                frame,
                context.user_memories,
                previous=(
                    context.requirements.resolved
                    if context.requirements is not None
                    else None
                ),
            )
            if frame is not None
            else context.requirements.resolved
            if context.requirements is not None
            else None
        )
        return DietaryRequirements(
            allergies=merge_dietary_constraints(allergies),
            restrictions=merge_dietary_constraints(restrictions),
            preferences=list(selected.values()),
            **({"resolved": resolved} if resolved is not None else {}),
        )

    def review_recipes(
        self, requirements: DietaryRequirements, observations: list[Observation]
    ) -> DietaryReviewResult:
        safety = build_dietary_safety_result(
            constraint=hard_constraints(requirements),
            observations=observations,
            require_evidence=True,
        )
        reviewed = []
        for record in [
            *safety.safe_recipes,
            *safety.excluded_recipes,
            *safety.unknown_recipes,
        ]:
            assessments = [
                assess_preference(p, record) for p in requirements.preferences
            ]
            required = [a for a in assessments if a.preference.required]
            decision: Literal["passed", "excluded", "unknown"] = "passed"
            if record.safety_status == "excluded" or any(
                a.status == "not_satisfied" for a in required
            ):
                decision = "excluded"
            elif record.safety_status == "unknown" or any(
                a.status == "unknown" for a in required
            ):
                decision = "unknown"
            statuses = [a.status for a in assessments]
            preference_status: Literal[
                "not_applicable", "satisfied", "not_satisfied", "unknown", "partial"
            ] = (
                "not_applicable"
                if not statuses
                else "satisfied"
                if all(s == "satisfied" for s in statuses)
                else "not_satisfied"
                if all(s == "not_satisfied" for s in statuses)
                else "unknown"
                if all(s == "unknown" for s in statuses)
                else "partial"
            )
            reviewed.append(
                RecipeReview(
                    name=record.name,
                    decision=decision,
                    allergy_status=record.safety_status,
                    preference_status=preference_status,
                    preferences=assessments,
                    evidence=record,
                )
            )

        reviewed.sort(
            key=lambda r: (
                r.decision != "passed",
                -sum(a.status == "satisfied" for a in r.preferences),
            )
        )
        return DietaryReviewResult(
            recipes=reviewed, missing_information=safety.missing_information
        )
