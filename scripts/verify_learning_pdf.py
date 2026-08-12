from __future__ import annotations

import argparse
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

EXPECTED_TITLE = "PyRepair Agent 十天实战学习手册"
REQUIRED_TEXT = [
    *(f"第{day}天" for day in range(1, 11)),
    "86.7%",
    "Policy",
    "Review",
    "Verifier",
    "pytest 9",
    "FakeLLM",
    "Claude Code",
    "全量回归",
]


def verify_pdf(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 100_000:
        raise AssertionError(f"PDF is missing or unexpectedly small: {path}")

    reader = PdfReader(path)
    page_count = len(reader.pages)
    if not 25 <= page_count <= 40:
        raise AssertionError(f"Expected 25-40 pages, found {page_count}")

    title = (reader.metadata or {}).get("/Title")
    if title != EXPECTED_TITLE:
        raise AssertionError(f"Unexpected title metadata: {title!r}")
    if not reader.outline:
        raise AssertionError("PDF outline/bookmarks are missing")

    a4_width = 595.28
    a4_height = 841.89
    for index, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if abs(width - a4_width) > 2 or abs(height - a4_height) > 2:
            raise AssertionError(f"Page {index} is not A4: {width:.2f} x {height:.2f}")

    with pdfplumber.open(path) as document:
        page_texts = [(page.extract_text() or "").strip() for page in document.pages]
    short_pages = [index for index, text in enumerate(page_texts, start=1) if len(text) < 30]
    if short_pages:
        raise AssertionError(f"Pages with unexpectedly little extractable text: {short_pages}")

    full_text = "\n".join(page_texts)
    missing = [value for value in REQUIRED_TEXT if value not in full_text]
    if missing:
        raise AssertionError(f"Required text is missing: {missing}")

    print(
        f"PDF verification passed: pages={page_count}, "
        f"bytes={path.stat().st_size}, bookmarks={len(reader.outline)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the PyRepair learning guide PDF")
    parser.add_argument("pdf", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    verify_pdf(args.pdf)
