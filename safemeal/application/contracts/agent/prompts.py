"""定义跨层传递的稳定数据契约。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptBundle:
    """一组有版本号的 Agent Prompt。"""

    version: str
    planner: str
    reflection: str
    answer: str
    recipe_generation: str
