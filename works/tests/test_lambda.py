"""
Tests for the Lambda handler function.
Verifies S3 event parsing, doc_id extraction, API call logic,
and error handling — all pure unit tests with no external deps.
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))
from handler import handler


def make_s3_event(bucket: str, key: str, size: int = 1024) -> dict:
    """Create a mock S3 event notification."""
    return {
        "Records": [{
            "eventVersion": "2.1",
            "eventSource": "aws:s3",
            "eventName": "ObjectCreated:Put",
            "s3": {
                "bucket": {"name": bucket},
                "object": {"key": key, "size": size},
            },
        }]
    }


def mock_urlopen_success(data=None):
    """Return a patched urlopen that returns success."""
    if data is None:
        data = {"status": "completed"}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestLambdaDocIdExtraction:
    """Test S3 key parsing and doc_id extraction."""

    def test_extracts_doc_id_from_valid_key(self):
        event = make_s3_event("ocr-documents", "uploads/abc-123-def/scan.png")

        with patch("handler.urllib.request.urlopen", return_value=mock_urlopen_success()):
            result = handler(event, None)

        body = json.loads(result["body"])
        assert body["processed"] == 1
        assert body["results"][0]["doc_id"] == "abc-123-def"
        assert body["results"][0]["status"] == "success"

    def test_extracts_uuid_doc_id(self):
        uuid_id = "550e8400-e29b-41d4-a716-446655440000"
        event = make_s3_event("bucket", f"uploads/{uuid_id}/file.png")

        with patch("handler.urllib.request.urlopen", return_value=mock_urlopen_success()):
            result = handler(event, None)

        body = json.loads(result["body"])
        assert body["results"][0]["doc_id"] == uuid_id

    def test_handles_nested_filename(self):
        event = make_s3_event("bucket", "uploads/doc-123/subdir/deep/file.png")

        with patch("handler.urllib.request.urlopen", return_value=mock_urlopen_success()):
            result = handler(event, None)

        body = json.loads(result["body"])
        assert body["results"][0]["doc_id"] == "doc-123"

    def test_skips_non_uploads_prefix(self):
        event = make_s3_event("ocr-documents", "text/abc/extracted.txt")
        result = handler(event, None)

        body = json.loads(result["body"])
        assert body["processed"] == 1
        assert body["results"][0]["status"] == "skipped"

    def test_skips_short_key(self):
        event = make_s3_event("ocr-documents", "uploads/file.png")
        result = handler(event, None)

        body = json.loads(result["body"])
        assert body["results"][0]["status"] == "skipped"

    def test_empty_records(self):
        result = handler({"Records": []}, None)
        body = json.loads(result["body"])
        assert body["processed"] == 0
        assert body["results"] == []


class TestLambdaMultipleRecords:
    """Test handling of multiple S3 records in one event."""

    def test_processes_all_records(self):
        event = {
            "Records": [
                {"eventVersion": "2.1", "eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
                 "s3": {"bucket": {"name": "ocr-documents"}, "object": {"key": "uploads/doc-1/a.png", "size": 100}}},
                {"eventVersion": "2.1", "eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
                 "s3": {"bucket": {"name": "ocr-documents"}, "object": {"key": "uploads/doc-2/b.png", "size": 200}}},
            ]
        }

        with patch("handler.urllib.request.urlopen", return_value=mock_urlopen_success()):
            result = handler(event, None)

        body = json.loads(result["body"])
        assert body["processed"] == 2
        doc_ids = [r["doc_id"] for r in body["results"]]
        assert "doc-1" in doc_ids
        assert "doc-2" in doc_ids


class TestLambdaAPICall:
    """Test the Lambda → API server call behavior."""

    def test_calls_correct_endpoint(self):
        event = make_s3_event("ocr-documents", "uploads/test-doc-id/file.png")

        with patch("handler.urllib.request.urlopen", return_value=mock_urlopen_success()) as mock_urlopen:
            handler(event, None)

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "/ocr/process" in req.full_url
        assert req.method == "POST"

        payload = json.loads(req.data)
        assert payload["doc_id"] == "test-doc-id"

    def test_uses_api_base_url_from_env(self):
        event = make_s3_event("bucket", "uploads/envtest/file.png")

        with patch.dict(os.environ, {"API_BASE_URL": "http://custom:9000"}):
            # Need to re-import to pick up the env change
            import importlib
            import handler as h
            importlib.reload(h)

            with patch("handler.urllib.request.urlopen", return_value=mock_urlopen_success()) as mock_urlopen:
                h.handler(event, None)

            req = mock_urlopen.call_args[0][0]
            assert req.full_url.startswith("http://custom:9000")

        # Restore
        import importlib
        import handler as h
        importlib.reload(h)

    def test_handles_http_error(self):
        import urllib.error
        event = make_s3_event("ocr-documents", "uploads/fail-doc/file.png")

        mock_error = urllib.error.HTTPError(
            url="http://api-server:8000/ocr/process",
            code=500, msg="Internal Server Error", hdrs={},
            fp=MagicMock(read=MagicMock(return_value=b'{"detail":"db error"}')),
        )

        with patch("handler.urllib.request.urlopen", side_effect=mock_error):
            result = handler(event, None)

        body = json.loads(result["body"])
        assert body["results"][0]["status"] == "error"
        assert body["results"][0]["http_code"] == 500

    def test_handles_connection_error(self):
        event = make_s3_event("ocr-documents", "uploads/timeout-doc/file.png")

        with patch("handler.urllib.request.urlopen", side_effect=ConnectionError("Connection refused")):
            result = handler(event, None)

        body = json.loads(result["body"])
        assert body["results"][0]["status"] == "error"
        assert "Connection refused" in body["results"][0]["error"]

    def test_always_returns_200(self):
        """Lambda should return 200 even if processing fails — errors are logged."""
        event = make_s3_event("ocr-documents", "uploads/any-doc/file.png")

        with patch("handler.urllib.request.urlopen", side_effect=Exception("total failure")):
            result = handler(event, None)

        assert result["statusCode"] == 200
