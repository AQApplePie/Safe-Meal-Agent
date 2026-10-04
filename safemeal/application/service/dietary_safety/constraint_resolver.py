"""Resolve canonical statements and typed memory into one active snapshot."""

from __future__ import annotations

from collections.abc import Iterable

from safemeal.application.contracts.dietary_safety.control_plane import (
    ResolvedConstraints,
)
from safemeal.application.contracts.workflow.request_frame import RequestFrame
from safemeal.application.contracts.workflow.semantic import ConstraintStatement
from safemeal.shared.types import JsonObject


class ConstraintResolver:
    """The sole authority for activating constraints for a workflow turn."""

    def resolve(
        self,
        frame: RequestFrame,
        memories: Iterable[JsonObject],
        *,
        previous: ResolvedConstraints | None = None,
    ) -> ResolvedConstraints:
        statements: list[ConstraintStatement] = []
        for memory in memories:
            memory_type = str(memory.get("memory_type") or "")
            value = str(memory.get("memory_key") or "").strip()
            if not value:
                continue
            if memory_type == "dietary_allergy":
                kind, strength = "allergy", "hard_safety"
            elif memory_type == "dietary_restriction":
                kind, strength = "restriction", "hard_safety"
            elif memory_type == "taste_dislike":
                kind, strength = "avoid", "soft_preference"
            elif memory_type == "taste_preference":
                kind, strength = "include", "menu_goal"
            else:
                continue
            statements.append(
                ConstraintStatement(
                    type=kind,
                    value=value,
                    strength=strength,
                    source="persistent_memory",
                    scope="persistent",
                )
            )

        if frame.context_relation in {"continuation", "modification"} and previous:
            statements.extend(
                item.model_copy(update={"source": "explicit_carryover"})
                for item in previous.active
                if item.scope in {"current_turn", "current_meal", "conversation"}
            )
        statements.extend(frame.statements)

        # Current input wins over carryover for the same semantic dimension.
        selected: dict[tuple[str, str], ConstraintStatement] = {}
        for item in statements:
            dimension = (
                ("taste", item.owner)
                if item.type == "taste"
                else (item.type, item.owner)
            )
            selected[dimension] = item
        active = tuple(selected.values())
        return ResolvedConstraints(
            hard_safety=tuple(i for i in active if i.strength == "hard_safety"),
            strong_requirements=tuple(
                i for i in active if i.strength == "strong_requirement"
            ),
            soft_preferences=tuple(
                i for i in active if i.strength == "soft_preference"
            ),
            menu_goals=tuple(i for i in active if i.strength == "menu_goal"),
        )


__all__ = ["ConstraintResolver"]
