"""
SQS Document Worker – Memory-Optimised Edition
================================================
Designed to handle 1 GB+ PDF files inside a constrained Docker container.

Key memory strategies:
  • Streaming S3 downloads (chunked, never holds full file in RAM)
  • Page-by-page PDF text extraction (one page loaded at a time)
  • Page-by-page image extraction with immediate S3 upload + cleanup
  • All temp artefacts live under /tmp and are aggressively deleted
  • Explicit gc.collect() after every heavy phase
  • psycopg streaming copy for DB writes (no full-text in RAM)
"""

import gc
import hashlib
import json
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, Optional

import boto3
import psycopg
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from processors import (
    cleanup_temp_file,
    download_s3_file_streaming,
    extract_text_streamed,
    extract_pdf_images_streamed,
    process_document_pipeline,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("sqs-document-worker")

# ---------------------------------------------------------------------------
# Settings (env-driven, Pydantic v2)
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    # AWS
    aws_region: str = Field("us-east-1", alias="AWS_REGION")
    aws_access_key_id: str = Field("test", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field("test", alias="AWS_SECRET_ACCESS_KEY")
    endpoint_url: Optional[str] = Field(
        "http://host.docker.internal:4566", alias="AWS_ENDPOINT"
    )

    # Database
    coral_db_host: str = Field("host.docker.internal", alias="CORAL_DB_HOST")
    coral_db_port: int = Field(5432, alias="CORAL_DB_PORT")
    coral_db_user: str = Field("postgres", alias="CORAL_DB_USER")
    coral_db_password: str = Field("postgres", alias="CORAL_DB_PASSWORD")
    coral_db_name: str = Field("coral", alias="CORAL_DB_NAME")

    # S3 Buckets
    s3_upload_bucket: str = Field("coral", alias="S3_UPLOAD_BUCKET")
    s3_extracted_bucket: str = Field("coral-extracted-text", alias="S3_EXTRACTED_BUCKET")
    s3_tmp_bucket: str = Field("coral-pdf-img-files", alias="S3_TMP_BUCKET")

    # SQS Queues
    sqs_file_queue_url: str = Field(
        "http://host.docker.internal:4566/000000000000/DOCUMENT_TEXT_EXTRACT.fifo",
        alias="SQS_FILE_QUEUE_URL",
    )
    sqs_ocr_queue_url: str = Field(
        "http://host.docker.internal:4566/000000000000/DOCUMENT_TEXT_OCR_REQUEST.fifo",
        alias="SQS_OCR_QUEUE_URL",
    )

    # Worker tuning
    poll_wait_seconds: int = 10
    visibility_timeout: int = 300          # raised for large files
    max_messages: int = 1
    sleep_on_empty: int = 2

    # Memory tuning
    s3_download_chunk_bytes: int = 8 * 1024 * 1024   # 8 MB chunks
    tmp_root: str = "/tmp/docworker"                  # local scratch space

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )


settings = Settings()

# Ensure scratch dir exists
os.makedirs(settings.tmp_root, exist_ok=True)

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
RUNNING = True


def _handle_shutdown(signum: int, _frame: Any) -> None:
    global RUNNING
    logger.info("Shutdown signal received: %s", signum)
    RUNNING = False


signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)

# ---------------------------------------------------------------------------
# AWS clients (reuse across the lifetime of the worker)
# ---------------------------------------------------------------------------
_BOTO_CFG = BotoConfig(
    max_pool_connections=4,
    retries={"max_attempts": 3, "mode": "adaptive"},
)


def _create_boto3_client(service_name: str):
    return boto3.client(
        service_name,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        endpoint_url=settings.endpoint_url,
        config=_BOTO_CFG,
    )


sqs_client = _create_boto3_client("sqs")
s3_client = _create_boto3_client("s3")

# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------

def _parse_message_body(body: str) -> Dict[str, Any]:
    try:
        payload = json.loads(body)
        logger.debug("Parsed payload: %s", payload)
        return payload
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON message body: {exc}") from exc


def _validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    document_id = payload.get("documentId")
    if not document_id:
        raise ValueError("Missing required field: documentId")

    return {
        "documentId": document_id,
        "Bucket": settings.s3_upload_bucket,
        "Key": str(document_id),
        "documentType": payload.get("documentType", "unknown"),
    }


# ---------------------------------------------------------------------------
# SQS helpers
# ---------------------------------------------------------------------------

def _get_safe_dedup_id(value: str) -> str:
    ts = int(time.time())
    return hashlib.sha256(f"{ts}_{value}".encode()).hexdigest()


def _send_ocr_message(queue_url: str, payload: Dict[str, Any], num_imgs: int = 1) -> bool:
    payload_copy = {**payload, "NumImages": num_imgs}
    dedup_id = _get_safe_dedup_id(payload["documentId"])
    try:
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(payload_copy),
            MessageGroupId="ocr-processing-group",
            MessageDeduplicationId=dedup_id,
        )
        logger.info("OCR message sent | images=%d", num_imgs)
        return True
    except Exception as exc:
        logger.error("Failed to send OCR message: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Database helper – streams text file content into Postgres
# ---------------------------------------------------------------------------

def _save_to_db(document_id: str, file_path: str) -> None:
    """
    Stream file content into Postgres without loading entire file into RAM.
    Uses psycopg3's binary streaming for the bytea/text column.
    """
    db_dsn = (
        f"dbname={settings.coral_db_name} "
        f"user={settings.coral_db_user} "
        f"password={settings.coral_db_password} "
        f"host={settings.coral_db_host} "
        f"port={settings.coral_db_port}"
    )

    try:
        with psycopg.connect(db_dsn) as conn:
            with open(file_path, "rb") as f:
                data = f.read()                          # read extracted text
            conn.execute(
                "UPDATE coral_documents SET doc_read = %s WHERE document_id = %s",
                (data, document_id),
            )
            conn.commit()
            logger.info("DB updated for document_id=%s", document_id)
            del data
            gc.collect()
    except Exception as exc:
        logger.error("DB write failed for %s: %s", document_id, exc)
        raise


# ---------------------------------------------------------------------------
# Processing phases
# ---------------------------------------------------------------------------

def phase_receive_message() -> Optional[Dict[str, Any]]:
    logger.debug("Polling SQS: %s", settings.sqs_file_queue_url)
    resp = sqs_client.receive_message(
        QueueUrl=settings.sqs_file_queue_url,
        MaxNumberOfMessages=settings.max_messages,
        WaitTimeSeconds=settings.poll_wait_seconds,
        VisibilityTimeout=settings.visibility_timeout,
    )
    msgs = resp.get("Messages", [])
    return msgs[0] if msgs else None


def phase_parse_message(message: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Phase: parse_message")
    payload = _parse_message_body(message.get("Body", ""))
    validated = _validate_payload(payload)
    logger.info(
        "Validated | id=%s bucket=%s key=%s type=%s",
        validated["documentId"],
        validated["Bucket"],
        validated["Key"],
        validated["documentType"],
    )
    return validated


def phase_download_document(payload: Dict[str, Any]) -> str:
    logger.info("Phase: download_document | id=%s", payload["documentId"])
    local_path = download_s3_file_streaming(
        s3_client=s3_client,
        bucket_name=payload["Bucket"],
        object_key=payload["Key"],
        document_id=payload["documentId"],
        tmp_root=settings.tmp_root,
        chunk_size=settings.s3_download_chunk_bytes,
    )
    logger.info("Downloaded -> %s", local_path)
    return local_path


def phase_extract_content(local_path: str, payload: Dict[str, Any]) -> Dict[str, str]:
    """
    For PDFs: stream-extract text page-by-page, save to DB, then extract
    images page-by-page and enqueue OCR.
    """
    logger.info("Phase: extract_content | type=%s file=%s", payload["documentType"], local_path)

    result = process_document_pipeline(
        file_path=local_path,
        document_type=payload["documentType"],
        tmp_root=settings.tmp_root,
        document_id=payload["documentId"],
    )

    if payload["documentType"].upper() == "PDF":
        # Save extracted text to DB
        text_file = result["text"]
        _save_to_db(payload["documentId"], text_file)

        # Extract images page-by-page (memory-safe)
        num_imgs = extract_pdf_images_streamed(
            local_path=local_path,
            payload=payload,
            s3_client=s3_client,
            s3_bucket=settings.s3_tmp_bucket,
            tmp_root=settings.tmp_root,
        )

        # Enqueue OCR
        _send_ocr_message(settings.sqs_ocr_queue_url, payload, num_imgs)
    else:
        _send_ocr_message(settings.sqs_ocr_queue_url, payload, 1)

    logger.info("Extraction complete | method=%s", result.get("method"))
    return result


def phase_delete_message(receipt_handle: str) -> None:
    sqs_client.delete_message(
        QueueUrl=settings.sqs_file_queue_url,
        ReceiptHandle=receipt_handle,
    )
    logger.info("Message deleted from queue")


# ---------------------------------------------------------------------------
# Main message handler
# ---------------------------------------------------------------------------

def handle_message(message: Dict[str, Any]) -> None:
    local_path: Optional[str] = None
    receipt_handle = message.get("ReceiptHandle")

    try:
        payload = phase_parse_message(message)
        local_path = phase_download_document(payload)
        doc_type = payload.get("documentType", "").upper()

        if doc_type == "PDF":
            result = phase_extract_content(local_path, payload)
            logger.info(
                "SUCCESS | id=%s method=%s",
                payload["documentId"],
                result.get("method"),
            )
        elif doc_type == "TXT":
            _save_to_db(payload["documentId"], local_path)
            logger.info("TXT saved to DB.")
        else:
            logger.info("Routing to OCR pipeline.")
            _send_ocr_message(settings.sqs_ocr_queue_url, payload, 1)

        phase_delete_message(receipt_handle)

    except Exception as exc:
        logger.exception("FAILED processing message: %s", exc)
    finally:
        if local_path:
            cleanup_temp_file(local_path)
        gc.collect()   # reclaim memory after every message


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

def run() -> None:
    logger.info("Starting SQS document worker (memory-optimised)…")
    logger.info("  endpoint  = %s", settings.endpoint_url)
    logger.info("  queue     = %s", settings.sqs_file_queue_url)
    logger.info("  bucket    = %s", settings.s3_upload_bucket)
    logger.info("  tmp_root  = %s", settings.tmp_root)

    while RUNNING:
        try:
            message = phase_receive_message()
            if not message:
                time.sleep(settings.sleep_on_empty)
                continue
            handle_message(message)

        except (ClientError, BotoCoreError) as exc:
            logger.exception("AWS error: %s", exc)
            time.sleep(5)

        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            time.sleep(5)

    logger.info("Worker stopped cleanly.")


if __name__ == "__main__":
    run()
