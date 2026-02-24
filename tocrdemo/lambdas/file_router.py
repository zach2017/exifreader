"""
Lambda 1: File Router
======================
Deployed on LocalStack. Triggered by S3 PutObject events.
Classifies the uploaded file and invokes file-processor Lambda
for PDFs and images.

LAMBDA-TO-LAMBDA INVOCATION PATTERNS:
--------------------------------------
1. boto3 direct invoke (used here) — sync or async
2. Step Functions — orchestrated workflows
3. SNS/SQS — decoupled fan-out
"""

import json
import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config ───────────────────────────────────────────────────
# When LAMBDA_EXECUTOR=local, lambdas run INSIDE the LocalStack
# container, so the endpoint is localhost:4566
ENDPOINT = os.environ.get('LOCALSTACK_ENDPOINT', 'http://localhost:4566')
REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
PDF_EXTS = {'.pdf'}


def _client(service):
    """Create a boto3 client pointing at LocalStack."""
    return boto3.client(
        service,
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id='test',
        aws_secret_access_key='test',
    )


def classify(key):
    """Return 'pdf', 'image', or None based on file extension."""
    ext = os.path.splitext(key)[1].lower()
    if ext in PDF_EXTS:
        return 'pdf', ext
    if ext in IMAGE_EXTS:
        return 'image', ext
    return None, ext


def handler(event, context):
    """
    S3 event handler.

    Event shape from S3 notification:
    {
      "Records": [{
        "s3": {
          "bucket": {"name": "file-uploads"},
          "object": {"key": "uploads/photo.png", "size": 12345}
        }
      }]
    }
    """
    logger.info("========== FILE ROUTER START ==========")
    logger.info(f"Event: {json.dumps(event, default=str)}")

    lambda_client = _client('lambda')
    results = []

    for record in event.get('Records', []):
        s3_info = record.get('s3', {})
        bucket = s3_info.get('bucket', {}).get('name', '')
        key = s3_info.get('object', {}).get('key', '')
        size = s3_info.get('object', {}).get('size', 0)

        file_type, ext = classify(key)

        logger.info(f"File: s3://{bucket}/{key} | size={size} | type={file_type} | ext={ext}")

        if file_type is None:
            logger.info(f"SKIP: unsupported extension '{ext}'")
            results.append({
                'key': key,
                'status': 'skipped',
                'reason': f"Unsupported extension: {ext}",
            })
            continue

        # ── INVOKE file-processor Lambda ─────────────────────
        # This is the core Lambda-to-Lambda call using boto3.
        #
        # InvocationType:
        #   'RequestResponse' = synchronous (waits for result)
        #   'Event'           = asynchronous (fire-and-forget)
        #   'DryRun'          = validate only
        #
        invoke_payload = {
            'bucket': bucket,
            'key': key,
            'size': size,
            'file_type': file_type,
            'extension': ext,
            'source_lambda': 'file-router',
        }

        logger.info(f"INVOKE file-processor: {json.dumps(invoke_payload)}")

        try:
            response = lambda_client.invoke(
                FunctionName='file-processor',
                InvocationType='RequestResponse',
                Payload=json.dumps(invoke_payload),
            )

            resp_payload = json.loads(response['Payload'].read().decode('utf-8'))
            status_code = response.get('StatusCode', 0)

            logger.info(f"file-processor responded ({status_code}): {json.dumps(resp_payload, default=str)}")

            results.append({
                'key': key,
                'file_type': file_type,
                'status': 'processed',
                'processor_response': resp_payload,
            })

        except Exception as e:
            logger.error(f"ERROR invoking file-processor: {e}")
            results.append({
                'key': key,
                'file_type': file_type,
                'status': 'error',
                'error': str(e),
            })

    response_body = {
        'message': 'File routing complete',
        'files_processed': len([r for r in results if r['status'] == 'processed']),
        'files_skipped': len([r for r in results if r['status'] == 'skipped']),
        'results': results,
    }

    logger.info(f"========== FILE ROUTER END ==========")
    logger.info(f"Response: {json.dumps(response_body, default=str)}")

    return {
        'statusCode': 200,
        'body': json.dumps(response_body, default=str),
    }
