"""
Tests for S3 bucket operations using moto mock.
Verifies bucket creation, object CRUD, key patterns,
and notification configuration.
"""

import json
import uuid

import boto3
import pytest
from moto import mock_aws


class TestS3BucketCreation:
    """Test S3 bucket creation and verification."""

    @mock_aws
    def test_create_bucket_us_east_1(self):
        """us-east-1 should NOT require LocationConstraint."""
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="ocr-documents")

        response = client.head_bucket(Bucket="ocr-documents")
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    @mock_aws
    def test_create_bucket_other_region(self):
        """Non us-east-1 regions require LocationConstraint."""
        client = boto3.client("s3", region_name="eu-west-1")
        client.create_bucket(
            Bucket="ocr-documents",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        response = client.head_bucket(Bucket="ocr-documents")
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    @mock_aws
    def test_create_bucket_idempotent(self):
        """Creating the same bucket twice should not raise."""
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="ocr-documents")
        client.create_bucket(Bucket="ocr-documents")

        buckets = client.list_buckets()["Buckets"]
        names = [b["Name"] for b in buckets]
        assert names.count("ocr-documents") == 1

    @mock_aws
    def test_bucket_appears_in_list(self):
        """Bucket should appear in list_buckets after creation."""
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="ocr-documents")

        names = [b["Name"] for b in client.list_buckets()["Buckets"]]
        assert "ocr-documents" in names


class TestS3ObjectOperations:
    """Test S3 object upload, download, listing, and deletion."""

    def test_upload_and_download(self, s3_client):
        body = b"test file content"
        s3_client.put_object(
            Bucket="test-ocr-documents",
            Key="uploads/abc-123/document.png",
            Body=body,
            ContentType="image/png",
        )

        obj = s3_client.get_object(Bucket="test-ocr-documents", Key="uploads/abc-123/document.png")
        assert obj["Body"].read() == body
        assert obj["ContentType"] == "image/png"

    def test_head_object(self, s3_client):
        s3_client.put_object(Bucket="test-ocr-documents", Key="uploads/test-id/file.png", Body=b"content")

        head = s3_client.head_object(Bucket="test-ocr-documents", Key="uploads/test-id/file.png")
        assert head["ContentLength"] == 7

    def test_upload_key_pattern(self, s3_client):
        """Verify uploads/{doc_id}/filename key pattern works."""
        doc_id = str(uuid.uuid4())
        key = f"uploads/{doc_id}/scan.pdf"

        s3_client.put_object(Bucket="test-ocr-documents", Key=key, Body=b"pdf content")

        response = s3_client.list_objects_v2(Bucket="test-ocr-documents", Prefix=f"uploads/{doc_id}/")
        keys = [obj["Key"] for obj in response.get("Contents", [])]
        assert key in keys

    def test_text_output_key_pattern(self, s3_client):
        """Verify text/{doc_id}/extracted.txt key pattern."""
        doc_id = str(uuid.uuid4())
        text_key = f"text/{doc_id}/extracted.txt"

        s3_client.put_object(
            Bucket="test-ocr-documents", Key=text_key,
            Body="Extracted text here".encode("utf-8"), ContentType="text/plain",
        )

        obj = s3_client.get_object(Bucket="test-ocr-documents", Key=text_key)
        assert obj["Body"].read().decode("utf-8") == "Extracted text here"

    def test_list_uploads_prefix(self, s3_client):
        """List only objects under uploads/ prefix."""
        s3_client.put_object(Bucket="test-ocr-documents", Key="uploads/a/file1.png", Body=b"1")
        s3_client.put_object(Bucket="test-ocr-documents", Key="uploads/b/file2.png", Body=b"2")
        s3_client.put_object(Bucket="test-ocr-documents", Key="text/a/extracted.txt", Body=b"3")

        response = s3_client.list_objects_v2(Bucket="test-ocr-documents", Prefix="uploads/")
        keys = [obj["Key"] for obj in response["Contents"]]
        assert len(keys) == 2
        assert all(k.startswith("uploads/") for k in keys)

    def test_overwrite_object(self, s3_client):
        key = "uploads/doc1/file.png"
        s3_client.put_object(Bucket="test-ocr-documents", Key=key, Body=b"original")
        s3_client.put_object(Bucket="test-ocr-documents", Key=key, Body=b"updated")

        obj = s3_client.get_object(Bucket="test-ocr-documents", Key=key)
        assert obj["Body"].read() == b"updated"

    def test_delete_object(self, s3_client):
        key = "uploads/del/file.png"
        s3_client.put_object(Bucket="test-ocr-documents", Key=key, Body=b"data")
        s3_client.delete_object(Bucket="test-ocr-documents", Key=key)

        response = s3_client.list_objects_v2(Bucket="test-ocr-documents", Prefix="uploads/del/")
        assert response.get("KeyCount", 0) == 0

    def test_read_write_roundtrip(self, s3_client):
        """Full put → get → verify cycle."""
        key = "uploads/roundtrip/doc.png"
        body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Fake PNG header
        s3_client.put_object(Bucket="test-ocr-documents", Key=key, Body=body, ContentType="image/png")

        obj = s3_client.get_object(Bucket="test-ocr-documents", Key=key)
        assert obj["Body"].read() == body


class TestS3NotificationConfig:
    """Test S3 bucket notification configuration for Lambda triggers."""

    @mock_aws
    def test_put_notification_configuration(self):
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="ocr-documents")

        config = {
            "LambdaFunctionConfigurations": [{
                "Id": "ocr-upload-trigger",
                "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:ocr-trigger",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {
                    "Key": {"FilterRules": [{"Name": "prefix", "Value": "uploads/"}]}
                },
            }]
        }

        client.put_bucket_notification_configuration(
            Bucket="ocr-documents", NotificationConfiguration=config,
        )

        result = client.get_bucket_notification_configuration(Bucket="ocr-documents")
        assert len(result.get("LambdaFunctionConfigurations", [])) == 1
        assert result["LambdaFunctionConfigurations"][0]["Id"] == "ocr-upload-trigger"

    @mock_aws
    def test_notification_filter_prefix(self):
        """Verify the notification only triggers on uploads/ prefix."""
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="ocr-documents")

        config = {
            "LambdaFunctionConfigurations": [{
                "Id": "ocr-trigger",
                "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:ocr-trigger",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {
                    "Key": {"FilterRules": [{"Name": "prefix", "Value": "uploads/"}]}
                },
            }]
        }

        client.put_bucket_notification_configuration(
            Bucket="ocr-documents", NotificationConfiguration=config,
        )

        result = client.get_bucket_notification_configuration(Bucket="ocr-documents")
        rules = result["LambdaFunctionConfigurations"][0]["Filter"]["Key"]["FilterRules"]
        assert any(r["Name"] == "prefix" and r["Value"] == "uploads/" for r in rules)
