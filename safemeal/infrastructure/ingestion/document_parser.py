"""Local TXT, Markdown and PDF document-parser adapter."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable

from safemeal.application.ports.ingestion.document_parser import (
    DocumentParseError,
    ParsedDocument,
)


Parser = Callable[[bytes], str]


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("无法识别文本编码")


def _parse_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        return "\n\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages
        )
    except Exception as exc:
        raise DocumentParseError(f"PDF 解析失败：{exc}") from exc


class DocumentParserRegistry:
    """Select one deterministic in-process parser by file suffix."""

    def __init__(self) -> None:
        self._parsers: dict[str, tuple[str, Parser]] = {
            ".txt": ("text", _decode_text),
            ".md": ("markdown", _decode_text),
            ".pdf": ("pypdf", _parse_pdf),
        }

    def parse(self, filename: str, content: bytes) -> ParsedDocument:
        suffix = Path(filename).suffix.casefold()
        registered = self._parsers.get(suffix)
        if registered is None:
            raise DocumentParseError("仅支持 TXT、Markdown 和 PDF 文件")
        name, parser = registered
        text = parser(content).strip()
        if not text:
            raise DocumentParseError("文档中没有可入库文本")
        return ParsedDocument(text=text, parser=name)


__all__ = ["DocumentParseError", "DocumentParserRegistry", "ParsedDocument"]
