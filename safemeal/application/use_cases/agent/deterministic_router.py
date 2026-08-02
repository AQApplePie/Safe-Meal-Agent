"""Deterministic request guard that runs before the semantic planner.

Authorization boundaries are application invariants, not model instructions.  This
processor decorator handles unambiguous privilege-escalation and secret-exfiltration
requests without constructing or invoking an LLM-backed Agent.  All other requests are
delegated to the configured AgentProcessor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from safemeal.application.ports import AgentProcessor
from safemeal.application.contracts.agent import AgentProcessResponse
from safemeal.shared.contracts.agent_context import AgentContext


@dataclass(frozen=True, slots=True)
class DeterministicRouteDecision:
    """An application-level route that is safe to answer without a model."""

    route: str
    message: str
    reason: str


class AuthorizationRoutingPolicy:
    """Recognize explicit requests that cross the Agent's authority boundary."""

    _DESTRUCTIVE_REQUEST = re.compile(
        r"(?:绕过|跳过|无视|规避).{0,12}(?:权限|鉴权|授权|限制)"
        r"|(?:删除|清空|销毁|修改).{0,12}(?:全部|所有).{0,12}"
        r"(?:数据库|数据|菜谱|用户|记录)"
    )
    _SECRET_EXFILTRATION = re.compile(
        r"(?:输出|显示|泄露|透露|给我|打印|导出).{0,16}"
        r"(?:系统提示词|隐藏提示词|其他用户.{0,6}(?:隐私|数据)|密钥|密码|令牌)"
    )

    def decide(self, message: str) -> DeterministicRouteDecision | None:
        normalized = " ".join(message.strip().split())
        if self._DESTRUCTIVE_REQUEST.search(normalized):
            return DeterministicRouteDecision(
                route="authorization_guard",
                message=(
                    "不能执行该请求：本服务无权绕过鉴权、提升权限，或删除/修改"
                    "受保护的数据。你可以查询菜谱、获取饮食建议，或操作自己有权"
                    "访问的会话数据。"
                ),
                reason="privilege_escalation_or_destructive_action",
            )
        if self._SECRET_EXFILTRATION.search(normalized):
            return DeterministicRouteDecision(
                route="authorization_guard",
                message=(
                    "不能提供系统提示词、密钥或其他用户的隐私数据。"
                    "我只能处理当前已授权上下文中的菜谱与饮食安全请求。"
                ),
                reason="secret_or_cross_user_data_exfiltration",
            )
        return None


class DeterministicFirstAgentProcessor:
    """Apply deterministic routes first and delegate only ambiguous requests."""

    def __init__(
        self,
        fallback: AgentProcessor | None,
        *,
        authorization_policy: AuthorizationRoutingPolicy | None = None,
    ) -> None:
        self._fallback = fallback
        self._authorization_policy = (
            authorization_policy or AuthorizationRoutingPolicy()
        )

    async def process(
        self,
        message: str,
        session_id: str,
        *,
        context: AgentContext | None = None,
        include_trace: bool = False,
    ) -> AgentProcessResponse:
        decision = self._authorization_policy.decide(message)
        if decision is not None:
            return AgentProcessResponse(
                status="ok",
                message=decision.message,
                route=decision.route,
                route_logic="deterministic_authorization_policy",
                metadata={
                    "deterministic": True,
                    "policy_reason": decision.reason,
                },
            )

        if self._fallback is None:
            return AgentProcessResponse(
                status="error",
                message="Agent LLM is disabled",
                route="semantic_planner",
                route_logic="llm_required",
                error_code="feature_unavailable",
            )
        return await self._fallback.process(
            message,
            session_id,
            context=context,
            include_trace=include_trace,
        )


__all__ = [
    "AuthorizationRoutingPolicy",
    "DeterministicFirstAgentProcessor",
    "DeterministicRouteDecision",
]
