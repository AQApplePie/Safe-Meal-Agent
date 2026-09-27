"""Local TXT, Markdown and PDF document-parser adapter."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable

from safemeal.application.contracts.upload.models import ParsedDocument
from safemeal.application.ports.ingestion.document_parser import DocumentParseError
from safemeal.config.settings import settings


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

        extracted = "\n\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages
        )
        if (
            len(extracted.strip()) >= settings.OCR_MIN_EXTRACTED_CHARS
            or not settings.OCR_ENABLED
        ):
            return extracted
        import fitz
        from PIL import Image
        import pytesseract

        document = fitz.open(stream=content, filetype="pdf")
        pages = []
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
            pages.append(
                pytesseract.image_to_string(image, lang=settings.OCR_LANGUAGES)
            )
        return "\n\n".join(pages)
    except Exception as exc:
        raise DocumentParseError(f"PDF 解析失败：{exc}") from exc


def _parse_image(content: bytes) -> str:
    try:
        from PIL import Image
        import pytesseract

        return pytesseract.image_to_string(
            Image.open(BytesIO(content)), lang=settings.OCR_LANGUAGES
        )
    except Exception as exc:
        raise DocumentParseError(f"图片 OCR 失败：{exc}") from exc


class DocumentParserRegistry:
    """Select one deterministic in-process parser by file suffix."""

    def __init__(self) -> None:
        self._parsers: dict[str, tuple[str, Parser]] = {
            ".txt": ("text", _decode_text),
            ".md": ("markdown", _decode_text),
            ".pdf": ("pypdf", _parse_pdf),
            ".png": ("tesseract", _parse_image),
            ".jpg": ("tesseract", _parse_image),
            ".jpeg": ("tesseract", _parse_image),
            ".tif": ("tesseract", _parse_image),
            ".tiff": ("tesseract", _parse_image),
        }

    def parse(self, filename: str, content: bytes) -> ParsedDocument:
        suffix = Path(filename).suffix.casefold()
        registered = self._parsers.get(suffix)
        if registered is None:
            raise DocumentParseError("仅支持 TXT、Markdown、PDF 和常见图片文件")
        name, parser = registered
        text = parser(content).strip()
        if not text:
            raise DocumentParseError("文档中没有可入库文本")
        return ParsedDocument(text=text, parser=name)


__all__ = ["DocumentParseError", "DocumentParserRegistry", "ParsedDocument"]
