"""定义跨层传递的稳定数据契约。"""

from typing import Literal
from pydantic import BaseModel


class IntentDecision(BaseModel):
    kind: Literal[
        "recommend",
        "menu_planning",
        "recipe_detail",
        "generate",
        "replace",
        "knowledge",
        "memory",
        "clarify",
        "out_of_scope",
    ]
    reason: str = ""
    clarification: str = ""
