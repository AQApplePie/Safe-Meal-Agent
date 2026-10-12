"""定义跨层传递的稳定数据契约。"""

from typing import Literal
from pydantic import BaseModel


# 类说明（数据契约类）：IntentDecision
# 作用：描述Agent 意图决策的结构、类型及可校验字段。
class IntentDecision(BaseModel):
    # 字段说明：kind
    # 作用：当前业务记录或操作的类型。
    # 类型：Literal['recommend', 'menu_planning', 'recipe_detail', 'generate', 'replace', 'knowledge', 'memory', 'clarify', 'out_of_scope']。
    # 取值说明：
    #   recommend：推荐候选菜谱。
    #   menu_planning：规划满足数量与分类要求的菜单。
    #   recipe_detail：查看指定菜谱详情。
    #   generate：生成新的菜谱。
    #   replace：替换既有菜品或任务对象。
    #   knowledge：查询饮食知识。
    #   memory：更新用户长期记忆。
    #   clarify：请求用户澄清信息。
    #   out_of_scope：请求超出当前业务支持范围。
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
    # 字段说明：reason
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    # 初始值：''。
    reason: str = ""
    # 字段说明：clarification
    # 作用：缺少关键信息或语义不确定时向用户提出的澄清问题。
    # 类型：str。
    # 初始值：''。
    clarification: str = ""
