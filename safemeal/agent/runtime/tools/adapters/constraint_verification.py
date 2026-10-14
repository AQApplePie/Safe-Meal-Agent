"""实现智能体可调用的应用层工具。"""

import asyncio
from safemeal.modules.dietary.contracts.control_plane import ConstraintDecision

from safemeal.modules.dietary.contracts.control_plane import ToolEvidence
from safemeal.agent.runtime.tools.contracts.payloads import (
    RecipeConstraintVerificationResult,
    VerifyRecipeConstraintsArgs,
)
from safemeal.agent.runtime.tools.ports.handler import ToolHandler
from safemeal.modules.dietary.application.constraint_evaluator import (
    ConstraintEvaluator,
)
from safemeal.modules.recipe.application import RecipeService


# 类说明（业务或基础设施实现类）：VerifyRecipeConstraintsTool
# 作用：实现候选食谱硬约束复核工具，封装该组件的业务处理与依赖协作。
class VerifyRecipeConstraintsTool(ToolHandler[VerifyRecipeConstraintsArgs]):
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'verify_recipe_constraints'。
    name = "verify_recipe_constraints"
    # 字段说明：purpose
    # 作用：工具或组件的业务用途说明。
    # 初始值：'根据规范菜谱的完整食材证据，确定性验证一组饮食约束。'。
    purpose = "根据规范菜谱的完整食材证据，确定性验证一组饮食约束。"
    # 字段说明：use_when
    # 作用：工具适用的任务或场景说明。
    use_when = (
        "Planner 或 Reflector 需要核验候选菜是否满足过敏、忌口或避开食材要求",
        "已有可信 recipe_id，且需要逐条输出 satisfied、violated 或 unknown 证据",
    )
    # 字段说明：do_not_use_when
    # 作用：工具不适用的场景说明，供规划器避免错误选用。
    do_not_use_when = (
        "没有可信 recipe_id 时先使用 search_recipes，禁止猜测 ID",
        "不能替代 Workflow 的 check_final_safety 发布门禁",
        "普通无约束的菜谱详情查询不需要调用",
    )
    # 字段说明：input_constraints
    # 作用：工具输入必须满足的条件说明。
    input_constraints = (
        "recipe_ids 必须是已有工具返回的正整数且不得重复",
        "constraints 必须使用规范 ConstraintStatement，不接受自然语言规则",
        "任何 unknown 都使 verified=false，禁止按安全通过处理",
    )
    # 字段说明：args_schema
    # 作用：工具入参的数据模型或 JSON Schema，供调用前校验参数。
    args_schema = VerifyRecipeConstraintsArgs

    # 方法说明：__init__
    # 作用：初始化候选食谱硬约束复核工具，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   recipe_service（RecipeService）：菜谱查询推荐与生成业务服务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, recipe_service: RecipeService) -> None:
        # 实例属性说明：_recipe_service
        # 作用：菜谱查询推荐与生成业务服务。
        self._recipe_service = recipe_service
        # 实例属性说明：_evaluator
        # 作用：逐项校验菜谱证据是否满足饮食约束的评估器。
        self._evaluator = ConstraintEvaluator()

    # 方法说明：run
    # 作用：执行候选食谱硬约束复核工具的业务处理流程。
    # 入参：
    #   arguments（VerifyRecipeConstraintsArgs）：按工具 Schema 校验后的调用参数。
    # 出参：RecipeConstraintVerificationResult；食谱硬约束复核结果。
    async def run(
        self, arguments: VerifyRecipeConstraintsArgs
    ) -> RecipeConstraintVerificationResult:
        recipes = await asyncio.gather(
            *(
                asyncio.to_thread(self._recipe_service.get, recipe_id)
                for recipe_id in dict.fromkeys(arguments.recipe_ids)
            )
        )
        decisions: list[ConstraintDecision] = []
        for recipe in recipes:
            evidence = ToolEvidence(
                recipe_name=recipe.name,
                ingredients=tuple(item.ingredient.name for item in recipe.ingredients),
                ingredients_complete=bool(recipe.ingredients),
                steps=tuple(item.instruction for item in recipe.steps),
                source=f"recipe:{recipe.id}",
                source_complete=True,
                fields={"recipe_id": recipe.id},
            )
            decisions.extend(
                self._evaluator.evaluate(constraint, evidence)
                for constraint in arguments.constraints
            )
        return RecipeConstraintVerificationResult(
            verified=bool(decisions)
            and all(item.status == "satisfied" for item in decisions),
            recipe_count=len(recipes),
            decisions=decisions,
        )


__all__ = ["VerifyRecipeConstraintsTool"]
