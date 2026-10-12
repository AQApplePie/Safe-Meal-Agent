"""实现文档摄取基础设施适配。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable

from safemeal.modules.knowledge.contracts.models import ParsedDocument
from safemeal.modules.knowledge.ports.ingestion.document_parser import (
    DocumentParseError,
)
from safemeal.config.settings import settings


Parser = Callable[[bytes], str]


# 方法说明：_decode_text
# 作用：尝试受支持的字符编码，将上传字节转换为文本。
# 入参：
#   content（bytes）：当前文件、消息或证据的正文内容。
# 出参：str；从上传文件解析出的正文文本。
def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("无法识别文本编码")


# 方法说明：_parse_pdf
# 作用：解析 PDF 页面的文本，用于知识库摄取。
# 入参：
#   content（bytes）：当前文件、消息或证据的正文内容。
# 出参：str；从上传文件解析出的正文文本。
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


# 方法说明：_parse_image
# 作用：通过 OCR 将图片文件解析为可摄取文本。
# 入参：
#   content（bytes）：当前文件、消息或证据的正文内容。
# 出参：str；从上传文件解析出的正文文本。
def _parse_image(content: bytes) -> str:
    try:
        from PIL import Image
        import pytesseract

        return pytesseract.image_to_string(
            Image.open(BytesIO(content)), lang=settings.OCR_LANGUAGES
        )
    except Exception as exc:
        raise DocumentParseError(f"图片 OCR 失败：{exc}") from exc


# 类说明（业务或基础设施实现类）：DocumentParserRegistry
# 作用：实现按文件类型路由的文档解析器，封装该组件的业务处理与依赖协作。
class DocumentParserRegistry:
    # 方法说明：__init__
    # 作用：初始化按文件类型路由的文档解析器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self) -> None:
        # 实例属性说明：_parsers
        # 作用：按文件扩展名映射解析器名称与解析函数的注册表。
        # 类型：dict[str, tuple[str, Parser]]。
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

    # 方法说明：parse
    # 作用：通过按文件类型路由的文档解析器解析输入并生成结构化结果。
    # 入参：
    #   filename（str）：上传文件的原始名称。
    #   content（bytes）：当前文件、消息或证据的正文内容。
    # 出参：ParsedDocument；上传文件解析后的文档。
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
