"""本地工具运行时。

本模块负责工具说明、参数校验、超时控制和工具实现调度。
它不依赖 Agent 图内部状态，可由应用层稳定调用和独立测试。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError
from loguru import logger

from safemeal.shared.exceptions import ApplicationError, DatabaseOperationError
from safemeal.agent.runtime.tools.contracts.base import ToolResult, ToolSpecification
from safemeal.shared.types import JsonObject, JsonValue, to_json_object, to_json_value


ToolArgs = TypeVar("ToolArgs", bound=BaseModel)


# 类说明（接口类）：ToolHandler
# 作用：本地具体工具的基础抽象。
class ToolHandler(Generic[ToolArgs], ABC):
    """本地具体工具的基础抽象。

    具体工具只需要声明名称、描述、参数模型，并实现 ``run``。运行时统一负责：

    - 生成 ToolSpecification；
    - 使用 Pydantic 校验参数；
    - 把返回值转换为 JSON 友好的 ToolResult。
    """

    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：purpose
    # 作用：工具或组件的业务用途说明。
    # 类型：str。
    purpose: str
    # 字段说明：use_when
    # 作用：工具适用的任务或场景说明。
    # 类型：tuple[str, ...]。
    use_when: tuple[str, ...]
    # 字段说明：do_not_use_when
    # 作用：工具不适用的场景说明，供规划器避免错误选用。
    # 类型：tuple[str, ...]。
    do_not_use_when: tuple[str, ...]
    # 字段说明：input_constraints
    # 作用：工具输入必须满足的条件说明。
    # 类型：tuple[str, ...]。
    input_constraints: tuple[str, ...]
    # 字段说明：side_effects
    # 作用：工具可能产生的写入、外部操作等副作用说明。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    side_effects: tuple[str, ...] = ()
    # 字段说明：requires_approval
    # 作用：执行该工具或动作前是否需要人工确认。
    # 类型：bool。
    # 初始值：False。
    requires_approval: bool = False
    # 字段说明：idempotent
    # 作用：相同调用重复执行是否不会产生额外业务副作用。
    # 类型：bool。
    # 初始值：True。
    idempotent: bool = True
    # 字段说明：args_schema
    # 作用：工具入参的数据模型或 JSON Schema，供调用前校验参数。
    # 类型：type[ToolArgs]。
    args_schema: type[ToolArgs]

    # 方法说明：_planner_description
    # 作用：生成规划节点使用的工具能力说明。
    # 入参：
    #   无显式入参。
    # 出参：str；供模型规划阅读的工具能力说明。
    def _planner_description(self) -> str:

        sections = [
            f"用途：{self.purpose}",
            "适用场景：" + "；".join(self.use_when),
            "不要使用：" + "；".join(self.do_not_use_when),
            "输入约束：" + "；".join(self.input_constraints),
        ]
        if self.side_effects:
            sections.append("副作用：" + "；".join(self.side_effects))
        return "\n".join(sections)

    # 方法说明：specification
    # 作用：导出单个工具的名称、用途及参数约束规范。
    # 入参：
    #   无显式入参。
    # 出参：ToolSpecification；工具用途与参数规范。
    def specification(self) -> ToolSpecification:

        required = {
            "purpose": self.purpose,
            "use_when": self.use_when,
            "do_not_use_when": self.do_not_use_when,
            "input_constraints": self.input_constraints,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"工具 {self.name} 缺少描述字段：{missing}")

        return ToolSpecification(
            name=self.name,
            purpose=self.purpose,
            use_when=self.use_when,
            do_not_use_when=self.do_not_use_when,
            input_constraints=self.input_constraints,
            side_effects=self.side_effects,
            requires_approval=self.requires_approval,
            idempotent=self.idempotent,
            description=self._planner_description(),
            arguments_schema=to_json_object(self.args_schema.model_json_schema()),
        )

    # 方法说明：invoke
    # 作用：校验参数并执行工具。
    # 入参：
    #   call_id（str）：工具调用标识。
    #   arguments（JsonObject）：按工具 Schema 校验后的调用参数。
    # 出参：ToolResult；标准工具执行结果。
    async def invoke(self, call_id: str, arguments: JsonObject) -> ToolResult:
        """校验参数并执行工具。"""

        try:
            parsed = self.args_schema.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                call_id=call_id,
                tool_name=self.name,
                ok=False,
                status="rejected",
                error=f"工具参数校验失败：{exc}",
                error_code="invalid_tool_arguments",
            )

        try:
            data = to_json_value(await self.run(parsed))
            return ToolResult(
                call_id=call_id,
                tool_name=self.name,
                ok=True,
                data=data,
            )
        except Exception as exc:
            logger.warning(
                "tools.handler.failed tools={} error_type={}",
                self.name,
                type(exc).__name__,
            )
            error_code = (
                exc.code
                if isinstance(exc, ApplicationError)
                else "tool_execution_failed"
            )
            retryable = exc.retryable if isinstance(exc, ApplicationError) else False
            return ToolResult(
                call_id=call_id,
                tool_name=self.name,
                ok=False,
                status=(
                    "unavailable"
                    if isinstance(exc, DatabaseOperationError)
                    else "error"
                ),
                error=str(exc),
                error_code=error_code,
                retryable=retryable,
            )

    # 方法说明：run
    # 作用：执行工具的确定性逻辑。
    # 入参：
    #   arguments（ToolArgs）：按工具 Schema 校验后的调用参数。
    # 出参：JsonValue | BaseModel；JSON 兼容数据或符合当前契约的 Pydantic 模型。
    @abstractmethod
    async def run(self, arguments: ToolArgs) -> JsonValue | BaseModel:
        """执行工具的确定性逻辑。"""
