"""File upload storage port."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class UploadStorage(Protocol):
    """Storage capability required by UploadService."""

    async def write(self, relative_path: str, content: bytes) -> Path: ...

    def resolve(self, relative_path: str) -> Path: ...

    def find_by_prefix(self, prefix: str) -> Path | None: ...

    def delete(self, path: Path) -> None: ...
