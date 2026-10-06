"""定义应用层依赖的能力端口。"""

from typing import Protocol

from safemeal.application.contracts.conversation.models import ConversationHistory
from safemeal.application.contracts.workflow.request_frame import RequestFrame


class RequestUnderstandingGateway(Protocol):
    backend_name: str

    async def understand(
        self, message: str, recent_context: ConversationHistory
    ) -> RequestFrame: ...
