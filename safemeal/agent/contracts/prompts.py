"""定义跨层传递的稳定数据契约。"""

from dataclasses import dataclass


# 类说明（数据契约类）：PromptBundle
# 作用：一组有版本号的 Agent Prompt。
@dataclass(frozen=True)
class PromptBundle:
    """一组有版本号的 Agent Prompt。"""

    # 字段说明：version
    # 作用：记录或协议的版本号。
    # 类型：str。
    version: str
    # 字段说明：planner
    # 作用：决定下一步工具调用或终止条件的规划组件。
    # 类型：str。
    planner: str
    # 字段说明：reflection
    # 作用：工具执行后的反思结果，决定是否继续规划。
    # 类型：str。
    reflection: str
    # 字段说明：answer
    # 作用：生成最终用户答复所用的提示词模板。
    # 类型：str。
    answer: str
    # 字段说明：recipe_generation
    # 作用：菜谱生成任务的参数或执行能力。
    # 类型：str。
    recipe_generation: str
