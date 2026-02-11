"""
Tests for pdf_ocr_handler.py – PDF OCR Lambda handler.
Mocks both PyMuPDF (fitz) and Tesseract subprocess calls.
"""

import base64
import os
from unittest.mock import patch, MagicMock, call

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pdf_ocr_handler import pdf_ocr_handler, run_tesseract, extract_page_image


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _b64_pdf(raw: bytes = b"%PDF-1.4 fake") -> str:
    return base64.b64encode(raw).decode()


def _b64_pdf_with_prefix(raw: bytes = b"%PDF-1.4 fake") -> str:
    return f"data:application/pdf;base64,{base64.b64encode(raw).decode()}"


def _mock_pixmap(png_bytes: bytes = b"\x89PNG fake image"):
    pix = MagicMock()
    pix.tobytes.return_value = png_bytes
    return pix


def _mock_page(png_bytes: bytes = b"\x89PNG fake image"):
    page = MagicMock()
    page.get_pixmap.return_value = _mock_pixmap(png_bytes)
    return page


def _mock_document(num_pages: int = 1, png_bytes: bytes = b"\x89PNG fake"):
    pages = [_mock_page(png_bytes) for _ in range(num_pages)]
    doc = MagicMock()
    doc.__len__ = lambda self: len(pages)
    doc.__iter__ = lambda self: iter(pages)
    doc.close = MagicMock()
    return doc


def _mock_subprocess_result(stdout="OCR text", stderr="", returncode=0):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


# ---------------------------------------------------------------------------
# Tests – run_tesseract helper
# ---------------------------------------------------------------------------

class TestRunTesseract:

    @patch("pdf_ocr_handler.subprocess.run")
    def test_successful_ocr(self, mock_run):
        mock_run.return_value = _mock_subprocess_result(stdout="  Hello World  ")

        text, elapsed = run_tesseract("/tmp/test.png")

        assert text == "Hello World"  # stripped
        assert elapsed >= 0
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert "tesseract" in args[0][0]

    @patch("pdf_ocr_handler.subprocess.run")
    def test_tesseract_failure_raises(self, mock_run):
        mock_run.return_value = _mock_subprocess_result(
            stdout="", stderr="Error: bad image", returncode=1
        )

        with pytest.raises(RuntimeError, match="Tesseract failed"):
            run_tesseract("/tmp/bad.png")

    @patch("pdf_ocr_handler.subprocess.run")
    def test_nonzero_returncode_with_text_succeeds(self, mock_run):
        """If returncode != 0 but text was extracted, don't raise."""
        mock_run.return_value = _mock_subprocess_result(
            stdout="partial text", stderr="warning", returncode=1
        )

        text, elapsed = run_tesseract("/tmp/warn.png")
        assert text == "partial text"


# ---------------------------------------------------------------------------
# Tests – extract_page_image helper
# ---------------------------------------------------------------------------

class TestExtractPageImage:

    def test_renders_page_to_png(self):
        page = _mock_page(b"\x89PNG rendered image bytes")

        png_bytes, elapsed = extract_page_image(page, dpi=300)

        assert png_bytes == b"\x89PNG rendered image bytes"
        assert elapsed >= 0
        page.get_pixmap.assert_called_once()

    def test_custom_dpi(self):
        page = _mock_page()

        extract_page_image(page, dpi=150)

        # Verify get_pixmap was called with a matrix
        page.get_pixmap.assert_called_once()
        call_kwargs = page.get_pixmap.call_args
        assert "matrix" in call_kwargs.kwargs or len(call_kwargs.args) > 0


# ---------------------------------------------------------------------------
# Tests – pdf_ocr_handler (full pipeline)
# ---------------------------------------------------------------------------

class TestPdfOcrHandlerSuccess:

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_single_page_pipeline(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        # Set up temp file mock
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=1)
        mock_run.return_value = _mock_subprocess_result(stdout="Extracted from image")

        result = pdf_ocr_handler(
            {"pdf": _b64_pdf(), "filename": "scan.pdf"}, None
        )

        assert result["text"] == "Extracted from image"
        assert result["page_count"] == 1
        assert result["filename"] == "scan.pdf"
        assert result["total_word_count"] == 3
        assert "timing" in result
        assert "pipeline_ms" in result["timing"]
        assert len(result["pages"]) == 1

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_multi_page_pipeline(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=3)
        mock_run.return_value = _mock_subprocess_result(stdout="Page text")

        result = pdf_ocr_handler({"pdf": _b64_pdf(), "filename": "multi.pdf"}, None)

        assert result["page_count"] == 3
        assert len(result["pages"]) == 3
        # Each page OCR'd separately, joined by double newline
        assert result["text"].count("Page text") == 3
        assert result["total_word_count"] == 6  # 2 words × 3 pages

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_strips_data_url_prefix(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=1)
        mock_run.return_value = _mock_subprocess_result(stdout="prefix test")

        result = pdf_ocr_handler(
            {"pdf": _b64_pdf_with_prefix(), "filename": "prefix.pdf"}, None
        )

        assert result["text"] == "prefix test"
        assert "error" not in result

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_custom_dpi(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=1)
        mock_run.return_value = _mock_subprocess_result(stdout="hi-res")

        result = pdf_ocr_handler(
            {"pdf": _b64_pdf(), "filename": "hires.pdf", "dpi": 600}, None
        )

        assert result["dpi"] == 600

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_timing_breakdown(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=2)
        mock_run.return_value = _mock_subprocess_result(stdout="text")

        result = pdf_ocr_handler({"pdf": _b64_pdf()}, None)

        timing = result["timing"]
        assert "pipeline_ms" in timing
        assert "total_image_extract_ms" in timing
        assert "total_ocr_ms" in timing
        assert "avg_extract_per_page_ms" in timing
        assert "avg_ocr_per_page_ms" in timing

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_per_page_metadata(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=1, png_bytes=b"X" * 500)
        mock_run.return_value = _mock_subprocess_result(stdout="hello world")

        result = pdf_ocr_handler({"pdf": _b64_pdf()}, None)

        page = result["pages"][0]
        assert page["page"] == 1
        assert page["word_count"] == 2
        assert page["image_size_bytes"] == 500
        assert "image_extract_ms" in page
        assert "ocr_ms" in page
        assert "page_total_ms" in page


# ---------------------------------------------------------------------------
# Tests – error handling
# ---------------------------------------------------------------------------

class TestPdfOcrHandlerErrors:

    def test_no_pdf_data(self):
        result = pdf_ocr_handler({"pdf": ""}, None)
        assert result == {"error": "No PDF data provided"}

    def test_missing_pdf_key(self):
        result = pdf_ocr_handler({}, None)
        assert result == {"error": "No PDF data provided"}

    def test_invalid_base64(self):
        result = pdf_ocr_handler({"pdf": "###invalid###"}, None)
        assert "error" in result

    @patch("pdf_ocr_handler.fitz.open", side_effect=Exception("corrupt"))
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_fitz_failure(self, mock_tmp, mock_fitz_open):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        result = pdf_ocr_handler({"pdf": _b64_pdf()}, None)
        assert result == {"error": "corrupt"}

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_tesseract_failure_in_pipeline(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=1)
        mock_run.return_value = _mock_subprocess_result(
            stdout="", stderr="Tesseract exploded", returncode=1
        )

        result = pdf_ocr_handler({"pdf": _b64_pdf()}, None)
        assert "error" in result
        assert "Tesseract failed" in result["error"]


# ---------------------------------------------------------------------------
# Tests – default values
# ---------------------------------------------------------------------------

class TestPdfOcrHandlerDefaults:

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_default_filename(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=1)
        mock_run.return_value = _mock_subprocess_result(stdout="x")

        result = pdf_ocr_handler({"pdf": _b64_pdf()}, None)
        assert result["filename"] == "unknown.pdf"

    @patch("pdf_ocr_handler.os.unlink")
    @patch("pdf_ocr_handler.subprocess.run")
    @patch("pdf_ocr_handler.fitz.open")
    @patch("pdf_ocr_handler.tempfile.NamedTemporaryFile")
    def test_default_dpi(self, mock_tmp, mock_fitz_open, mock_run, mock_unlink):
        tmp_mock = MagicMock()
        tmp_mock.name = "/tmp/fake"
        tmp_mock.write = MagicMock()
        mock_tmp.return_value.__enter__ = lambda s: tmp_mock
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

        mock_fitz_open.return_value = _mock_document(num_pages=1)
        mock_run.return_value = _mock_subprocess_result(stdout="x")

        result = pdf_ocr_handler({"pdf": _b64_pdf()}, None)
        assert result["dpi"] == 300
