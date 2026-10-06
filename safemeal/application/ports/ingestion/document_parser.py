"""定义应用层依赖的能力端口。"""

from __future__ import annotations
from safemeal.application.contracts.upload.models import ParsedDocument

from typing import Protocol


class DocumentParseError(ValueError):
    """表示上传文档无法转换为可摄取文本。"""


class DocumentParser(Protocol):
    def parse(self, filename: str, content: bytes) -> ParsedDocument: ...


__all__ = ["DocumentParseError", "DocumentParser", "ParsedDocument"]
