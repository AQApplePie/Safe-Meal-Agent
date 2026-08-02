"""Expected chat-use-case failures safe for interface-layer mapping."""

from __future__ import annotations

from safemeal.application.errors import ApplicationError


class ChatError(ApplicationError):
    """Base class for expected chat failures."""


class ChatSessionNotFoundError(ChatError):
    """The session does not exist or is not owned by the supplied user."""

    public_message = "Chat session not found"


class ChatTurnConflictError(ChatError):
    """A request ID was reused incompatibly or its turn is still running."""

    public_message = "Chat turn conflict"


class ChatTurnInProgressError(ChatTurnConflictError):
    public_message = "Chat turn is already being processed"


class ChatRequestConflictError(ChatTurnConflictError):
    public_message = "request_id was already used with different request data"


class ChatAgentUnavailableError(ChatError):
    """The Agent failed after the user message was durably accepted."""

    public_message = "Agent is temporarily unavailable"

    def __init__(self, *, error_code: str | None = None) -> None:
        super().__init__(self.public_message)
        self.error_code = error_code or "agent_execution_failed"


__all__ = [
    "ChatAgentUnavailableError",
    "ChatError",
    "ChatRequestConflictError",
    "ChatSessionNotFoundError",
    "ChatTurnConflictError",
    "ChatTurnInProgressError",
]
