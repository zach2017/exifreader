"""
Lambda 1: S3 Event Handler (File Router)
=========================================
Triggered by S3 PUT events. Checks if the uploaded file is a PDF or image,
then invokes Lambda 2 (file-processor) with the file metadata.

KEY CONCEPT: Lambda-to-Lambda Invocation
-----------------------------------------
There are 3 ways to call a Lambda from another Lambda:

1. AWS SDK (boto3) - Direct Invocation (USED HERE)
   - Synchronous (RequestResponse) or Async (Event)
   - Best for: simple chains, low latency
   
2. AWS Step Functions
   - Orchestrates complex workflows
   - Best for: multi-step pipelines, retries, parallel execution
   
3. SNS/SQS
   - Decoupled, fan-out pattern
   - Best for: multiple consumers, retry with dead-letter queues
"""

import json
import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Supported file types ────────────────────────────────────────────
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
PDF_EXTENSIONS = {'.pdf'}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS

# ── LocalStack endpoint (for local dev) ─────────────────────────────
LOCALSTACK_ENDPOINT = os.environ.get('LOCALSTACK_ENDPOINT', 'http://host.docker.internal:4566')


def get_lambda_client():
    """Create a Lambda client pointing to LocalStack."""
    return boto3.client(
        'lambda',
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )


def get_s3_client():
    """Create an S3 client pointing to LocalStack."""
    return boto3.client(
        's3',
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )


def get_file_extension(key: str) -> str:
    """Extract lowercase file extension from S3 key."""
    _, ext = os.path.splitext(key)
    return ext.lower()


def classify_file(extension: str) -> str | None:
    """Classify a file as 'image', 'pdf', or None (unsupported)."""
    if extension in IMAGE_EXTENSIONS:
        return 'image'
    elif extension in PDF_EXTENSIONS:
        return 'pdf'
    return None


def handler(event, context):
    """
    Main handler - triggered by S3 PutObject event notification.
    
    Event structure (from S3):
    {
        "Records": [{
            "s3": {
                "bucket": {"name": "my-bucket"},
                "object": {"key": "file.pdf", "size": 12345}
            }
        }]
    }
    """
    logger.info(f"📥 File Router Lambda triggered with event: {json.dumps(event)}")

    lambda_client = get_lambda_client()
    s3_client = get_s3_client()
    results = []

    for record in event.get('Records', []):
        s3_info = record.get('s3', {})
        bucket = s3_info.get('bucket', {}).get('name', '')
        key = s3_info.get('object', {}).get('key', '')
        size = s3_info.get('object', {}).get('size', 0)

        logger.info(f"📄 Processing: s3://{bucket}/{key} ({size} bytes)")

        extension = get_file_extension(key)
        file_type = classify_file(extension)

        if file_type is None:
            msg = f"⏭️  Skipping unsupported file type: {extension}"
            logger.info(msg)
            results.append({'key': key, 'status': 'skipped', 'reason': msg})
            continue

        # ─────────────────────────────────────────────────────────
        # LAMBDA-TO-LAMBDA INVOCATION (Method 1: Direct via SDK)
        # ─────────────────────────────────────────────────────────
        #
        # InvocationType options:
        #   'RequestResponse' → Synchronous: waits for result (30s default timeout)
        #   'Event'           → Asynchronous: fire-and-forget (returns 202 immediately)
        #   'DryRun'          → Validates params without executing
        #
        payload = {
            'bucket': bucket,
            'key': key,
            'size': size,
            'file_type': file_type,         # 'image' or 'pdf'
            'extension': extension,
            'source_lambda': context.function_name if context else 'file-router',
        }

        logger.info(f"🚀 Invoking file-processor Lambda with payload: {json.dumps(payload)}")

        try:
            response = lambda_client.invoke(
                FunctionName='file-processor',          # Target Lambda name
                InvocationType='RequestResponse',       # Sync invocation
                Payload=json.dumps(payload),            # Must be JSON string
            )

            # Read the response payload
            response_payload = json.loads(response['Payload'].read().decode('utf-8'))
            status_code = response.get('StatusCode', 0)

            logger.info(f"✅ file-processor responded ({status_code}): {json.dumps(response_payload)}")

            results.append({
                'key': key,
                'file_type': file_type,
                'status': 'processed',
                'processor_response': response_payload,
            })

        except Exception as e:
            logger.error(f"❌ Error invoking file-processor: {str(e)}")
            results.append({
                'key': key,
                'file_type': file_type,
                'status': 'error',
                'error': str(e),
            })

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'File routing complete',
            'results': results,
        })
    }
