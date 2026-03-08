import json
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from processors import (
    cleanup_temp_file,
    download_s3_file,
    extract_text,
    ocr_file,
    process_document_pipeline,
)

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("sqs-document-worker")

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")

SQS_QUEUE_URL = os.getenv(
    "SQS_QUEUE_URL",
    "http://localstack:4566/000000000000/document-uploaded-queue",
)
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "documents")

POLL_WAIT_SECONDS = int(os.getenv("POLL_WAIT_SECONDS", "10"))
VISIBILITY_TIMEOUT = int(os.getenv("VISIBILITY_TIMEOUT", "60"))
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "1"))
SLEEP_ON_EMPTY = int(os.getenv("SLEEP_ON_EMPTY", "2"))

RUNNING = True


def handle_shutdown(signum: int, frame: Any) -> None:
    global RUNNING
    logger.info("Shutdown signal received: %s", signum)
    RUNNING = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# -----------------------------------------------------------------------------
# AWS clients
# -----------------------------------------------------------------------------
def create_boto3_client(service_name: str):
    return boto3.client(
        service_name,
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        endpoint_url=AWS_ENDPOINT_URL,
    )


sqs_client = create_boto3_client("sqs")
s3_client = create_boto3_client("s3")


# -----------------------------------------------------------------------------
# Message parsing / validation
# -----------------------------------------------------------------------------
def parse_message_body(body: str) -> Dict[str, Any]:
    """
    Expected message example:
    {
      "DocumentId": "12345",
      "Bucket": "documents",
      "Key": "uploads/12345/sample.png",
      "DocumentType": "image/png"
    }
    """
    try:
        payload = json.loads(body)
        logger.debug("Parsed message payload: %s", payload)
        return payload
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON message body: {exc}") from exc


def validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    document_id = payload.get("DocumentId")
    bucket = payload.get("Bucket", S3_BUCKET_NAME)
    key = payload.get("Key")
    document_type = payload.get("DocumentType", "unknown")

    if not document_id:
        raise ValueError("Missing required field: DocumentId")

    if not key:
        # fallback example convention if key not supplied
        key = f"uploads/{document_id}"

    return {
        "DocumentId": document_id,
        "Bucket": bucket,
        "Key": key,
        "DocumentType": document_type,
    }


# -----------------------------------------------------------------------------
# Processing phases
# -----------------------------------------------------------------------------
def phase_receive_message() -> Optional[Dict[str, Any]]:
    logger.info("Polling SQS queue: %s", SQS_QUEUE_URL)

    response = sqs_client.receive_message(
        QueueUrl=SQS_QUEUE_URL,
        MaxNumberOfMessages=MAX_MESSAGES,
        WaitTimeSeconds=POLL_WAIT_SECONDS,
        VisibilityTimeout=VISIBILITY_TIMEOUT,
    )

    messages = response.get("Messages", [])
    if not messages:
        logger.debug("No messages received")
        return None

    return messages[0]


def phase_parse_message(message: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Phase: parse_message")
    body = message.get("Body", "")
    payload = parse_message_body(body)
    validated = validate_payload(payload)
    logger.info(
        "Message validated | DocumentId=%s Bucket=%s Key=%s Type=%s",
        validated["DocumentId"],
        validated["Bucket"],
        validated["Key"],
        validated["DocumentType"],
    )
    return validated


def phase_download_document(payload: Dict[str, Any]) -> str:
    logger.info("Phase: download_document | DocumentId=%s", payload["DocumentId"])
    local_path = download_s3_file(
        s3_client=s3_client,
        bucket_name=payload["Bucket"],
        object_key=payload["Key"],
        document_id=payload["DocumentId"],
    )
    logger.info("Downloaded file to: %s", local_path)
    return local_path


def phase_extract_content(local_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Phase: extract_content | file=%s", local_path)

    result = process_document_pipeline(
        file_path=local_path,
        document_type=payload["DocumentType"],
    )

    logger.info(
        "Extraction complete | method=%s chars=%s",
        result.get("method"),
        len(result.get("text", "")),
    )
    return result


def phase_delete_message(receipt_handle: str) -> None:
    logger.info("Phase: delete_message")
    sqs_client.delete_message(
        QueueUrl=SQS_QUEUE_URL,
        ReceiptHandle=receipt_handle,
    )
    logger.info("Message deleted from queue")


def phase_handle_success(payload: Dict[str, Any], result: Dict[str, Any]) -> None:
    logger.info(
        "SUCCESS | DocumentId=%s | Method=%s | Preview=%s",
        payload["DocumentId"],
        result.get("method"),
        result.get("text", "")[:120].replace("\n", " "),
    )


def phase_handle_failure(message: Optional[Dict[str, Any]], exc: Exception) -> None:
    logger.exception("FAILED processing message: %s", exc)

    # Optional: leave message in queue for retry by not deleting it.
    # Could also send to a dead-letter queue in a fuller implementation.


# -----------------------------------------------------------------------------
# Main message handler
# -----------------------------------------------------------------------------
def handle_message(message: Dict[str, Any]) -> None:
    payload: Optional[Dict[str, Any]] = None
    local_path: Optional[str] = None

    try:
        payload = phase_parse_message(message)
        local_path = phase_download_document(payload)
        result = phase_extract_content(local_path, payload)
        phase_handle_success(payload, result)
        phase_delete_message(message["ReceiptHandle"])

    except (ValueError, ClientError, BotoCoreError, RuntimeError, OSError) as exc:
        phase_handle_failure(message, exc)

    finally:
        if local_path:
            cleanup_temp_file(local_path)


# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------
def run() -> None:
    logger.info("Starting SQS document worker...")
    logger.info("AWS endpoint: %s", AWS_ENDPOINT_URL)
    logger.info("Queue URL: %s", SQS_QUEUE_URL)
    logger.info("Bucket: %s", S3_BUCKET_NAME)

    while RUNNING:
        try:
            message = phase_receive_message()
            if not message:
                time.sleep(SLEEP_ON_EMPTY)
                continue

            handle_message(message)

        except (ClientError, BotoCoreError) as exc:
            logger.exception("AWS communication error: %s", exc)
            time.sleep(5)

        except Exception as exc:
            logger.exception("Unexpected top-level error: %s", exc)
            time.sleep(5)

    logger.info("Worker stopped cleanly")


if __name__ == "__main__":
    run()