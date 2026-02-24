"""
Unit Tests for Document Processing Pipeline
=============================================
Tests the file classification, routing logic, and helper functions
without requiring AWS services (uses mocks).
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Add lambda directories to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambdas', 'file-router'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambdas', 'text-extractor'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambdas', 'ocr-extractor'))


class TestFileClassification:
    """Test the file type classification logic."""

    def test_classify_pdf(self):
        from handler import classify_file
        category, mime = classify_file('document.pdf')
        assert category == 'pdf'
        assert mime == 'application/pdf'

    def test_classify_docx(self):
        from handler import classify_file
        category, _ = classify_file('report.docx')
        assert category == 'word'

    def test_classify_doc(self):
        from handler import classify_file
        category, _ = classify_file('old_report.doc')
        assert category == 'word'

    def test_classify_png(self):
        from handler import classify_file
        category, _ = classify_file('screenshot.png')
        assert category == 'image'

    def test_classify_jpg(self):
        from handler import classify_file
        category, _ = classify_file('photo.jpg')
        assert category == 'image'

    def test_classify_jpeg(self):
        from handler import classify_file
        category, _ = classify_file('photo.jpeg')
        assert category == 'image'

    def test_classify_tiff(self):
        from handler import classify_file
        category, _ = classify_file('scan.tiff')
        assert category == 'image'

    def test_classify_txt(self):
        from handler import classify_file
        category, _ = classify_file('notes.txt')
        assert category == 'text'

    def test_classify_csv(self):
        from handler import classify_file
        category, _ = classify_file('data.csv')
        assert category == 'text'

    def test_classify_json(self):
        from handler import classify_file
        category, _ = classify_file('config.json')
        assert category == 'text'

    def test_classify_html(self):
        from handler import classify_file
        category, _ = classify_file('page.html')
        assert category == 'text'

    def test_classify_unknown(self):
        from handler import classify_file
        category, _ = classify_file('archive.rar')
        assert category == 'other'

    def test_classify_with_mime_override(self):
        from handler import classify_file
        category, mime = classify_file('file.bin', 'application/pdf')
        assert category == 'pdf'

    def test_classify_no_extension(self):
        from handler import classify_file
        category, _ = classify_file('README')
        assert category == 'other'


class TestSQSEventParsing:
    """Test SQS event message parsing."""

    def _make_sqs_s3_event(self, bucket, key, size=100):
        return {
            'Records': [{
                'body': json.dumps({
                    'Records': [{
                        's3': {
                            'bucket': {'name': bucket},
                            'object': {'key': key, 'size': size}
                        }
                    }]
                })
            }]
        }

    @patch('handler.process_s3_event')
    def test_sqs_event_parsing(self, mock_process):
        from handler import lambda_handler
        event = self._make_sqs_s3_event('docproc-bucket', 'uploads/abc-123/test.pdf', 1024)
        lambda_handler(event, None)
        mock_process.assert_called_once()

    @patch('handler.process_s3_event')
    def test_multiple_records(self, mock_process):
        from handler import lambda_handler
        event = {
            'Records': [
                {'body': json.dumps({'Records': [{'s3': {'bucket': {'name': 'b'}, 'object': {'key': 'uploads/1/a.pdf', 'size': 1}}}]})},
                {'body': json.dumps({'Records': [{'s3': {'bucket': {'name': 'b'}, 'object': {'key': 'uploads/2/b.pdf', 'size': 2}}}]})}
            ]
        }
        lambda_handler(event, None)
        assert mock_process.call_count == 2


class TestStepFunctionActions:
    """Test Step Function action dispatching."""

    @patch('handler.sqs')
    @patch('handler.update_processing_step')
    def test_send_ocr_batch(self, mock_step, mock_sqs):
        from handler import handle_step_function_action
        event = {
            'action': 'send_ocr_batch',
            'file_id': 'test-123',
            'image_keys': ['img1.png', 'img2.png', 'img3.png']
        }
        result = handle_step_function_action(event)
        assert result['images_queued'] == 3
        assert mock_sqs.send_message.call_count == 3

    @patch('handler.sqs')
    @patch('handler.update_processing_step')
    def test_send_text_extract(self, mock_step, mock_sqs):
        from handler import handle_step_function_action
        event = {
            'action': 'send_text_extract',
            'file_id': 'test-123',
            's3_key': 'uploads/test-123/doc.pdf'
        }
        result = handle_step_function_action(event)
        assert result['text_extract_queued'] is True

    @patch('handler.update_status')
    def test_update_metadata(self, mock_status):
        from handler import handle_step_function_action
        event = {
            'action': 'update_metadata',
            'file_id': 'test-123',
            'status': 'COMPLETED'
        }
        result = handle_step_function_action(event)
        assert result['status'] == 'COMPLETED'
        mock_status.assert_called_with('test-123', 'COMPLETED')

    def test_unknown_action(self):
        from handler import handle_step_function_action
        result = handle_step_function_action({'action': 'invalid', 'file_id': 'x'})
        assert result['statusCode'] == 400


class TestHelperFunctions:
    """Test utility/helper functions."""

    def test_format_s3_key_with_subdirectories(self):
        """Verify S3 key parsing handles nested paths."""
        key = 'uploads/abc-123/subfolder/document.pdf'
        parts = key.split('/')
        file_id = parts[1]
        filename = '/'.join(parts[2:])
        assert file_id == 'abc-123'
        assert filename == 'subfolder/document.pdf'

    def test_skip_non_upload_keys(self):
        """Files outside uploads/ prefix should be skipped."""
        key = 'extracted/abc-123/output.txt'
        assert not key.startswith('uploads/')
