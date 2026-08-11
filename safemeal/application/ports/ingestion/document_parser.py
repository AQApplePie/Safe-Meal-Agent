"""Application contract for parsing uploaded knowledge documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DocumentParseError(ValueError):
    """The uploaded document cannot be converted into ingestible text."""


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    text: str
    parser: str


class DocumentParser(Protocol):
    def parse(self, filename: str, content: bytes) -> ParsedDocument: ...


__all__ = ["DocumentParseError", "DocumentParser", "ParsedDocument"]
