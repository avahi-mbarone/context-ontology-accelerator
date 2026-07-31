# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the preprocessing Lambda processors module."""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

for _mod_name in (
    "fitz",
    "unstructured",
    "unstructured.partition",
):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = ModuleType(_mod_name)

# These need a callable attribute so @patch can target it
for _mod_name, _attr in [
    ("unstructured.partition.docx", "partition_docx"),
    ("unstructured.partition.pdf", "partition_pdf"),
]:
    if _mod_name not in sys.modules:
        mod = ModuleType(_mod_name)
        setattr(mod, _attr, None)
        sys.modules[_mod_name] = mod

from coa_sources.documents.preprocessing.processors import (
    _PROCESSORS,
    _SCANNED_PDF_THRESHOLD,
    elements_to_markdown,
    get_page_count,
    process_docx,
    process_md,
    process_pdf,
    process_pdf_textract,
    process_txt,
)

# ---------------------------------------------------------------------------
# Pass-through processors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessTxt:
    def test_decodes_utf8(self):
        text, ext = process_txt(b"hello world", "file.txt")
        assert text == "hello world"
        assert ext == ".txt"

    def test_preserves_newlines(self):
        text, _ = process_txt(b"line1\nline2\nline3", "file.txt")
        assert text == "line1\nline2\nline3"

    def test_replaces_invalid_bytes(self):
        text, ext = process_txt(b"hello \xff world", "file.txt")
        assert "hello" in text
        assert "world" in text
        assert ext == ".txt"

    def test_empty_file(self):
        text, ext = process_txt(b"", "empty.txt")
        assert text == ""
        assert ext == ".txt"


@pytest.mark.unit
class TestProcessMd:
    def test_decodes_utf8(self):
        text, ext = process_md(b"# Heading\n\nParagraph", "doc.md")
        assert text == "# Heading\n\nParagraph"
        assert ext == ".md"

    def test_replaces_invalid_bytes(self):
        text, _ = process_md(b"# Title\xff", "doc.md")
        assert "Title" in text

    def test_empty_file(self):
        text, ext = process_md(b"", "empty.md")
        assert text == ""
        assert ext == ".md"


# ---------------------------------------------------------------------------
# DOCX processor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessDocx:
    @patch("unstructured.partition.docx.partition_docx")
    def test_calls_partition_and_returns_markdown(self, mock_partition):
        el = MagicMock()
        el.category = "NarrativeText"
        el.__str__ = MagicMock(return_value="Some paragraph text")
        mock_partition.return_value = [el]

        text, ext = process_docx(b"fake-docx-bytes", "doc.docx")
        assert ext == ".md"
        assert "Some paragraph text" in text
        mock_partition.assert_called_once()

    @patch("unstructured.partition.docx.partition_docx")
    def test_empty_docx(self, mock_partition):
        mock_partition.return_value = []
        text, ext = process_docx(b"fake", "empty.docx")
        assert text == ""
        assert ext == ".md"


# ---------------------------------------------------------------------------
# Scanned PDF detection
# ---------------------------------------------------------------------------


def _make_fitz_doc(pages_text: list[str]) -> MagicMock:
    """Build a mock fitz.Document with pages returning given text."""
    doc = MagicMock()
    doc.page_count = len(pages_text)
    pages = []
    for text in pages_text:
        page = MagicMock()
        page.get_text.return_value = text
        pages.append(page)
    doc.__iter__ = lambda self: iter(pages)
    doc.__getitem__ = lambda self, i: pages[i]
    doc.close = MagicMock()
    return doc


@pytest.mark.unit
class TestIsScannedPdf:
    @patch("fitz.open")
    def test_text_heavy_pdf_not_scanned(self, mock_fitz_open):
        from coa_sources.documents.preprocessing.processors import is_scanned_pdf

        mock_fitz_open.return_value = _make_fitz_doc(["a" * 500, "b" * 600])
        assert is_scanned_pdf(b"fake-pdf") is False

    @patch("fitz.open")
    def test_image_only_pdf_is_scanned(self, mock_fitz_open):
        from coa_sources.documents.preprocessing.processors import is_scanned_pdf

        mock_fitz_open.return_value = _make_fitz_doc(["", ""])
        assert is_scanned_pdf(b"fake-pdf") is True

    @patch("fitz.open")
    def test_below_threshold_is_scanned(self, mock_fitz_open):
        from coa_sources.documents.preprocessing.processors import is_scanned_pdf

        chars = "x" * (_SCANNED_PDF_THRESHOLD - 1)
        mock_fitz_open.return_value = _make_fitz_doc([chars])
        assert is_scanned_pdf(b"fake-pdf") is True

    @patch("fitz.open")
    def test_at_threshold_not_scanned(self, mock_fitz_open):
        from coa_sources.documents.preprocessing.processors import is_scanned_pdf

        chars = "x" * _SCANNED_PDF_THRESHOLD
        mock_fitz_open.return_value = _make_fitz_doc([chars])
        assert is_scanned_pdf(b"fake-pdf") is False

    @patch("fitz.open")
    def test_empty_pdf_zero_pages(self, mock_fitz_open):
        from coa_sources.documents.preprocessing.processors import is_scanned_pdf

        doc = MagicMock()
        doc.page_count = 0
        doc.close = MagicMock()
        mock_fitz_open.return_value = doc
        assert is_scanned_pdf(b"fake-pdf") is True


# ---------------------------------------------------------------------------
# Textract extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessPdfTextract:
    @patch("fitz.open")
    def test_single_page_calls_textract(self, mock_fitz_open):
        page = MagicMock()
        pix = MagicMock()
        pix.tobytes.return_value = b"fake-png"
        page.get_pixmap.return_value = pix

        doc = MagicMock()
        doc.page_count = 1
        doc.__getitem__ = lambda _, i: page
        doc.close = MagicMock()
        mock_fitz_open.return_value = doc

        textract = MagicMock()
        textract.detect_document_text.return_value = {
            "Blocks": [
                {"BlockType": "LINE", "Text": "Hello from Textract"},
                {"BlockType": "WORD", "Text": "ignored"},
            ]
        }

        result = process_pdf_textract(b"pdf-bytes", "scan.pdf", textract)
        assert result == "Hello from Textract"
        textract.detect_document_text.assert_called_once()
        page.get_pixmap.assert_called_once_with(dpi=300)

    @patch("fitz.open")
    def test_multi_page_joins_with_double_newline(self, mock_fitz_open):
        pages = []
        for _ in range(3):
            page = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = b"png"
            page.get_pixmap.return_value = pix
            pages.append(page)

        doc = MagicMock()
        doc.page_count = 3
        doc.__getitem__ = lambda _, i: pages[i]
        doc.close = MagicMock()
        mock_fitz_open.return_value = doc

        textract = MagicMock()
        textract.detect_document_text.side_effect = [
            {"Blocks": [{"BlockType": "LINE", "Text": "Page 1"}]},
            {"Blocks": [{"BlockType": "LINE", "Text": "Page 2"}]},
            {"Blocks": [{"BlockType": "LINE", "Text": "Page 3"}]},
        ]

        result = process_pdf_textract(b"pdf", "multi.pdf", textract)
        assert result == "Page 1\n\nPage 2\n\nPage 3"
        assert textract.detect_document_text.call_count == 3

    @patch("fitz.open")
    def test_empty_textract_response(self, mock_fitz_open):
        page = MagicMock()
        pix = MagicMock()
        pix.tobytes.return_value = b"png"
        page.get_pixmap.return_value = pix

        doc = MagicMock()
        doc.page_count = 1
        doc.__getitem__ = lambda _, i: page
        doc.close = MagicMock()
        mock_fitz_open.return_value = doc

        textract = MagicMock()
        textract.detect_document_text.return_value = {"Blocks": []}

        result = process_pdf_textract(b"pdf", "empty.pdf", textract)
        assert result == ""


# ---------------------------------------------------------------------------
# PDF processor (routing logic)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessPdf:
    @patch("unstructured.partition.pdf.partition_pdf")
    @patch("coa_sources.documents.preprocessing.processors.is_scanned_pdf", return_value=False)
    def test_text_native_uses_unstructured(self, mock_scanned, mock_partition):
        el = MagicMock()
        el.category = "NarrativeText"
        el.__str__ = MagicMock(return_value="PDF text content")
        mock_partition.return_value = [el]

        text, ext = process_pdf(b"pdf-bytes", "doc.pdf", MagicMock())
        assert ext == ".md"
        assert "PDF text content" in text
        mock_partition.assert_called_once()

    @patch(
        "coa_sources.documents.preprocessing.processors.process_pdf_textract",
        return_value="Textract output",
    )
    @patch("coa_sources.documents.preprocessing.processors.is_scanned_pdf", return_value=True)
    def test_scanned_uses_textract(self, mock_scanned, mock_textract):
        textract_client = MagicMock()
        text, ext = process_pdf(b"pdf-bytes", "scan.pdf", textract_client)
        assert ext == ".txt"
        assert text == "Textract output"
        mock_textract.assert_called_once_with(b"pdf-bytes", "scan.pdf", textract_client)


# ---------------------------------------------------------------------------
# elements_to_markdown
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestElementsToMarkdown:
    def _make_element(self, category: str, text: str) -> MagicMock:
        el = MagicMock()
        el.category = category
        el.__str__ = MagicMock(return_value=text)
        return el

    def test_title_becomes_h2(self):
        result = elements_to_markdown([self._make_element("Title", "My Title")])
        assert result == "## My Title"

    def test_header_becomes_h1(self):
        result = elements_to_markdown([self._make_element("Header", "My Header")])
        assert result == "# My Header"

    def test_list_item_becomes_bullet(self):
        result = elements_to_markdown([self._make_element("ListItem", "First item")])
        assert result == "- First item"

    def test_table_becomes_code_block(self):
        result = elements_to_markdown([self._make_element("Table", "col1 | col2")])
        assert result == "```\ncol1 | col2\n```"

    def test_narrative_text_plain(self):
        result = elements_to_markdown([self._make_element("NarrativeText", "Paragraph text")])
        assert result == "Paragraph text"

    def test_empty_text_skipped(self):
        result = elements_to_markdown([self._make_element("NarrativeText", "   ")])
        assert result == ""

    def test_mixed_elements(self):
        els = [
            self._make_element("Header", "Doc Title"),
            self._make_element("NarrativeText", "Introduction paragraph"),
            self._make_element("Title", "Section 1"),
            self._make_element("ListItem", "Item A"),
            self._make_element("ListItem", "Item B"),
        ]
        result = elements_to_markdown(els)
        lines = result.split("\n\n")
        assert lines[0] == "# Doc Title"
        assert lines[1] == "Introduction paragraph"
        assert lines[2] == "## Section 1"
        assert lines[3] == "- Item A"
        assert lines[4] == "- Item B"

    def test_empty_list(self):
        assert elements_to_markdown([]) == ""

    def test_no_category_attribute(self):
        """Element without a .category attribute falls through to plain text."""

        class BareElement:
            """An element with no .category attribute."""

            def __str__(self):
                return "plain text"

        el = BareElement()
        result = elements_to_markdown([el])
        assert result == "plain text"


# ---------------------------------------------------------------------------
# get_page_count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPageCount:
    @patch("fitz.open")
    def test_pdf_returns_count(self, mock_fitz_open):
        doc = MagicMock()
        doc.page_count = 5
        doc.close = MagicMock()
        mock_fitz_open.return_value = doc
        assert get_page_count(b"pdf-bytes", ".pdf") == 5

    def test_txt_returns_zero(self):
        assert get_page_count(b"text", ".txt") == 0

    def test_md_returns_zero(self):
        assert get_page_count(b"# heading", ".md") == 0

    def test_docx_returns_zero(self):
        assert get_page_count(b"docx-bytes", ".docx") == 0


# ---------------------------------------------------------------------------
# Processor dispatch table
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessorDispatchTable:
    def test_has_txt(self):
        assert ".txt" in _PROCESSORS
        assert _PROCESSORS[".txt"] is process_txt

    def test_has_md(self):
        assert ".md" in _PROCESSORS
        assert _PROCESSORS[".md"] is process_md

    def test_has_docx(self):
        assert ".docx" in _PROCESSORS
        assert _PROCESSORS[".docx"] is process_docx

    def test_pdf_not_in_table(self):
        assert ".pdf" not in _PROCESSORS

    def test_no_unexpected_keys(self):
        assert set(_PROCESSORS.keys()) == {".txt", ".md", ".docx"}
