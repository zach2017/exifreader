"""
Lambda 2: File Processor
=========================
Invoked by Lambda 1 (file-router). Pulls the file from S3 and extracts
metadata: file size, content type, dimensions (for images), page count (for PDFs).

This Lambda receives the S3 bucket/key from the invoking Lambda's payload,
downloads the file, and returns processed metadata.
"""

import json
import os
import io
import boto3
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

LOCALSTACK_ENDPOINT = os.environ.get('LOCALSTACK_ENDPOINT', 'http://host.docker.internal:4566')


def get_s3_client():
    """Create an S3 client pointing to LocalStack."""
    return boto3.client(
        's3',
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )


def format_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def process_image(file_bytes: bytes, extension: str) -> dict:
    """
    Extract image metadata.
    Uses basic byte-level parsing (no PIL dependency needed).
    """
    metadata = {
        'processor': 'image_processor',
        'raw_size_bytes': len(file_bytes),
        'formatted_size': format_size(len(file_bytes)),
    }

    # ── Try to detect image dimensions from headers ──────────
    try:
        if extension in ('.png',):
            # PNG: width at bytes 16-20, height at bytes 20-24 (big-endian)
            if len(file_bytes) >= 24 and file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                width = int.from_bytes(file_bytes[16:20], 'big')
                height = int.from_bytes(file_bytes[20:24], 'big')
                metadata['width'] = width
                metadata['height'] = height
                metadata['dimensions'] = f"{width}x{height}"

        elif extension in ('.jpg', '.jpeg'):
            # JPEG: search for SOF0 marker (0xFFC0)
            i = 0
            while i < len(file_bytes) - 9:
                if file_bytes[i] == 0xFF:
                    marker = file_bytes[i + 1]
                    if marker == 0xC0 or marker == 0xC2:  # SOF0 or SOF2
                        height = int.from_bytes(file_bytes[i+5:i+7], 'big')
                        width = int.from_bytes(file_bytes[i+7:i+9], 'big')
                        metadata['width'] = width
                        metadata['height'] = height
                        metadata['dimensions'] = f"{width}x{height}"
                        break
                    elif marker == 0xD9:  # EOI
                        break
                    elif marker not in (0x00, 0x01, 0xD0, 0xD1, 0xD2, 0xD3,
                                        0xD4, 0xD5, 0xD6, 0xD7, 0xD8):
                        seg_len = int.from_bytes(file_bytes[i+2:i+4], 'big')
                        i += seg_len + 2
                        continue
                i += 1

        elif extension == '.gif':
            # GIF: width at bytes 6-8, height at bytes 8-10 (little-endian)
            if len(file_bytes) >= 10 and file_bytes[:3] in (b'GIF',):
                width = int.from_bytes(file_bytes[6:8], 'little')
                height = int.from_bytes(file_bytes[8:10], 'little')
                metadata['width'] = width
                metadata['height'] = height
                metadata['dimensions'] = f"{width}x{height}"

    except Exception as e:
        logger.warning(f"Could not extract dimensions: {e}")
        metadata['dimensions'] = 'unknown'

    return metadata


def process_pdf(file_bytes: bytes) -> dict:
    """
    Extract PDF metadata using basic byte-level parsing.
    """
    metadata = {
        'processor': 'pdf_processor',
        'raw_size_bytes': len(file_bytes),
        'formatted_size': format_size(len(file_bytes)),
    }

    content = file_bytes.decode('latin-1', errors='ignore')

    # ── Count pages (approximate) ────────────────────────────
    # Method 1: Count /Type /Page entries (not /Pages)
    page_count = content.count('/Type /Page') - content.count('/Type /Pages')
    if page_count <= 0:
        # Method 2: Look for /Count in the page tree
        import re
        count_match = re.search(r'/Count\s+(\d+)', content)
        page_count = int(count_match.group(1)) if count_match else -1

    metadata['page_count'] = page_count

    # ── Extract PDF version ──────────────────────────────────
    if content.startswith('%PDF-'):
        metadata['pdf_version'] = content[5:8]

    # ── Check for encryption ─────────────────────────────────
    metadata['encrypted'] = '/Encrypt' in content

    return metadata


def handler(event, context):
    """
    Main handler - invoked by file-router Lambda.

    Expected event payload (from Lambda 1):
    {
        "bucket": "file-uploads",
        "key": "photo.png",
        "size": 12345,
        "file_type": "image",
        "extension": ".png",
        "source_lambda": "file-router"
    }
    """
    logger.info(f"🔧 File Processor Lambda invoked with: {json.dumps(event)}")

    bucket = event['bucket']
    key = event['key']
    file_type = event['file_type']
    extension = event.get('extension', '')
    source_lambda = event.get('source_lambda', 'unknown')

    s3_client = get_s3_client()

    try:
        # ── Pull file from S3 ────────────────────────────────
        logger.info(f"⬇️  Downloading s3://{bucket}/{key}")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        file_bytes = response['Body'].read()
        content_type = response.get('ContentType', 'unknown')
        last_modified = response.get('LastModified', None)

        logger.info(f"📦 Downloaded {len(file_bytes)} bytes, ContentType={content_type}")

        # ── Process based on file type ───────────────────────
        if file_type == 'image':
            file_metadata = process_image(file_bytes, extension)
        elif file_type == 'pdf':
            file_metadata = process_pdf(file_bytes)
        else:
            file_metadata = {'processor': 'generic', 'raw_size_bytes': len(file_bytes)}

        # ── Build the result ─────────────────────────────────
        result = {
            'status': 'success',
            'file_info': {
                'bucket': bucket,
                'key': key,
                'file_type': file_type,
                'extension': extension,
                'content_type': content_type,
                'last_modified': str(last_modified) if last_modified else None,
                's3_uri': f"s3://{bucket}/{key}",
            },
            'processing_result': file_metadata,
            'invoked_by': source_lambda,
            'processed_at': datetime.utcnow().isoformat() + 'Z',
        }

        logger.info(f"✅ Processing complete: {json.dumps(result)}")
        return result

    except Exception as e:
        logger.error(f"❌ Error processing file: {str(e)}")
        return {
            'status': 'error',
            'error': str(e),
            'bucket': bucket,
            'key': key,
        }
