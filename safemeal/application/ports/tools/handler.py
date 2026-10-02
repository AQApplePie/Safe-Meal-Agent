"""本地工具运行时。

本模块负责工具说明、参数校验、超时控制和工具实现调度。
它不依赖 Agent 图内部状态，可由应用层稳定调用和独立测试。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError
from loguru import logger

from safemeal.application.exceptions import ApplicationError, DatabaseOperationError
from safemeal.application.contracts.tools.base import ToolResult, ToolSpecification
from safemeal.shared.types import JsonObject, JsonValue, to_json_object, to_json_value


ToolArgs = TypeVar("ToolArgs", bound=BaseModel)


class ToolHandler(Generic[ToolArgs], ABC):
    """本地具体工具的基础抽象。

    具体工具只需要声明名称、描述、参数模型，并实现 ``run``。运行时统一负责：

    - 生成 ToolSpecification；
    - 使用 Pydantic 校验参数；
    - 把返回值转换为 JSON 友好的 ToolResult。
    """

    name: str
    purpose: str
    use_when: tuple[str, ...]
    do_not_use_when: tuple[str, ...]
    input_constraints: tuple[str, ...]
    side_effects: tuple[str, ...] = ()
    requires_approval: bool = False
    idempotent: bool = True
    args_schema: type[ToolArgs]

    def _planner_description(self) -> str:
        """Build one readable description from the same structured metadata.

        Keeping this text derived from fields prevents the prompt description and
        the runtime/tool documentation from drifting into two contradictory copies.
        """

        sections = [
            f"用途：{self.purpose}",
            "适用场景：" + "；".join(self.use_when),
            "不要使用：" + "；".join(self.do_not_use_when),
            "输入约束：" + "；".join(self.input_constraints),
        ]
        if self.side_effects:
            sections.append("副作用：" + "；".join(self.side_effects))
        return "\n".join(sections)

    def specification(self) -> ToolSpecification:
        """Return the Planner contract generated from executable metadata."""

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

    @abstractmethod
    async def run(self, arguments: ToolArgs) -> JsonValue | BaseModel:
        """执行工具的确定性逻辑。"""
