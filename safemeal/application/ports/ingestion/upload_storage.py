"""File upload storage port."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from safemeal.application.contracts.upload.models import UploadedDocumentRecord


class UploadStorage(Protocol):
    """Storage capability required by FileUploadService."""

    async def write(self, relative_path: str, content: bytes) -> Path: ...

    def resolve(self, relative_path: str) -> Path: ...

    def find_by_prefix(self, prefix: str) -> Path | None: ...

    def delete(self, path: Path) -> None: ...

    def save_record(self, record: UploadedDocumentRecord) -> None: ...

    def get_record(self, file_id: str) -> UploadedDocumentRecord | None: ...

    def list_records(self, tenant_id: str) -> list[UploadedDocumentRecord]: ...

    def delete_record(self, file_id: str) -> None: ...
