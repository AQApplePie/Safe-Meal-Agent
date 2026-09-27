"""Application contract for parsing uploaded knowledge documents."""

from __future__ import annotations
from safemeal.application.contracts.upload.models import ParsedDocument

from typing import Protocol


class DocumentParseError(ValueError):
    """The uploaded document cannot be converted into ingestible text."""


class DocumentParser(Protocol):
    def parse(self, filename: str, content: bytes) -> ParsedDocument: ...


__all__ = ["DocumentParseError", "DocumentParser", "ParsedDocument"]
