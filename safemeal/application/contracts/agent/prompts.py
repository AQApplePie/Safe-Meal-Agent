"""Application value contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptBundle:
    """一组有版本号的 Agent Prompt。"""

    version: str
    planner: str
    reflection: str
    answer: str
    recipe_generation: str
