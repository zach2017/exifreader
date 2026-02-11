"""
Tests for pdf_handler.py – PDF text extraction Lambda handler.
Uses unittest.mock to patch PyMuPDF (fitz) so no real PDFs are needed.
"""

import base64
import os
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pdf_handler import pdf_handler


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _b64_pdf(raw: bytes = b"%PDF-1.4 fake pdf content") -> str:
    return base64.b64encode(raw).decode()


def _b64_pdf_with_prefix(raw: bytes = b"%PDF-1.4 fake pdf") -> str:
    return f"data:application/pdf;base64,{base64.b64encode(raw).decode()}"


def _mock_page(text: str = "Page text"):
    """Create a mock fitz page that returns given text."""
    page = MagicMock()
    page.get_text.return_value = text
    return page


def _mock_document(pages_text: list[str]):
    """Create a mock fitz.Document with given page texts."""
    pages = [_mock_page(t) for t in pages_text]
    doc = MagicMock()
    doc.__len__ = lambda self: len(pages)
    doc.__iter__ = lambda self: iter(pages)
    doc.__enter__ = lambda self: self
    doc.__exit__ = MagicMock(return_value=False)
    doc.close = MagicMock()
    return doc


# ---------------------------------------------------------------------------
# Tests – successful extraction
# ---------------------------------------------------------------------------

class TestPdfHandlerSuccess:

    @patch("pdf_handler.os.unlink")
    @patch("pdf_handler.fitz.open")
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_single_page_extraction(self, mock_tmp, mock_fitz_open, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        mock_fitz_open.return_value = _mock_document(["Hello from page 1"])

        result = pdf_handler({"pdf": _b64_pdf(), "filename": "test.pdf"}, None)

        assert result["text"] == "Hello from page 1"
        assert result["page_count"] == 1
        assert result["total_word_count"] == 4
        assert result["filename"] == "test.pdf"
        assert "processing_time_ms" in result
        assert len(result["pages"]) == 1
        assert result["pages"][0]["page"] == 1

    @patch("pdf_handler.os.unlink")
    @patch("pdf_handler.fitz.open")
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_multi_page_extraction(self, mock_tmp, mock_fitz_open, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        mock_fitz_open.return_value = _mock_document([
            "First page content",
            "Second page content",
            "Third page content",
        ])

        result = pdf_handler({"pdf": _b64_pdf(), "filename": "multi.pdf"}, None)

        assert result["page_count"] == 3
        assert len(result["pages"]) == 3
        assert "First page content" in result["text"]
        assert "Third page content" in result["text"]
        # Pages joined by double-newline
        assert "\n\n" in result["text"]

    @patch("pdf_handler.os.unlink")
    @patch("pdf_handler.fitz.open")
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_strips_data_url_prefix(self, mock_tmp, mock_fitz_open, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        mock_fitz_open.return_value = _mock_document(["Prefix test"])

        result = pdf_handler({"pdf": _b64_pdf_with_prefix(), "filename": "prefix.pdf"}, None)

        assert result["text"] == "Prefix test"
        assert "error" not in result

    @patch("pdf_handler.os.unlink")
    @patch("pdf_handler.fitz.open")
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_word_and_char_counts(self, mock_tmp, mock_fitz_open, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        mock_fitz_open.return_value = _mock_document(["One two three", "Four five"])

        result = pdf_handler({"pdf": _b64_pdf(), "filename": "counts.pdf"}, None)

        assert result["total_word_count"] == 5
        assert result["pages"][0]["word_count"] == 3
        assert result["pages"][1]["word_count"] == 2

    @patch("pdf_handler.os.unlink")
    @patch("pdf_handler.fitz.open")
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_default_filename(self, mock_tmp, mock_fitz_open, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        mock_fitz_open.return_value = _mock_document(["text"])

        result = pdf_handler({"pdf": _b64_pdf()}, None)
        assert result["filename"] == "unknown.pdf"

    @patch("pdf_handler.os.unlink")
    @patch("pdf_handler.fitz.open")
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_file_size_bytes(self, mock_tmp, mock_fitz_open, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        mock_fitz_open.return_value = _mock_document(["text"])
        raw = b"%PDF raw data here"

        result = pdf_handler({"pdf": base64.b64encode(raw).decode()}, None)
        assert result["file_size_bytes"] == len(raw)


# ---------------------------------------------------------------------------
# Tests – error handling
# ---------------------------------------------------------------------------

class TestPdfHandlerErrors:

    def test_no_pdf_data(self):
        result = pdf_handler({"pdf": "", "filename": "empty.pdf"}, None)
        assert result == {"error": "No PDF data provided"}

    def test_missing_pdf_key(self):
        result = pdf_handler({"filename": "nopdf.pdf"}, None)
        assert result == {"error": "No PDF data provided"}

    def test_invalid_base64(self):
        result = pdf_handler({"pdf": "!!!bad_base64!!!", "filename": "bad.pdf"}, None)
        assert "error" in result

    @patch("pdf_handler.fitz.open", side_effect=Exception("corrupt PDF"))
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_fitz_open_failure(self, mock_tmp, mock_fitz_open):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        result = pdf_handler({"pdf": _b64_pdf(), "filename": "corrupt.pdf"}, None)
        assert result == {"error": "corrupt PDF"}


# ---------------------------------------------------------------------------
# Tests – edge cases
# ---------------------------------------------------------------------------

class TestPdfHandlerEdgeCases:

    @patch("pdf_handler.os.unlink")
    @patch("pdf_handler.fitz.open")
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_empty_page_text(self, mock_tmp, mock_fitz_open, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        mock_fitz_open.return_value = _mock_document(["", ""])

        result = pdf_handler({"pdf": _b64_pdf(), "filename": "empty_pages.pdf"}, None)

        assert result["total_word_count"] == 0
        assert result["page_count"] == 2
        assert result["pages"][0]["word_count"] == 0

    @patch("pdf_handler.os.unlink")
    @patch("pdf_handler.fitz.open")
    @patch("pdf_handler.tempfile.NamedTemporaryFile")
    def test_page_extraction_timing(self, mock_tmp, mock_fitz_open, mock_unlink):
        """Each page should have its own extraction_time_ms."""
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.pdf"
        mock_tmp.return_value.write = MagicMock()

        mock_fitz_open.return_value = _mock_document(["a", "b"])

        result = pdf_handler({"pdf": _b64_pdf()}, None)

        for page in result["pages"]:
            assert "extraction_time_ms" in page
            assert isinstance(page["extraction_time_ms"], float)
