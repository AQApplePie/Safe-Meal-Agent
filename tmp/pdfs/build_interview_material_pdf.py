from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents


ROOT = Path("/Users/aqapplepie/Desktop/my_project")
MATERIAL_ROOT = ROOT / "interview_ material"
BANK_ROOT = MATERIAL_ROOT / "技术栈面试题库"
OUTPUT = ROOT / "SafeMealAgent" / "output" / "pdf" / "BigMarket与SafeMealAgent技术栈面试题库.pdf"

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = 18 * mm
RIGHT = 18 * mm
TOP = 19 * mm
BOTTOM = 17 * mm

NAVY = colors.HexColor("#17365D")
BLUE = colors.HexColor("#1F5A94")
TEAL = colors.HexColor("#147D78")
TEXT = colors.HexColor("#202A35")
MUTED = colors.HexColor("#667085")
LIGHT = colors.HexColor("#E8EEF5")
CODE_BG = colors.HexColor("#F3F5F7")


def register_fonts() -> None:
    regular = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    mono = "/System/Library/Fonts/Menlo.ttc"
    pdfmetrics.registerFont(TTFont("CJK", regular))
    try:
        pdfmetrics.registerFont(TTFont("Mono", mono, subfontIndex=0))
    except Exception:
        pdfmetrics.registerFont(TTFont("Mono", regular))
    pdfmetrics.registerFontFamily("CJK", normal="CJK", bold="CJK", italic="CJK", boldItalic="CJK")


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="CJK",
            fontSize=25,
            leading=34,
            alignment=TA_CENTER,
            textColor=NAVY,
            spaceAfter=12 * mm,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName="CJK",
            fontSize=11,
            leading=18,
            alignment=TA_CENTER,
            textColor=MUTED,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="CJK",
            fontSize=18,
            leading=25,
            textColor=NAVY,
            spaceBefore=3 * mm,
            spaceAfter=5 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="CJK",
            fontSize=13,
            leading=19,
            textColor=BLUE,
            spaceBefore=5 * mm,
            spaceAfter=2.5 * mm,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontName="CJK",
            fontSize=11.5,
            leading=17,
            textColor=TEAL,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="CJK",
            fontSize=9.1,
            leading=14.5,
            alignment=TA_JUSTIFY,
            textColor=TEXT,
            spaceAfter=1.8 * mm,
            splitLongWords=True,
        ),
        "question": ParagraphStyle(
            "Question",
            parent=base["BodyText"],
            fontName="CJK",
            fontSize=9.8,
            leading=15.2,
            textColor=NAVY,
            leftIndent=1 * mm,
            spaceBefore=2.5 * mm,
            spaceAfter=1 * mm,
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="CJK",
            fontSize=8.9,
            leading=14.2,
            textColor=TEXT,
            leftIndent=6.5 * mm,
            firstLineIndent=-3.5 * mm,
            bulletIndent=2.5 * mm,
            spaceAfter=1.0 * mm,
            splitLongWords=True,
        ),
        "ordered": ParagraphStyle(
            "Ordered",
            parent=base["BodyText"],
            fontName="CJK",
            fontSize=8.9,
            leading=14.2,
            textColor=TEXT,
            leftIndent=7 * mm,
            firstLineIndent=-5 * mm,
            spaceAfter=1.2 * mm,
        ),
        "quote": ParagraphStyle(
            "Quote",
            parent=base["BodyText"],
            fontName="CJK",
            fontSize=8.8,
            leading=14,
            textColor=MUTED,
            leftIndent=7 * mm,
            rightIndent=4 * mm,
            borderColor=TEAL,
            borderWidth=1.2,
            borderPadding=(2 * mm, 3 * mm, 2 * mm, 3 * mm),
            backColor=colors.HexColor("#F5FAFA"),
            spaceAfter=2 * mm,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="Mono",
            fontSize=7.3,
            leading=10.5,
            textColor=colors.HexColor("#263238"),
            leftIndent=4 * mm,
            rightIndent=4 * mm,
            borderPadding=3 * mm,
            backColor=CODE_BG,
            spaceBefore=1.5 * mm,
            spaceAfter=2.5 * mm,
            splitLongWords=True,
        ),
        "toc_title": ParagraphStyle(
            "TOCTitle",
            parent=base["Heading1"],
            fontName="CJK",
            fontSize=20,
            leading=28,
            textColor=NAVY,
            spaceAfter=7 * mm,
        ),
        "toc_entry": ParagraphStyle(
            "TOCEntry",
            parent=base["Normal"],
            fontName="CJK",
            fontSize=9.5,
            leading=15,
            leftIndent=0,
            firstLineIndent=0,
            textColor=TEXT,
        ),
    }


def local_href(source_file: Path, target: str, chapter_targets: dict[str, str]) -> str | None:
    if target.startswith(("http://", "https://", "mailto:")):
        return target
    if target.startswith("#"):
        return target
    raw_path, _, fragment = target.partition("#")
    if raw_path in chapter_targets:
        return f"#{chapter_targets[raw_path]}"
    if raw_path == "项目题源码定位索引.md" and fragment:
        return f"#{fragment}"
    if not raw_path:
        return f"#{fragment}" if fragment else None
    resolved = (source_file.parent / raw_path).resolve()
    if resolved.exists():
        return "file://" + quote(str(resolved))
    return None


def inline_markup(text: str, source_file: Path, chapter_targets: dict[str, str]) -> str:
    tokens: list[str] = []

    def reserve(value: str) -> str:
        tokens.append(value)
        return f"@@TOKEN{len(tokens) - 1}@@"

    def repl_code(match: re.Match[str]) -> str:
        return reserve(f'<font name="Mono" color="#344054">{html.escape(match.group(1))}</font>')

    text = re.sub(r"`([^`]+)`", repl_code, text)

    def repl_link(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        href = local_href(source_file, target, chapter_targets)
        safe_label = html.escape(label)
        if href:
            return reserve(f'<link href="{html.escape(href, quote=True)}" color="#1F5A94"><u>{safe_label}</u></link>')
        return reserve(safe_label)

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", repl_link, text)
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = text.replace(" -> ", " → ")
    # Link labels can contain inline-code placeholders. Restore the outer link
    # token first and the nested code token afterwards.
    for index in reversed(range(len(tokens))):
        token = tokens[index]
        text = text.replace(f"@@TOKEN{index}@@", token)
    return text


class InterviewDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, styles: dict[str, ParagraphStyle]) -> None:
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=LEFT,
            rightMargin=RIGHT,
            topMargin=TOP,
            bottomMargin=BOTTOM,
            title="BigMarket 与 SafeMealAgent 技术栈面试题库",
            author="Interview Material",
            subject="技术栈术语、面试题答案与项目源码定位",
        )
        self.styles = styles
        frame = Frame(LEFT, BOTTOM, PAGE_WIDTH - LEFT - RIGHT, PAGE_HEIGHT - TOP - BOTTOM, id="body")
        self.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=self.draw_header_footer))
        self._heading_counter = 0

    def draw_header_footer(self, canvas, doc) -> None:
        canvas.saveState()
        if doc.page > 1:
            canvas.setStrokeColor(LIGHT)
            canvas.line(LEFT, PAGE_HEIGHT - 12 * mm, PAGE_WIDTH - RIGHT, PAGE_HEIGHT - 12 * mm)
            canvas.setFont("CJK", 7.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(LEFT, PAGE_HEIGHT - 9.5 * mm, "BigMarket 与 SafeMealAgent 技术栈面试题库")
            canvas.drawRightString(PAGE_WIDTH - RIGHT, 9 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:
        if not isinstance(flowable, Paragraph):
            return
        if flowable.style.name != "H1":
            return
        self._heading_counter += 1
        key = getattr(flowable, "_bookmark_name", f"heading-{self._heading_counter}")
        text = flowable.getPlainText()
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=0, closed=False)
        self.notify("TOCEntry", (0, text, self.page, key))


def paragraph(text: str, style: ParagraphStyle, source: Path, chapter_targets: dict[str, str], **kwargs) -> Paragraph:
    return Paragraph(inline_markup(text, source, chapter_targets), style, **kwargs)


def parse_markdown(
    path: Path,
    styles: dict[str, ParagraphStyle],
    chapter_targets: dict[str, str],
    chapter_key: str,
) -> list:
    lines = path.read_text(encoding="utf-8").splitlines()
    story: list = []
    paragraph_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False
    first_h1 = True

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            story.append(paragraph(" ".join(x.strip() for x in paragraph_lines), styles["body"], path, chapter_targets))
            paragraph_lines = []

    for line in lines:
        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                code_text = "<br/>".join(html.escape(x).replace(" ", "&nbsp;") for x in code_lines) or " "
                story.append(Paragraph(code_text, styles["code"]))
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue

        anchor = re.fullmatch(r'<a id="([^"]+)"></a>', line.strip())
        if anchor:
            flush_paragraph()
            story.append(Paragraph(f'<a name="{html.escape(anchor.group(1))}"/>', styles["body"]))
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            text = heading.group(2).strip()
            item = paragraph(text, styles[f"h{level}"], path, chapter_targets)
            if level == 1 and first_h1:
                item._bookmark_name = chapter_key
                first_h1 = False
            story.append(item)
            continue

        question = re.match(r"^(\d+)\.\s+\*\*(.+)\*\*\s*$", line)
        if question:
            flush_paragraph()
            q = Paragraph(
                f'<b>{html.escape(question.group(1))}. {inline_markup(question.group(2), path, chapter_targets)}</b>',
                styles["question"],
            )
            story.append(q)
            continue

        bullet = re.match(r"^\s*-\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            story.append(paragraph(bullet.group(1), styles["bullet"], path, chapter_targets, bulletText="-"))
            continue

        ordered = re.match(r"^(\d+)\.\s+(.+)$", line)
        if ordered:
            flush_paragraph()
            story.append(paragraph(f"{ordered.group(1)}. {ordered.group(2)}", styles["ordered"], path, chapter_targets))
            continue

        quote_line = re.match(r"^>\s?(.*)$", line)
        if quote_line:
            flush_paragraph()
            story.append(paragraph(quote_line.group(1), styles["quote"], path, chapter_targets))
            continue

        if not line.strip():
            flush_paragraph()
            continue

        paragraph_lines.append(line)

    flush_paragraph()
    if code_lines:
        code_text = "<br/>".join(html.escape(x).replace(" ", "&nbsp;") for x in code_lines)
        story.append(Paragraph(code_text, styles["code"]))
    return story


def build() -> None:
    register_fonts()
    styles = make_styles()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    files = [
        BANK_ROOT / "README.md",
        MATERIAL_ROOT / "BigMarket与SafeMealAgent技术栈总结.md",
        BANK_ROOT / "00-术语解析与作答规范.md",
        *sorted(BANK_ROOT.glob("[0-9][0-9]-*.md"))[1:],
        BANK_ROOT / "项目题源码定位索引.md",
    ]
    # sorted glob includes 00; it is already inserted explicitly.
    assert all(path.exists() for path in files), [str(path) for path in files if not path.exists()]

    chapter_targets: dict[str, str] = {
        path.name: f"chapter-{index}" for index, path in enumerate(files)
    }

    story: list = [
        Spacer(1, 45 * mm),
        Paragraph("BigMarket 与 SafeMealAgent<br/>技术栈面试题库", styles["cover_title"]),
        Paragraph("术语解析 · 907 道面试题 · 项目源码定位", styles["cover_subtitle"]),
        Spacer(1, 16 * mm),
        Paragraph("整合范围：项目技术栈总结、答题规范、28 个专题与项目题源码索引", styles["cover_subtitle"]),
        Spacer(1, 7 * mm),
        Paragraph(f"生成日期：{date.today().isoformat()}", styles["cover_subtitle"]),
        PageBreak(),
        Paragraph("目录", styles["toc_title"]),
    ]

    toc = TableOfContents()
    toc.levelStyles = [styles["toc_entry"]]
    toc.dotsMinLevel = 0
    story.extend([toc, PageBreak()])

    for index, path in enumerate(files):
        if index:
            story.append(PageBreak())
        story.extend(parse_markdown(path, styles, chapter_targets, f"chapter-{index}"))

    doc = InterviewDocTemplate(str(OUTPUT), styles)
    doc.multiBuild(story)
    print(OUTPUT)


if __name__ == "__main__":
    build()
