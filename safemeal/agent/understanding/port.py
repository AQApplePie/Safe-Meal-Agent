"""定义应用层依赖的能力端口。"""

from typing import Protocol

from safemeal.modules.conversation.contracts.conversation.models import ConversationHistory
from safemeal.shared.contracts.request_frame import RequestFrame


class RequestUnderstandingGateway(Protocol):
    backend_name: str

    async def understand(
        self, message: str, recent_context: ConversationHistory
    ) -> RequestFrame: ...
