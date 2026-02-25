#!/usr/bin/env python3
"""
SQS → Lambda Poller v2
=======================
Bypasses LocalStack's broken Lambda entirely.
Polls SQS queues and directly calls Lambda handler.py functions.

KEY FIX: Creates queues itself — never depends on init script timing.
Uses sqs.get_queue_url() to resolve proper queue URLs.
"""

import json
import sys
import os
import time
import logging
import importlib.util
import traceback

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [POLLER] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
log = logging.getLogger('poller')

# ─── Config ───────────────────────────────────────────
LOCALSTACK_URL = os.environ.get('AWS_ENDPOINT_URL', 'http://localstack:4566')
REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
POLL_WAIT = int(os.environ.get('POLL_WAIT', '5'))
STARTUP_DELAY = int(os.environ.get('STARTUP_DELAY', '20'))

QUEUE_HANDLER_MAP = {
    'file-router-queue':  '/opt/lambdas/file-router/handler.py',
    'text-extract-queue': '/opt/lambdas/text-extractor/handler.py',
    'ocr-queue':          '/opt/lambdas/ocr-extractor/handler.py',
}

# Resolved queue URLs (populated at startup)
queue_urls = {}
handlers = {}

# ─── AWS clients ──────────────────────────────────────
import boto3

sqs_client = None
s3_client = None
dynamodb_resource = None


def init_aws():
    global sqs_client, s3_client, dynamodb_resource
    kwargs = {
        'endpoint_url': LOCALSTACK_URL,
        'region_name': REGION,
        'aws_access_key_id': 'test',
        'aws_secret_access_key': 'test',
    }
    sqs_client = boto3.client('sqs', **kwargs)
    s3_client = boto3.client('s3', **kwargs)
    dynamodb_resource = boto3.resource('dynamodb', **kwargs)


# ─── Create queues (idempotent) ───────────────────────
def ensure_queues():
    """Create all queues if they don't exist. Returns True if all ready."""
    dlqs = {
        'file-router-dlq': None,
        'text-extract-dlq': None,
        'ocr-dlq': None,
    }
    main_queues = {
        'file-router-queue': {'VisibilityTimeout': '120', 'dlq': 'file-router-dlq'},
        'text-extract-queue': {'VisibilityTimeout': '360', 'dlq': 'text-extract-dlq'},
        'ocr-queue': {'VisibilityTimeout': '600', 'dlq': 'ocr-dlq'},
    }

    # Create DLQs first
    for dlq_name in dlqs:
        try:
            resp = sqs_client.create_queue(QueueName=dlq_name)
            dlqs[dlq_name] = resp['QueueUrl']
            log.info(f"  ✓ DLQ '{dlq_name}'")
        except Exception as e:
            log.warning(f"  DLQ '{dlq_name}': {e}")

    # Create main queues with redrive policy
    all_ok = True
    for q_name, cfg in main_queues.items():
        try:
            dlq_arn = f"arn:aws:sqs:{REGION}:000000000000:{cfg['dlq']}"
            attrs = {
                'VisibilityTimeout': cfg['VisibilityTimeout'],
                'RedrivePolicy': json.dumps({
                    'deadLetterTargetArn': dlq_arn,
                    'maxReceiveCount': '3',
                }),
            }
            resp = sqs_client.create_queue(QueueName=q_name, Attributes=attrs)
            queue_urls[q_name] = resp['QueueUrl']
            log.info(f"  ✓ Queue '{q_name}' → {resp['QueueUrl']}")
        except Exception as e:
            log.error(f"  ✗ Queue '{q_name}': {e}")
            all_ok = False

    return all_ok


def ensure_s3_bucket():
    """Create S3 bucket if it doesn't exist."""
    bucket = os.environ.get('S3_BUCKET', 'docproc-bucket')
    try:
        s3_client.head_bucket(Bucket=bucket)
        log.info(f"  ✓ S3 bucket '{bucket}' exists")
    except Exception:
        try:
            s3_client.create_bucket(Bucket=bucket)
            log.info(f"  ✓ S3 bucket '{bucket}' created")
        except Exception as e:
            log.warning(f"  S3 bucket: {e}")


def ensure_dynamodb():
    """Create DynamoDB table if it doesn't exist."""
    table_name = os.environ.get('DYNAMODB_TABLE', 'document-metadata')
    try:
        table = dynamodb_resource.Table(table_name)
        table.load()
        log.info(f"  ✓ DynamoDB table '{table_name}' exists")
    except Exception:
        try:
            dynamodb_resource.create_table(
                TableName=table_name,
                KeySchema=[{'AttributeName': 'file_id', 'KeyType': 'HASH'}],
                AttributeDefinitions=[{'AttributeName': 'file_id', 'AttributeType': 'S'}],
                BillingMode='PAY_PER_REQUEST',
            )
            log.info(f"  ✓ DynamoDB table '{table_name}' created")
        except Exception as e:
            log.warning(f"  DynamoDB: {e}")


def setup_s3_notification():
    """Configure S3 → SQS notification for uploads/ prefix."""
    bucket = os.environ.get('S3_BUCKET', 'docproc-bucket')
    try:
        s3_client.put_bucket_notification_configuration(
            Bucket=bucket,
            NotificationConfiguration={
                'QueueConfigurations': [{
                    'QueueArn': f'arn:aws:sqs:{REGION}:000000000000:file-router-queue',
                    'Events': ['s3:ObjectCreated:*'],
                    'Filter': {
                        'Key': {'FilterRules': [{'Name': 'prefix', 'Value': 'uploads/'}]}
                    },
                }]
            }
        )
        log.info("  ✓ S3 notification: uploads/ → file-router-queue")
    except Exception as e:
        log.warning(f"  S3 notification: {e}")


# ─── Load Lambda handlers ────────────────────────────
class FakeContext:
    function_name = 'poller'
    function_version = '$LATEST'
    invoked_function_arn = 'arn:aws:lambda:us-east-1:000000000000:function:poller'
    memory_limit_in_mb = 2048
    aws_request_id = 'local-poller'
    log_group_name = '/aws/lambda/poller'
    log_stream_name = 'local'
    def get_remaining_time_in_millis(self):
        return 300000


def load_handler(queue_name, handler_path):
    module_name = queue_name.replace('-', '_') + '_handler'
    try:
        spec = importlib.util.spec_from_file_location(module_name, handler_path)
        if spec is None:
            log.error(f"Cannot find: {handler_path}")
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        if hasattr(module, 'lambda_handler'):
            log.info(f"  ✓ Loaded handler: {handler_path}")
            return module.lambda_handler
        else:
            log.error(f"  ✗ No lambda_handler in {handler_path}")
            return None
    except Exception as e:
        log.error(f"  ✗ Failed to load {handler_path}: {e}")
        traceback.print_exc()
        return None


def load_all_handlers():
    for queue_name, path in QUEUE_HANDLER_MAP.items():
        fn = load_handler(queue_name, path)
        if fn:
            handlers[queue_name] = fn


# ─── SQS polling ─────────────────────────────────────
def receive_messages(queue_name, max_msgs=1):
    url = queue_urls.get(queue_name)
    if not url:
        return []
    try:
        resp = sqs_client.receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=max_msgs,
            WaitTimeSeconds=POLL_WAIT,
            VisibilityTimeout=120,
        )
        return resp.get('Messages', [])
    except Exception as e:
        log.error(f"SQS receive {queue_name}: {e}")
        return []


def delete_message(queue_name, receipt_handle):
    url = queue_urls.get(queue_name)
    if not url:
        return
    try:
        sqs_client.delete_message(QueueUrl=url, ReceiptHandle=receipt_handle)
    except Exception as e:
        log.error(f"SQS delete: {e}")


def process_message(queue_name, message):
    handler_fn = handlers.get(queue_name)
    if not handler_fn:
        return False

    msg_id = message.get('MessageId', '?')[:8]
    body = message.get('Body', '{}')

    # Preview
    preview = body[:100]
    try:
        parsed = json.loads(body)
        if 'Records' in parsed:
            preview = f"S3 → {parsed['Records'][0].get('s3',{}).get('object',{}).get('key','?')}"
        elif 'file_id' in parsed:
            preview = f"file_id={parsed['file_id']}"
    except Exception:
        pass

    log.info(f"📩 {queue_name} [{msg_id}] {preview}")

    event = {
        'Records': [{
            'messageId': message.get('MessageId', ''),
            'receiptHandle': message.get('ReceiptHandle', ''),
            'body': body,
            'eventSource': 'aws:sqs',
            'eventSourceARN': f'arn:aws:sqs:{REGION}:000000000000:{queue_name}',
        }]
    }

    try:
        result = handler_fn(event, FakeContext())
        log.info(f"⚡ {queue_name} handler OK → {json.dumps(result, default=str)[:120]}")
        return True
    except Exception as e:
        log.error(f"✗ {queue_name} handler FAILED: {e}")
        traceback.print_exc()
        return False


def poll_queue(queue_name):
    messages = receive_messages(queue_name, max_msgs=1)
    processed = 0
    for msg in messages:
        if process_message(queue_name, msg):
            delete_message(queue_name, msg['ReceiptHandle'])
            log.info(f"✓ Deleted from {queue_name}")
            processed += 1
        else:
            log.warning(f"⚠ NOT deleted — will retry via visibility timeout")
    return processed


# ─── Startup ─────────────────────────────────────────
def wait_for_localstack():
    log.info(f"Waiting {STARTUP_DELAY}s for LocalStack...")
    time.sleep(STARTUP_DELAY)

    for attempt in range(30):
        try:
            import urllib.request
            with urllib.request.urlopen(f"{LOCALSTACK_URL}/_localstack/health", timeout=5) as r:
                if r.status == 200:
                    log.info("✓ LocalStack is healthy")
                    return True
        except Exception:
            pass
        log.info(f"  Waiting... ({attempt+1}/30)")
        time.sleep(3)

    log.error("LocalStack not reachable after timeout")
    return False


# ─── Main ────────────────────────────────────────────
def main():
    print("", flush=True)
    print("=" * 52, flush=True)
    print("  SQS → Lambda Poller v2", flush=True)
    print("  Creates resources + polls + calls handlers", flush=True)
    print("=" * 52, flush=True)
    print("", flush=True)

    if not wait_for_localstack():
        sys.exit(1)

    init_aws()

    # Create ALL resources ourselves — don't depend on init script
    log.info("Creating AWS resources...")
    ensure_s3_bucket()
    ensure_dynamodb()
    ensure_queues()
    setup_s3_notification()

    log.info("Loading Lambda handlers...")
    load_all_handlers()

    if not handlers:
        log.error("No handlers loaded! Check /opt/lambdas volume mount.")
        sys.exit(1)

    log.info(f"Ready: {list(handlers.keys())}")
    log.info(f"Queue URLs: {json.dumps(queue_urls, indent=2)}")
    log.info(f"Starting poll loop (wait={POLL_WAIT}s)")
    print("", flush=True)

    total = 0
    cycle = 0

    while True:
        cycle += 1
        n = 0
        for q in handlers:
            try:
                n += poll_queue(q)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log.error(f"Poll error {q}: {e}")

        total += n
        if cycle % 60 == 0:
            log.info(f"♥ cycle={cycle} total_processed={total}")
        if n == 0:
            time.sleep(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log.info("Shutting down")
        sys.exit(0)
