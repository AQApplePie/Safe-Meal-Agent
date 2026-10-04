"""Boundary for replaceable lightweight request-understanding backends."""

from typing import Protocol

from safemeal.application.contracts.conversation.models import ConversationHistory
from safemeal.application.contracts.workflow.request_frame import RequestFrame


class RequestUnderstandingGateway(Protocol):
    backend_name: str

    async def understand(
        self, message: str, recent_context: ConversationHistory
    ) -> RequestFrame: ...
