from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
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
    Preformatted,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents


PAGE_WIDTH, PAGE_HEIGHT = A4
NAVY = colors.HexColor("#15324B")
BLUE = colors.HexColor("#2166A5")
CYAN = colors.HexColor("#28A7B8")
INK = colors.HexColor("#243442")
MUTED = colors.HexColor("#657786")
PALE_BLUE = colors.HexColor("#EAF3FA")
CODE_BG = colors.HexColor("#F3F6F8")
RULE = colors.HexColor("#CFDCE5")


def register_fonts() -> None:
    font_dir = Path(r"C:\Windows\Fonts")
    pdfmetrics.registerFont(TTFont("CJK", str(font_dir / "Deng.ttf")))
    pdfmetrics.registerFont(TTFont("CJK-Bold", str(font_dir / "Dengb.ttf")))
    pdfmetrics.registerFont(TTFont("Code", str(font_dir / "CascadiaMono.ttf")))
    pdfmetrics.registerFont(TTFont("Code-Bold", str(font_dir / "consolab.ttf")))


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
                f'<font name="Code" color="#174D74">{html.escape(part[1:-1])}</font>'
            )
        else:
            escaped = html.escape(part)
            escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
            rendered.append(escaped)
    return "".join(rendered)


class PyRepairDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs) -> None:
        super().__init__(filename, **kwargs)
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
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=draw_page)])

    def afterFlowable(self, flowable) -> None:  # noqa: ANN001
        if not isinstance(flowable, Paragraph):
            return
        level = getattr(flowable, "toc_level", None)
        if level is None:
            return
        text = flowable.getPlainText()
        key = f"heading-{level}-{self.page}-{abs(hash(text))}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=False)
        self.notify("TOCEntry", (level, text, self.page, key))


def draw_page(canvas, doc) -> None:  # noqa: ANN001
    canvas.saveState()
    page = canvas.getPageNumber()
    if page == 1:
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        canvas.setFillColor(CYAN)
        canvas.rect(0, PAGE_HEIGHT - 10 * mm, PAGE_WIDTH, 10 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("CJK-Bold", 31)
        canvas.drawString(24 * mm, PAGE_HEIGHT - 69 * mm, "PyRepair Agent")
        canvas.setFont("CJK-Bold", 20)
        canvas.drawString(24 * mm, PAGE_HEIGHT - 84 * mm, "测试诊断与候选补丁生成智能体")
        canvas.setStrokeColor(CYAN)
        canvas.setLineWidth(2.2)
        canvas.line(24 * mm, PAGE_HEIGHT - 94 * mm, 112 * mm, PAGE_HEIGHT - 94 * mm)
        canvas.setFillColor(colors.HexColor("#D9E8F2"))
        canvas.setFont("CJK", 11)
        canvas.drawString(24 * mm, PAGE_HEIGHT - 111 * mm, "MVP 产品与工程设计说明")
        canvas.drawString(24 * mm, PAGE_HEIGHT - 121 * mm, "目标：14天完成可安装、可评测、可接入CI的第一版")
        canvas.setFillColor(CYAN)
        canvas.setFont("CJK-Bold", 10)
        canvas.drawString(24 * mm, PAGE_HEIGHT - 134 * mm, "状态：设计已批准")
        canvas.setFillColor(colors.HexColor("#9FC5D8"))
        canvas.setFont("Code", 9)
        canvas.drawString(24 * mm, 36 * mm, "DESIGN SPECIFICATION  /  VERSION 1.0")
        canvas.setFillColor(colors.white)
        canvas.setFont("CJK", 9.5)
        canvas.drawRightString(PAGE_WIDTH - 24 * mm, 25 * mm, "2026-08-12")
    else:
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.6)
        canvas.line(doc.leftMargin, PAGE_HEIGHT - 16 * mm, PAGE_WIDTH - doc.rightMargin, PAGE_HEIGHT - 16 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("CJK", 8.5)
        canvas.drawString(doc.leftMargin, PAGE_HEIGHT - 12 * mm, "PyRepair Agent  |  设计说明")
        canvas.setFont("Code", 8)
        canvas.drawRightString(PAGE_WIDTH - doc.rightMargin, 11 * mm, f"{page - 1:02d}")
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
            alignment=TA_LEFT,
            spaceAfter=8 * mm,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=sample["Heading1"],
            fontName="CJK-Bold",
            fontSize=18,
            leading=24,
            textColor=NAVY,
            spaceBefore=7 * mm,
            spaceAfter=3.5 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=sample["Heading2"],
            fontName="CJK-Bold",
            fontSize=13,
            leading=18,
            textColor=BLUE,
            spaceBefore=5 * mm,
            spaceAfter=2.2 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=10.2,
            leading=16.2,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=2.2 * mm,
            wordWrap="CJK",
        ),
        "body_keep": ParagraphStyle(
            "BodyKeep",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=10.2,
            leading=16.2,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=2.2 * mm,
            wordWrap="CJK",
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=9.8,
            leading=15.2,
            textColor=INK,
            leftIndent=5.5 * mm,
            firstLineIndent=-3.5 * mm,
            bulletIndent=1.5 * mm,
            spaceAfter=1.2 * mm,
            wordWrap="CJK",
        ),
        "numbered": ParagraphStyle(
            "Numbered",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=9.8,
            leading=15.2,
            textColor=INK,
            leftIndent=7 * mm,
            firstLineIndent=-5 * mm,
            spaceAfter=1.2 * mm,
            wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "CodeBlock",
            parent=sample["Code"],
            fontName="Code",
            fontSize=7.5,
            leading=11.2,
            textColor=colors.HexColor("#263642"),
            backColor=CODE_BG,
            borderColor=RULE,
            borderWidth=0.6,
            borderPadding=8,
            leftIndent=1.5 * mm,
            rightIndent=1.5 * mm,
            spaceBefore=1.5 * mm,
            spaceAfter=3.2 * mm,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=sample["BodyText"],
            fontName="CJK",
            fontSize=9.5,
            leading=15,
            textColor=MUTED,
            backColor=PALE_BLUE,
            borderColor=RULE,
            borderWidth=0.6,
            borderPadding=9,
            spaceAfter=4 * mm,
        ),
    }


def add_heading(story: list, text: str, style: ParagraphStyle, level: int) -> None:
    paragraph = Paragraph(inline_markup(text), style)
    paragraph.toc_level = level
    story.append(paragraph)


def markdown_to_flowables(markdown: str, styles: dict[str, ParagraphStyle]) -> list:
    lines = markdown.splitlines()
    story: list = []
    paragraph_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False
    skipped_header = False

    def flush_paragraph(keep_with_next: bool = False) -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            text = "".join(line.strip() for line in paragraph_lines)
            style = styles["body_keep"] if keep_with_next else styles["body"]
            story.append(Paragraph(inline_markup(text), style))
            paragraph_lines = []

    for line in lines:
        if line.startswith("# ") and not skipped_header:
            skipped_header = True
            continue
        if not skipped_header:
            continue
        if line.startswith("日期：") or line.startswith("状态：") or line.startswith("目标周期："):
            continue
        if line.startswith("```"):
            flush_paragraph(keep_with_next=not in_code)
            if in_code:
                code = normalize_text("\n".join(code_lines).rstrip())
                story.append(
                    KeepTogether(
                        [Preformatted(code, styles["code"], maxLineLength=95)]
                    )
                )
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("## "):
            flush_paragraph()
            add_heading(story, line[3:].strip(), styles["h1"], 0)
            continue
        if line.startswith("### "):
            flush_paragraph()
            add_heading(story, line[4:].strip(), styles["h2"], 1)
            continue
        bullet_match = re.match(r"^-\s+(.+)$", line)
        if bullet_match:
            flush_paragraph()
            story.append(
                Paragraph(
                    inline_markup(bullet_match.group(1)),
                    styles["bullet"],
                    bulletText="•",
                )
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
    if code_lines:
        story.append(
            KeepTogether(
                [Preformatted(normalize_text("\n".join(code_lines)), styles["code"])]
            )
        )
    return story


def build_pdf(source: Path, output: Path) -> None:
    register_fonts()
    styles = build_styles()
    markdown = source.read_text(encoding="utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = PyRepairDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=23 * mm,
        bottomMargin=22 * mm,
        title="PyRepair Agent 设计说明",
        author="JerryWu-gith",
        subject="Python测试诊断与候选补丁生成Agent MVP设计",
    )

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOC1",
            fontName="CJK-Bold",
            fontSize=10.5,
            leading=17,
            textColor=NAVY,
            leftIndent=0,
            firstLineIndent=0,
            spaceBefore=1.5 * mm,
        ),
        ParagraphStyle(
            "TOC2",
            fontName="CJK",
            fontSize=8.7,
            leading=13.5,
            textColor=MUTED,
            leftIndent=7 * mm,
            firstLineIndent=0,
        ),
    ]

    story: list = [
        PageBreak(),
        Paragraph("目录", styles["toc_title"]),
        Paragraph(
            "本设计聚焦两周MVP：产品边界、CLI、模块职责、安全约束、测试评测、GitHub Actions及学习路线。",
            styles["meta"],
        ),
        toc,
        PageBreak(),
    ]
    story.extend(markdown_to_flowables(markdown, styles))
    story.append(Spacer(1, 4 * mm))
    story.append(
        KeepTogether(
            [
                Paragraph("设计结论", styles["h2"]),
                Paragraph(
                    "PyRepair以确定性安全与验证代码包围LLM推理：模型提出修改，规则控制边界，测试决定是否完成。第一版成功标准不是夸大的通用能力，而是一个可安装、可复现、可测量的Python测试修复闭环。",
                    styles["meta"],
                ),
            ]
        )
    )
    doc.multiBuild(story)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the PyRepair design PDF")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_pdf(args.source, args.output)
