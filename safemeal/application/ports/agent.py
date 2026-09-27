"""The only dependency of the chat workflow on an Agent system."""

from typing import Protocol
from safemeal.application.contracts.agent.api import AgentProcessResponse, AgentResumeResult
from safemeal.application.contracts.agent.context import AgentContext


class AgentInvoker(Protocol):
    async def process(
        self,
        message: str,
        session_id: str,
        *,
        context: AgentContext | None = None,
        include_trace: bool = False,
    ) -> AgentProcessResponse: ...


class ResumableAgent(AgentInvoker, Protocol):
    async def resume(
        self, session_id: str, *, approved: bool
    ) -> "AgentResumeResult": ...
