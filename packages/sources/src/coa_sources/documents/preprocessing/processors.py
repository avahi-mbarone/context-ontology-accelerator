# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""File-type-specific document processors for the preprocessing Lambda.

Each processor converts a file's raw bytes into clean text suitable for
the GraphRAG Toolkit.  Processors use lazy imports so that heavy
dependencies (``unstructured``, ``fitz``) are only loaded when the
corresponding code path is hit, keeping cold-start time low for
pass-through formats.
"""

from __future__ import annotations

import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

# Chars-per-page threshold below which a PDF is considered scanned (image-based).
# PDFs with fewer than this many characters per page on average are routed to Textract.
_SCANNED_PDF_THRESHOLD = 50

# DPI used when rendering PDF pages to PNG for Textract OCR.
# 300 DPI is the recommended minimum for accurate OCR results.
_TEXTRACT_RENDER_DPI = 300

# Concurrent Textract DetectDocumentText calls per document. Textract sync APIs
# allow concurrent requests up to an account TPS quota (default ~10 TPS); boto3
# clients are thread-safe for calls, so we fan the per-page OCR calls out over a
# thread pool. Tunable via env; keep <= the account Textract TPS to avoid
# throttling (boto retries throttles, but staying under is cheaper).
_TEXTRACT_CONCURRENCY = int(os.environ.get("TEXTRACT_CONCURRENCY", "10"))


# ---------------------------------------------------------------------------
# Pass-through processors
# ---------------------------------------------------------------------------


def process_txt(content_bytes: bytes, filename: str) -> tuple[str, str]:
    """Pass through ``.txt`` files (UTF-8 decode only)."""
    return content_bytes.decode("utf-8", errors="replace"), ".txt"


def process_md(content_bytes: bytes, filename: str) -> tuple[str, str]:
    """Pass through ``.md`` files (UTF-8 decode only)."""
    return content_bytes.decode("utf-8", errors="replace"), ".md"


# ---------------------------------------------------------------------------
# DOCX processor
# ---------------------------------------------------------------------------


def process_docx(content_bytes: bytes, filename: str) -> tuple[str, str]:
    """Convert ``.docx`` to Markdown via ``unstructured.partition_docx``."""
    from unstructured.partition.docx import partition_docx  # lazy import

    logger.info(
        "Processing DOCX with unstructured",
        extra={"doc_filename": filename},
    )
    elements = partition_docx(file=io.BytesIO(content_bytes))
    text = elements_to_markdown(elements)
    logger.info(
        "DOCX processed",
        extra={"doc_filename": filename, "elements": len(elements), "char_count": len(text)},
    )
    return text, ".md"


# ---------------------------------------------------------------------------
# PDF processor (auto-detects scanned vs text-native)
# ---------------------------------------------------------------------------


def process_pdf(
    content_bytes: bytes,
    filename: str,
    textract_client: Any,
) -> tuple[str, str]:
    """Process a PDF — text-native via unstructured, scanned via Textract."""
    if is_scanned_pdf(content_bytes):
        logger.info(
            "PDF detected as scanned, routing to Textract",
            extra={"doc_filename": filename},
        )
        text = process_pdf_textract(content_bytes, filename, textract_client)
        return text, ".txt"

    logger.info(
        "PDF detected as text-native, using unstructured",
        extra={"doc_filename": filename},
    )
    from unstructured.partition.pdf import partition_pdf  # lazy import

    # strategy="fast" uses pdfminer only — no layout detection models (torch/detectron2)
    elements = partition_pdf(file=io.BytesIO(content_bytes), strategy="fast")
    text = elements_to_markdown(elements)
    logger.info(
        "PDF processed",
        extra={"doc_filename": filename, "elements": len(elements), "char_count": len(text)},
    )
    return text, ".md"


def is_scanned_pdf(pdf_bytes: bytes) -> bool:
    """Return True if the PDF appears to be scanned (< 50 chars/page avg)."""
    import fitz  # lazy import (PyMuPDF)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count == 0:
            return True

        total_chars = sum(len(page.get_text()) for page in doc)
        avg_chars = total_chars / doc.page_count
        num_pages = doc.page_count
    finally:
        doc.close()

    logger.info(
        "Scanned PDF detection",
        extra={
            "total_chars": total_chars,
            "avg_chars_per_page": round(avg_chars, 1),
            "threshold": _SCANNED_PDF_THRESHOLD,
            "page_count": num_pages,
        },
    )
    return avg_chars < _SCANNED_PDF_THRESHOLD


def process_pdf_textract(
    pdf_bytes: bytes,
    filename: str,
    textract_client: Any,
) -> str:
    """Extract text from a scanned PDF using Amazon Textract.

    Renders each page to a 300-DPI PNG via PyMuPDF, then OCRs the pages with
    Textract sync ``DetectDocumentText``. Rendering is done sequentially first
    (PyMuPDF is NOT thread-safe on a shared document), then the per-page Textract
    calls are fanned out over a thread pool (``_TEXTRACT_CONCURRENCY``) since
    boto3 clients are thread-safe and Textract accepts concurrent requests.
    Results are reassembled in page order.
    """
    import fitz  # lazy import

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        # 1. Render all pages to PNG sequentially (local CPU; PyMuPDF not
        #    thread-safe on a shared doc), keeping page order.
        page_pngs: list[bytes] = []
        for page_num in range(doc.page_count):
            pix = doc[page_num].get_pixmap(dpi=_TEXTRACT_RENDER_DPI)
            page_pngs.append(pix.tobytes("png"))
    finally:
        doc.close()

    total_pages = len(page_pngs)

    def _ocr_page(idx_png: tuple[int, bytes]) -> tuple[int, str]:
        idx, png_bytes = idx_png
        logger.info(
            "Calling Textract for page",
            extra={"doc_filename": filename, "page": idx + 1, "total_pages": total_pages},
        )
        resp = textract_client.detect_document_text(Document={"Bytes": png_bytes})
        lines = [block["Text"] for block in resp.get("Blocks", []) if block["BlockType"] == "LINE"]
        return idx, "\n".join(lines)

    # 2. OCR pages concurrently (I/O-bound remote calls); reassemble in order.
    pages_text: list[str] = [""] * total_pages
    if total_pages:
        workers = min(_TEXTRACT_CONCURRENCY, total_pages)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for idx, text in pool.map(_ocr_page, enumerate(page_pngs)):
                pages_text[idx] = text

    return "\n\n".join(pages_text)


# ---------------------------------------------------------------------------
# Element-to-Markdown conversion
# ---------------------------------------------------------------------------


def elements_to_markdown(elements: list) -> str:
    """Convert unstructured ``Element`` objects to a Markdown string."""
    lines: list[str] = []

    for el in elements:
        category = el.category if hasattr(el, "category") else ""
        text = str(el)

        if category == "Title":
            lines.append(f"## {text}")
        elif category == "Header":
            lines.append(f"# {text}")
        elif category == "ListItem":
            lines.append(f"- {text}")
        elif category == "Table":
            lines.append(f"```\n{text}\n```")
        elif text.strip():
            lines.append(text)

    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Page count helper
# ---------------------------------------------------------------------------


def get_page_count(content_bytes: bytes, ext: str) -> int:
    """Return the page count for PDFs; 0 for other formats."""
    if ext != ".pdf":
        return 0
    import fitz  # lazy import

    doc = fitz.open(stream=content_bytes, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Processor dispatch table
# ---------------------------------------------------------------------------

_PROCESSORS: dict[str, Any] = {
    ".txt": process_txt,
    ".md": process_md,
    ".docx": process_docx,
    # .pdf is handled separately in handler.py (needs textract_client)
}
