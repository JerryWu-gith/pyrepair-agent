from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

PAGE_WIDTH, PAGE_HEIGHT = A4
NAVY = colors.HexColor("#16324A")
BLUE = colors.HexColor("#1E6091")
TEAL = colors.HexColor("#1F9D8A")
CYAN = colors.HexColor("#57C4D0")
INK = colors.HexColor("#263642")
MUTED = colors.HexColor("#617483")
RULE = colors.HexColor("#CBD9E2")
PALE_BLUE = colors.HexColor("#EAF3F8")
PALE_TEAL = colors.HexColor("#E9F7F3")
PALE_AMBER = colors.HexColor("#FFF5DC")
CODE_BG = colors.HexColor("#F4F7F9")
WHITE = colors.white


def register_fonts() -> None:
    font_dir = Path(r"C:\Windows\Fonts")
    required = {
        "CJK": font_dir / "Deng.ttf",
        "CJK-Bold": font_dir / "Dengb.ttf",
        "Code": font_dir / "CascadiaMono.ttf",
    }
    missing = [str(path) for path in required.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required fonts are missing: {missing}")
    for name, path in required.items():
        pdfmetrics.registerFont(TTFont(name, str(path)))


def normalize_text(value: str) -> str:
    return (
        value.replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\t", "    ")
    )


def inline_markup(value: str) -> str:
    value = normalize_text(value)
    parts = re.split(r"(`[^`]*`)", value)
    rendered: list[str] = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            rendered.append(
                f'<font name="Code" color="#135B7B">{html.escape(part[1:-1])}</font>'
            )
            continue
        escaped = html.escape(part)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        escaped = escaped.replace("[ ]", "□").replace("[x]", "■")
        rendered.append(escaped)
    return "".join(rendered)


class LearningGuideTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs: Any) -> None:
        super().__init__(filename, **kwargs)
        self._heading_counter = 0
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(
            [PageTemplate(id="learning-guide", frames=[frame], onPage=draw_page)]
        )

    def beforeDocument(self) -> None:
        self._heading_counter = 0

    def afterFlowable(self, flowable: Any) -> None:
        if not isinstance(flowable, Paragraph):
            return
        level = getattr(flowable, "toc_level", None)
        if level is None:
            return
        self._heading_counter += 1
        text = flowable.getPlainText()
        key = f"heading-{self._heading_counter}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=level == 0)
        self.notify("TOCEntry", (level, text, self.page, key))


def draw_page(canvas: Any, doc: LearningGuideTemplate) -> None:
    canvas.saveState()
    page = canvas.getPageNumber()
    if page == 1:
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        canvas.setFillColor(TEAL)
        canvas.rect(0, PAGE_HEIGHT - 11 * mm, PAGE_WIDTH, 11 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#10283C"))
        canvas.circle(PAGE_WIDTH - 24 * mm, 49 * mm, 52 * mm, fill=1, stroke=0)
        canvas.setStrokeColor(CYAN)
        canvas.setLineWidth(1.2)
        for offset in range(0, 70, 12):
            canvas.line(
                PAGE_WIDTH - (80 - offset) * mm,
                22 * mm,
                PAGE_WIDTH - (28 - offset / 3) * mm,
                82 * mm,
            )
        canvas.setFillColor(WHITE)
        canvas.setFont("CJK-Bold", 29)
        canvas.drawString(22 * mm, PAGE_HEIGHT - 64 * mm, "PyRepair Agent")
        canvas.setFont("CJK-Bold", 21)
        canvas.drawString(22 * mm, PAGE_HEIGHT - 80 * mm, "十天实战学习手册")
        canvas.setStrokeColor(CYAN)
        canvas.setLineWidth(2.5)
        canvas.line(22 * mm, PAGE_HEIGHT - 91 * mm, 109 * mm, PAGE_HEIGHT - 91 * mm)
        canvas.setFillColor(colors.HexColor("#D6E8F0"))
        canvas.setFont("CJK", 11)
        canvas.drawString(22 * mm, PAGE_HEIGHT - 108 * mm, "从会运行，到能解释、能调试、能改进、能面试")
        canvas.setFont("CJK", 10)
        canvas.drawString(22 * mm, PAGE_HEIGHT - 119 * mm, "10天 × 每天4-6小时  |  Python / pytest / Agent开发")
        canvas.setFillColor(TEAL)
        canvas.roundRect(22 * mm, PAGE_HEIGHT - 144 * mm, 52 * mm, 10 * mm, 2 * mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont("CJK-Bold", 9)
        canvas.drawCentredString(48 * mm, PAGE_HEIGHT - 140.8 * mm, "实战路线 A")
        canvas.setFillColor(colors.HexColor("#9EC6D6"))
        canvas.setFont("Code", 8.5)
        canvas.drawString(22 * mm, 30 * mm, "PYREPAIR LEARNING GUIDE  /  VERSION 1.0")
        canvas.setFillColor(WHITE)
        canvas.setFont("CJK", 9)
        canvas.drawRightString(PAGE_WIDTH - 22 * mm, 20 * mm, "2026-08-12")
    else:
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.55)
        canvas.line(doc.leftMargin, PAGE_HEIGHT - 16 * mm, PAGE_WIDTH - doc.rightMargin, PAGE_HEIGHT - 16 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("CJK", 8.2)
        canvas.drawString(doc.leftMargin, PAGE_HEIGHT - 12 * mm, "PyRepair Agent  |  十天实战学习手册")
        canvas.setFont("CJK", 8)
        canvas.drawRightString(PAGE_WIDTH - doc.rightMargin, 11 * mm, f"{page:02d}")
        canvas.setStrokeColor(RULE)
        canvas.line(doc.leftMargin, 16 * mm, PAGE_WIDTH - doc.rightMargin, 16 * mm)
    canvas.restoreState()


def build_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "toc_title": ParagraphStyle(
            "TOCTitle",
            parent=sample["Title"],
            fontName="CJK-Bold",
            fontSize=24,
            leading=31,
            textColor=NAVY,
            spaceAfter=7 * mm,
        ),
        "toc_intro": ParagraphStyle(
            "TOCIntro",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=9.5,
            leading=15,
            textColor=MUTED,
            backColor=PALE_BLUE,
            borderColor=RULE,
            borderWidth=0.5,
            borderPadding=8,
            spaceAfter=5 * mm,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=sample["Heading1"],
            fontName="CJK-Bold",
            fontSize=18,
            leading=24,
            textColor=NAVY,
            spaceBefore=3 * mm,
            spaceAfter=4 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=sample["Heading2"],
            fontName="CJK-Bold",
            fontSize=12.5,
            leading=18,
            textColor=BLUE,
            spaceBefore=4 * mm,
            spaceAfter=2.2 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=9.6,
            leading=15.2,
            textColor=INK,
            alignment=TA_LEFT,
            wordWrap="CJK",
            spaceAfter=2.1 * mm,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=9.3,
            leading=14.7,
            textColor=INK,
            leftIndent=5.5 * mm,
            firstLineIndent=-3.5 * mm,
            bulletIndent=1.2 * mm,
            wordWrap="CJK",
            spaceAfter=1.2 * mm,
        ),
        "numbered": ParagraphStyle(
            "Numbered",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=9.3,
            leading=14.7,
            textColor=INK,
            leftIndent=7 * mm,
            firstLineIndent=-5 * mm,
            wordWrap="CJK",
            spaceAfter=1.2 * mm,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=sample["Code"],
            fontName="CJK",
            fontSize=7.5,
            leading=10.6,
            textColor=colors.HexColor("#20343F"),
            backColor=CODE_BG,
            borderColor=RULE,
            borderWidth=0.55,
            borderPadding=7,
            leftIndent=1.5 * mm,
            rightIndent=1.5 * mm,
            spaceBefore=1.2 * mm,
            spaceAfter=3 * mm,
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=9.5,
            leading=15.2,
            textColor=INK,
            borderColor=TEAL,
            borderWidth=0.8,
            borderPadding=9,
            leftIndent=1.5 * mm,
            rightIndent=1.5 * mm,
            backColor=PALE_TEAL,
            spaceBefore=1.5 * mm,
            spaceAfter=3.5 * mm,
        ),
        "table_head": ParagraphStyle(
            "TableHead",
            parent=sample["BodyText"],
            fontName="CJK-Bold",
            fontSize=7.8,
            leading=11.2,
            textColor=WHITE,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "table_body": ParagraphStyle(
            "TableBody",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=7.6,
            leading=11.2,
            textColor=INK,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
    }


def add_heading(
    story: list[Any], text: str, style: ParagraphStyle, level: int | None
) -> None:
    paragraph = Paragraph(inline_markup(text), style)
    if level is not None:
        paragraph.toc_level = level
    story.append(paragraph)


def parse_table(lines: list[str], styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    column_count = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (column_count - len(row)))

    weights: list[float] = []
    for index in range(column_count):
        longest = max(len(row[index]) for row in rows)
        weights.append(min(max(longest, 8), 34))
    total_weight = sum(weights)
    widths = [doc_width * weight / total_weight for weight in weights]

    data: list[list[Paragraph]] = []
    for row_index, row in enumerate(rows):
        style = styles["table_head"] if row_index == 0 else styles["table_body"]
        data.append([Paragraph(inline_markup(cell), style) for cell in row])

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("BACKGROUND", (0, 1), (-1, -1), WHITE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE_BLUE]),
                ("GRID", (0, 0), (-1, -1), 0.45, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def markdown_to_flowables(
    markdown: str, styles: dict[str, ParagraphStyle], doc_width: float
) -> list[Any]:
    lines = markdown.splitlines()
    story: list[Any] = []
    paragraph_lines: list[str] = []
    code_lines: list[str] = []
    callout_lines: list[str] = []
    table_lines: list[str] = []
    in_code = False
    seen_title = False

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            text = "".join(line.strip() for line in paragraph_lines)
            story.append(Paragraph(inline_markup(text), styles["body"]))
            paragraph_lines = []

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines:
            code = normalize_text("\n".join(code_lines).rstrip())
            story.append(Preformatted(code, styles["code"], maxLineLength=91))
            code_lines = []

    def flush_callout() -> None:
        nonlocal callout_lines
        if callout_lines:
            tag_match = re.fullmatch(r"\[!(\w+)\]", callout_lines[0].strip())
            tag = tag_match.group(1) if tag_match else "NOTE"
            body_lines = callout_lines[1:] if tag_match else callout_lines
            labels = {
                "GOAL": "学习目标",
                "RULE": "学习规则",
                "SAFETY": "安全提醒",
                "TIP": "学习提示",
                "INTERVIEW": "面试提示",
                "NOTE": "说明",
            }
            label = labels.get(tag, "说明")
            text = "".join(line.strip() for line in body_lines)
            content = f'<b><font color="#147A6B">{label}</font></b><br/>{inline_markup(text)}'
            story.append(KeepTogether([Paragraph(content, styles["callout"])]))
            callout_lines = []

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            story.append(parse_table(table_lines, styles, doc_width))
            story.append(Spacer(1, 3 * mm))
            table_lines = []

    for line in lines:
        if line.startswith("# ") and not seen_title:
            seen_title = True
            continue
        if not seen_title:
            continue
        if line.startswith(("副标题：", "适用对象：", "学习周期：", "项目目录：")):
            continue
        if line.strip() == "<!-- PAGEBREAK -->":
            flush_paragraph()
            flush_callout()
            flush_table()
            story.append(CondPageBreak(75 * mm))
            continue
        if line.startswith("```"):
            flush_paragraph()
            flush_callout()
            flush_table()
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith(">"):
            flush_paragraph()
            flush_table()
            callout_lines.append(line[1:].lstrip())
            continue
        flush_callout()
        if line.startswith("|") and line.rstrip().endswith("|"):
            flush_paragraph()
            table_lines.append(line)
            continue
        flush_table()
        if line.startswith("## "):
            flush_paragraph()
            add_heading(story, line[3:].strip(), styles["h1"], 0)
            continue
        if line.startswith("### "):
            flush_paragraph()
            add_heading(story, line[4:].strip(), styles["h2"], None)
            continue
        bullet_match = re.match(r"^-\s+(.+)$", line)
        if bullet_match:
            flush_paragraph()
            story.append(
                Paragraph(inline_markup(bullet_match.group(1)), styles["bullet"], bulletText="•")
            )
            continue
        numbered_match = re.match(r"^(\d+)\.\s+(.+)$", line)
        if numbered_match:
            flush_paragraph()
            story.append(
                Paragraph(
                    f'<b>{numbered_match.group(1)}.</b> {inline_markup(numbered_match.group(2))}',
                    styles["numbered"],
                )
            )
            continue
        if not line.strip():
            flush_paragraph()
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    flush_code()
    flush_callout()
    flush_table()
    return story


def build_pdf(source: Path, output: Path) -> None:
    register_fonts()
    styles = build_styles()
    markdown = source.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = LearningGuideTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=21 * mm,
        title="PyRepair Agent 十天实战学习手册",
        author="JerryWu-gith",
        subject="PyRepair Agent项目学习、调试、改进与面试实战路线",
        keywords="PyRepair, Agent, DeepSeek, pytest, Tool Calling, Python",
    )

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOC1",
            fontName="CJK-Bold",
            fontSize=9.3,
            leading=13.2,
            textColor=NAVY,
            leftIndent=0,
            firstLineIndent=0,
            spaceBefore=0.6 * mm,
        ),
        ParagraphStyle(
            "TOC2",
            fontName="CJK",
            fontSize=8.2,
            leading=12.4,
            textColor=MUTED,
            leftIndent=7 * mm,
            firstLineIndent=0,
        ),
    ]

    story: list[Any] = [
        PageBreak(),
        Paragraph("目录", styles["toc_title"]),
        Paragraph(
            "建议按天执行，不要跳过动手任务和完成标准。阅读源码时始终把实现、测试和一次真实运行证据放在一起。",
            styles["toc_intro"],
        ),
        toc,
        PageBreak(),
    ]
    story.extend(markdown_to_flowables(markdown, styles, doc.width))
    doc.multiBuild(story)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the PyRepair ten-day learning guide PDF")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_pdf(args.source, args.output)
