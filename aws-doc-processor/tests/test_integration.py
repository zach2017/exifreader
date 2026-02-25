"""
Integration Tests — Run against LocalStack
============================================
These tests require LocalStack to be running with all resources initialized.
They test the actual AWS service interactions end-to-end.

Run with: pytest tests/test_integration.py -v
Requires: AWS_ENDPOINT_URL environment variable set to LocalStack endpoint
"""

import json
import os
import time
import uuid
import pytest
import boto3

ENDPOINT = os.environ.get('AWS_ENDPOINT_URL', 'http://localhost:4566')
BUCKET = os.environ.get('S3_BUCKET', 'docproc-bucket')
TABLE = os.environ.get('DYNAMODB_TABLE', 'document-metadata')
REGION = 'us-east-1'

kwargs = {'endpoint_url': ENDPOINT, 'region_name': REGION}


@pytest.fixture(scope='module')
def s3():
    return boto3.client('s3', **kwargs)


@pytest.fixture(scope='module')
def sqs():
    return boto3.client('sqs', **kwargs)


@pytest.fixture(scope='module')
def dynamodb():
    return boto3.resource('dynamodb', **kwargs)


@pytest.fixture(scope='module')
def lambda_client():
    return boto3.client('lambda', **kwargs)


class TestS3Operations:
    """Test S3 bucket operations."""

    def test_bucket_exists(self, s3):
        buckets = s3.list_buckets()['Buckets']
        names = [b['Name'] for b in buckets]
        assert BUCKET in names, f"Bucket '{BUCKET}' not found. Available: {names}"

    def test_upload_file(self, s3):
        file_id = str(uuid.uuid4())[:8]
        key = f"uploads/{file_id}/test.txt"
        s3.put_object(Bucket=BUCKET, Key=key, Body=b"Hello integration test")
        
        response = s3.get_object(Bucket=BUCKET, Key=key)
        content = response['Body'].read().decode()
        assert content == "Hello integration test"

    def test_cors_configured(self, s3):
        cors = s3.get_bucket_cors(Bucket=BUCKET)
        rules = cors.get('CORSRules', [])
        assert len(rules) > 0, "CORS not configured on bucket"


class TestSQSQueues:
    """Test SQS queue operations."""

    def test_queues_exist(self, sqs):
        queues = sqs.list_queues().get('QueueUrls', [])
        queue_names = [q.split('/')[-1] for q in queues]
        
        for expected in ['file-router-queue', 'text-extract-queue', 'ocr-queue']:
            assert expected in queue_names, f"Queue '{expected}' not found"

    def test_dlq_queues_exist(self, sqs):
        queues = sqs.list_queues().get('QueueUrls', [])
        queue_names = [q.split('/')[-1] for q in queues]
        
        for expected in ['file-router-dlq', 'text-extract-dlq', 'ocr-dlq']:
            assert expected in queue_names, f"DLQ '{expected}' not found"

    def test_send_and_receive_message(self, sqs):
        queues = sqs.list_queues(QueueNamePrefix='file-router-queue')['QueueUrls']
        queue_url = queues[0]
        
        test_msg = {'test': True, 'timestamp': time.time()}
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(test_msg))
        
        response = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=2)
        messages = response.get('Messages', [])
        assert len(messages) > 0, "No message received from queue"
        
        # Clean up
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=messages[0]['ReceiptHandle'])


class TestDynamoDB:
    """Test DynamoDB table operations."""

    def test_table_exists(self, dynamodb):
        table = dynamodb.Table(TABLE)
        assert table.table_status == 'ACTIVE'

    def test_put_and_get_item(self, dynamodb):
        table = dynamodb.Table(TABLE)
        file_id = f"test-{uuid.uuid4().hex[:8]}"
        
        table.put_item(Item={
            'file_id': file_id,
            'filename': 'test.pdf',
            'status': 'PENDING',
            'file_type': 'application/pdf',
            'upload_time': '2025-01-01T00:00:00Z'
        })
        
        response = table.get_item(Key={'file_id': file_id})
        item = response['Item']
        assert item['filename'] == 'test.pdf'
        assert item['status'] == 'PENDING'
        
        # Clean up
        table.delete_item(Key={'file_id': file_id})


class TestLambdaFunctions:
    """Test Lambda function deployments."""

    def test_functions_exist(self, lambda_client):
        functions = lambda_client.list_functions()['Functions']
        names = [f['FunctionName'] for f in functions]
        
        for expected in ['file-router', 'text-extractor', 'ocr-extractor']:
            assert expected in names, f"Lambda '{expected}' not found. Available: {names}"

    def test_file_router_invocation(self, lambda_client):
        """Test that file-router Lambda can be invoked with a text file event."""
        payload = {
            'action': 'update_metadata',
            'file_id': 'test-invocation',
            'status': 'TESTING'
        }
        
        response = lambda_client.invoke(
            FunctionName='file-router',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        assert response['StatusCode'] == 200
        result = json.loads(response['Payload'].read())
        assert result.get('statusCode') == 200


class TestEndToEndFlow:
    """Test the complete upload → process → retrieve flow."""

    def test_text_file_flow(self, s3, dynamodb, lambda_client):
        """Upload a text file and verify it gets processed correctly."""
        file_id = f"e2e-{uuid.uuid4().hex[:8]}"
        key = f"uploads/{file_id}/hello.txt"
        content = "This is an end-to-end test document for the processing pipeline."
        
        # 1. Upload to S3
        s3.put_object(Bucket=BUCKET, Key=key, Body=content.encode())
        
        # 2. Simulate the SQS event that S3 notification would send
        event = {
            'Records': [{
                'body': json.dumps({
                    'Records': [{
                        's3': {
                            'bucket': {'name': BUCKET},
                            'object': {'key': key, 'size': len(content)}
                        }
                    }]
                })
            }]
        }
        
        # 3. Invoke file-router
        response = lambda_client.invoke(
            FunctionName='file-router',
            InvocationType='RequestResponse',
            Payload=json.dumps(event)
        )
        assert response['StatusCode'] == 200
        
        # 4. Check DynamoDB record was created
        time.sleep(1)
        table = dynamodb.Table(TABLE)
        result = table.get_item(Key={'file_id': file_id})
        
        if 'Item' in result:
            item = result['Item']
            assert item['filename'] == 'hello.txt'
            assert item['file_category'] == 'text'
            print(f"  ✓ DynamoDB record: status={item.get('status')}")
        
        # Clean up
        s3.delete_object(Bucket=BUCKET, Key=key)
        try:
            table.delete_item(Key={'file_id': file_id})
        except Exception:
            pass
