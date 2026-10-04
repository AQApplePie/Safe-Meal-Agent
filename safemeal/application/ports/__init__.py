"""Application-facing capability boundaries and persistence contracts."""

from safemeal.application.ports.persistence.chat_repository import (
    ChatMessageRepository,
    ChatSessionRepository,
    ChatUnitOfWork,
    ChatUnitOfWorkFactory,
)
from safemeal.application.ports.retrieval.document_embedder import DocumentEmbedder
from safemeal.application.ports.retrieval.document_reranker import DocumentReranker
from safemeal.application.contracts.upload.models import ParsedDocument
from safemeal.application.ports.ingestion.document_parser import (
    DocumentParseError,
    DocumentParser,
)
from safemeal.application.ports.persistence.recipe_repository import RecipeRepository
from safemeal.application.ports.ingestion.upload_storage import UploadStorage
from safemeal.application.ports.tools.tool_executor import ToolExecutor
from safemeal.application.ports.persistence.user_memory_repository import (
    UserMemoryRepository,
    UserMemoryUnitOfWork,
    UserMemoryUnitOfWorkFactory,
)
from safemeal.application.ports.retrieval.vector_document_repository import (
    VectorDocumentRepository,
)
from safemeal.application.ports.retrieval.lexical_document_repository import (
    LexicalDocumentRepository,
)

__all__ = [
    "ChatMessageRepository",
    "ChatSessionRepository",
    "ChatUnitOfWork",
    "ChatUnitOfWorkFactory",
    "DocumentParseError",
    "DocumentParser",
    "DocumentEmbedder",
    "DocumentReranker",
    "RecipeRepository",
    "ParsedDocument",
    "ToolExecutor",
    "UploadStorage",
    "UserMemoryRepository",
    "UserMemoryUnitOfWork",
    "UserMemoryUnitOfWorkFactory",
    "VectorDocumentRepository",
    "LexicalDocumentRepository",
]
