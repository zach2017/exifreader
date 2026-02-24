#!/usr/bin/env python3
"""
SQS → Lambda Poller (Direct Handler Invocation)
=================================================
LocalStack's event-source-mapping and Lambda invocation are broken.
This script replaces BOTH by:

  1. Polling SQS queues using boto3 (real AWS SDK calls to LocalStack)
  2. Directly importing and calling the Lambda handler.py functions
  3. Deleting messages on success, letting visibility timeout handle retries

This runs as a Docker container with ALL Lambda dependencies installed
(pdfplumber, python-docx, pytesseract, Pillow, etc.)
"""

import json
import sys
import os
import time
import logging
import importlib.util
from datetime import datetime

# ─── Configure logging ────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [POLLER] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
log = logging.getLogger('poller')

# ─── Config from environment ──────────────────────────
LOCALSTACK_URL = os.environ.get('AWS_ENDPOINT_URL', 'http://localstack:4566')
REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
POLL_WAIT = int(os.environ.get('POLL_WAIT', '5'))
STARTUP_DELAY = int(os.environ.get('STARTUP_DELAY', '25'))

QUEUE_LAMBDA_MAP = {
    'file-router-queue':  '/opt/lambdas/file-router/handler.py',
    'text-extract-queue': '/opt/lambdas/text-extractor/handler.py',
    'ocr-queue':          '/opt/lambdas/ocr-extractor/handler.py',
}

# ─── Load Lambda handlers as Python modules ───────────
handlers = {}

def load_handler(queue_name, handler_path):
    """Import a handler.py as a uniquely named module."""
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
            log.info(f"✓ Loaded {handler_path} as '{module_name}'")
            return module.lambda_handler
        else:
            log.error(f"✗ No lambda_handler in {handler_path}")
            return None
    except Exception as e:
        log.error(f"✗ Failed to load {handler_path}: {e}")
        return None

def load_all_handlers():
    """Load all Lambda handlers. Must be called AFTER env vars are set."""
    for queue_name, path in QUEUE_LAMBDA_MAP.items():
        fn = load_handler(queue_name, path)
        if fn:
            handlers[queue_name] = fn
        else:
            log.warning(f"  Skipping queue '{queue_name}' — handler not available")

# ─── Fake Lambda context object ───────────────────────
class FakeContext:
    function_name = 'poller'
    function_version = '$LATEST'
    invoked_function_arn = 'arn:aws:lambda:us-east-1:000000000000:function:poller'
    memory_limit_in_mb = 2048
    aws_request_id = 'local-poller'
    log_group_name = '/aws/lambda/poller'
    log_stream_name = 'local'

    def get_remaining_time_in_millis(self):
        return 300000  # 5 minutes

# ─── SQS operations using boto3 ──────────────────────
import boto3

sqs = None

def init_sqs():
    global sqs
    sqs = boto3.client(
        'sqs',
        endpoint_url=LOCALSTACK_URL,
        region_name=REGION,
        aws_access_key_id='test',
        aws_secret_access_key='test',
    )

def get_queue_url(queue_name):
    return f"{LOCALSTACK_URL}/000000000000/{queue_name}"

def receive_messages(queue_name, max_msgs=1):
    """Long-poll SQS and return messages."""
    try:
        resp = sqs.receive_message(
            QueueUrl=get_queue_url(queue_name),
            MaxNumberOfMessages=max_msgs,
            WaitTimeSeconds=POLL_WAIT,
            VisibilityTimeout=120,
        )
        return resp.get('Messages', [])
    except Exception as e:
        log.error(f"SQS receive error on {queue_name}: {e}")
        return []

def delete_message(queue_name, receipt_handle):
    """Delete a processed message."""
    try:
        sqs.delete_message(
            QueueUrl=get_queue_url(queue_name),
            ReceiptHandle=receipt_handle,
        )
    except Exception as e:
        log.error(f"SQS delete error: {e}")

# ─── Main polling logic ──────────────────────────────
def process_message(queue_name, message):
    """Call the Lambda handler with the SQS message."""
    handler_fn = handlers.get(queue_name)
    if not handler_fn:
        log.error(f"No handler for queue {queue_name}")
        return False

    msg_id = message.get('MessageId', '?')[:8]
    body = message.get('Body', '{}')

    # Build the SQS event shape that Lambda handlers expect
    event = {
        'Records': [{
            'messageId': message.get('MessageId', ''),
            'receiptHandle': message.get('ReceiptHandle', ''),
            'body': body,
            'eventSource': 'aws:sqs',
            'eventSourceARN': f'arn:aws:sqs:{REGION}:000000000000:{queue_name}',
        }]
    }

    # Log what we're processing
    preview = body[:100]
    try:
        parsed = json.loads(body)
        if 'Records' in parsed:
            s3_key = parsed['Records'][0].get('s3', {}).get('object', {}).get('key', '')
            preview = f"S3 event → {s3_key}"
        elif 'file_id' in parsed:
            preview = f"file_id={parsed['file_id']}"
    except Exception:
        pass
    
    log.info(f"📩 {queue_name} [{msg_id}] {preview}")

    try:
        result = handler_fn(event, FakeContext())
        log.info(f"⚡ Handler OK → {json.dumps(result, default=str)[:150]}")
        return True
    except Exception as e:
        log.error(f"✗ Handler FAILED: {e}", exc_info=True)
        return False

def poll_queue(queue_name):
    """Poll one queue, process messages, return count processed."""
    messages = receive_messages(queue_name, max_msgs=1)
    processed = 0
    for msg in messages:
        success = process_message(queue_name, msg)
        if success:
            delete_message(queue_name, msg['ReceiptHandle'])
            processed += 1
            log.info(f"✓ Deleted message from {queue_name}")
        else:
            log.warning(f"⚠ Message NOT deleted — will retry after visibility timeout")
    return processed

# ─── Wait for LocalStack ─────────────────────────────
def wait_for_localstack():
    log.info(f"Waiting {STARTUP_DELAY}s for LocalStack to initialize...")
    time.sleep(STARTUP_DELAY)
    
    for attempt in range(30):
        try:
            import urllib.request
            req = urllib.request.Request(f"{LOCALSTACK_URL}/_localstack/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    log.info("✓ LocalStack is healthy")
                    return True
        except Exception:
            pass
        log.info(f"Waiting for LocalStack... ({attempt + 1}/30)")
        time.sleep(3)
    
    log.error("LocalStack not reachable")
    return False

def verify_queues():
    """Verify all queues exist."""
    for queue_name in QUEUE_LAMBDA_MAP:
        try:
            attrs = sqs.get_queue_attributes(
                QueueUrl=get_queue_url(queue_name),
                AttributeNames=['ApproximateNumberOfMessages'],
            )
            count = attrs.get('Attributes', {}).get('ApproximateNumberOfMessages', '?')
            log.info(f"✓ Queue '{queue_name}' — {count} messages")
        except Exception as e:
            log.error(f"✗ Queue '{queue_name}' not found: {e}")

# ─── Main ─────────────────────────────────────────────
def main():
    print("", flush=True)
    print("=" * 52, flush=True)
    print("  SQS → Lambda Poller (Direct Invocation)", flush=True)
    print("  Bypasses LocalStack Lambda — calls handlers", flush=True)
    print("  directly as Python functions", flush=True)
    print("=" * 52, flush=True)
    print("", flush=True)

    if not wait_for_localstack():
        sys.exit(1)

    init_sqs()
    verify_queues()

    log.info("Loading Lambda handlers...")
    load_all_handlers()

    if not handlers:
        log.error("No handlers loaded! Check volume mounts.")
        sys.exit(1)

    log.info(f"Active handlers: {list(handlers.keys())}")
    log.info(f"Starting poll loop (wait={POLL_WAIT}s per queue)")
    print("", flush=True)

    total = 0
    cycle = 0

    while True:
        cycle += 1
        cycle_count = 0

        for queue_name in handlers:
            try:
                n = poll_queue(queue_name)
                cycle_count += n
                total += n
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log.error(f"Poll error on {queue_name}: {e}", exc_info=True)

        # Heartbeat every ~60 cycles
        if cycle % 60 == 0:
            log.info(f"♥ Heartbeat — cycle {cycle}, total processed: {total}")

        # Brief sleep between cycles if nothing processed
        if cycle_count == 0:
            time.sleep(1)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log.info("Shutting down")
        sys.exit(0)
