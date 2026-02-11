"""
Tests for handler.py – Image OCR Lambda handler.
Uses unittest.mock to patch subprocess and tempfile so Tesseract is not required.
"""

import base64
import json
import os
from unittest.mock import patch, MagicMock, mock_open

import pytest

# Import the handler
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from handler import lambda_handler


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _b64_png(raw: bytes = b"\x89PNG fake image data") -> str:
    """Return a plain base64-encoded string (no data-URL prefix)."""
    return base64.b64encode(raw).decode()


def _b64_png_with_prefix(raw: bytes = b"\x89PNG fake image data") -> str:
    """Return a base64 string WITH data-URL prefix."""
    return f"data:image/png;base64,{base64.b64encode(raw).decode()}"


def _make_subprocess_result(stdout="Hello World", stderr="", returncode=0):
    """Create a mock subprocess.CompletedProcess."""
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


# ---------------------------------------------------------------------------
# Tests – successful extraction
# ---------------------------------------------------------------------------

class TestLambdaHandlerSuccess:
    """Happy-path tests."""

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_basic_extraction(self, mock_tmp, mock_run, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(stdout="Extracted text here")

        result = lambda_handler({"image": _b64_png(), "filename": "test.png"}, None)

        assert result["text"] == "Extracted text here"
        assert result["filename"] == "test.png"
        assert result["word_count"] == 3
        assert result["text_length"] == len("Extracted text here")
        assert "processing_time_ms" in result

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_strips_data_url_prefix(self, mock_tmp, mock_run, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(stdout="OCR output")

        result = lambda_handler(
            {"image": _b64_png_with_prefix(), "filename": "photo.png"}, None
        )

        assert result["text"] == "OCR output"
        assert "error" not in result

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_api_gateway_proxy_format(self, mock_tmp, mock_run, mock_unlink):
        """Simulate API Gateway event with body + httpMethod."""
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(stdout="Gateway text")

        body_payload = json.dumps({"image": _b64_png(), "filename": "gw.png"})
        event = {
            "httpMethod": "POST",
            "body": body_payload,
            "isBase64Encoded": False,
        }

        result = lambda_handler(event, None)
        assert result["text"] == "Gateway text"

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_api_gateway_base64_body(self, mock_tmp, mock_run, mock_unlink):
        """API Gateway event where the body itself is base64-encoded."""
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(stdout="B64 body")

        inner = json.dumps({"image": _b64_png(), "filename": "b64body.png"})
        event = {
            "httpMethod": "POST",
            "body": base64.b64encode(inner.encode()).decode(),
            "isBase64Encoded": True,
        }

        result = lambda_handler(event, None)
        assert result["text"] == "B64 body"

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_default_filename(self, mock_tmp, mock_run, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(stdout="text")

        result = lambda_handler({"image": _b64_png()}, None)
        assert result["filename"] == "unknown"


# ---------------------------------------------------------------------------
# Tests – error handling
# ---------------------------------------------------------------------------

class TestLambdaHandlerErrors:

    def test_no_image_data(self):
        result = lambda_handler({"image": "", "filename": "empty.png"}, None)
        assert result == {"error": "No image data provided"}

    def test_missing_image_key(self):
        result = lambda_handler({"filename": "noimage.png"}, None)
        assert result == {"error": "No image data provided"}

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_tesseract_failure(self, mock_tmp, mock_run, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(
            stdout="", stderr="Tesseract error details", returncode=1
        )

        result = lambda_handler({"image": _b64_png(), "filename": "bad.png"}, None)
        assert "error" in result
        assert "Tesseract OCR failed" in result["error"]

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_tesseract_nonzero_but_has_text(self, mock_tmp, mock_run, mock_unlink):
        """If returncode != 0 but some text was extracted, return the text."""
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(
            stdout="partial text", stderr="warning", returncode=1
        )

        result = lambda_handler({"image": _b64_png(), "filename": "warn.png"}, None)
        assert result["text"] == "partial text"

    def test_invalid_base64(self):
        result = lambda_handler({"image": "not_valid_base64!!!", "filename": "bad.png"}, None)
        assert "error" in result

    @patch("handler.subprocess.run", side_effect=Exception("boom"))
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_unexpected_exception(self, mock_tmp, mock_run):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        result = lambda_handler({"image": _b64_png(), "filename": "err.png"}, None)
        assert result == {"error": "boom"}


# ---------------------------------------------------------------------------
# Tests – edge cases
# ---------------------------------------------------------------------------

class TestLambdaHandlerEdgeCases:

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_empty_extracted_text(self, mock_tmp, mock_run, mock_unlink):
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.png"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(stdout="")

        result = lambda_handler({"image": _b64_png(), "filename": "blank.png"}, None)
        assert result["text"] == ""
        assert result["word_count"] == 0
        assert result["text_length"] == 0

    @patch("handler.os.unlink")
    @patch("handler.subprocess.run")
    @patch("handler.tempfile.NamedTemporaryFile")
    def test_file_extension_from_filename(self, mock_tmp, mock_run, mock_unlink):
        """Ensure the temp file suffix matches the uploaded file extension."""
        mock_tmp.return_value.__enter__ = lambda s: s
        mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.jpg"
        mock_tmp.return_value.write = MagicMock()

        mock_run.return_value = _make_subprocess_result(stdout="jpg text")

        lambda_handler({"image": _b64_png(), "filename": "photo.jpg"}, None)

        # Verify the temp file was created with .jpg suffix
        mock_tmp.assert_called_once_with(suffix=".jpg", delete=False)
