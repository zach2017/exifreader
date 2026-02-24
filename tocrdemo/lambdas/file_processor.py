"""
Lambda 2: File Processor
=========================
Deployed on LocalStack. Invoked by file-router Lambda.
Pulls the file from S3 and extracts metadata:
  - Images: dimensions (width x height), file size
  - PDFs: page count, PDF version, encryption status, file size
"""

import json
import os
import re
import boto3
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config ───────────────────────────────────────────────────
ENDPOINT = os.environ.get('LOCALSTACK_ENDPOINT', 'http://localhost:4566')
REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')


def _s3():
    """Create S3 client for LocalStack."""
    return boto3.client(
        's3',
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id='test',
        aws_secret_access_key='test',
    )


def format_size(size_bytes):
    """Human-readable file size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


# ── Image Processing ────────────────────────────────────────

def _png_dimensions(data):
    """Extract dimensions from PNG header (bytes 16-24)."""
    if len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n':
        w = int.from_bytes(data[16:20], 'big')
        h = int.from_bytes(data[20:24], 'big')
        return w, h
    return None, None


def _jpeg_dimensions(data):
    """Extract dimensions by scanning for SOF0/SOF2 marker."""
    i = 0
    while i < len(data) - 9:
        if data[i] == 0xFF:
            marker = data[i + 1]
            if marker in (0xC0, 0xC2):  # SOF0 or SOF2
                h = int.from_bytes(data[i+5:i+7], 'big')
                w = int.from_bytes(data[i+7:i+9], 'big')
                return w, h
            elif marker == 0xD9:  # EOI — stop
                break
            elif marker not in (0x00, 0x01) and not (0xD0 <= marker <= 0xD8):
                seg_len = int.from_bytes(data[i+2:i+4], 'big')
                i += seg_len + 2
                continue
        i += 1
    return None, None


def _gif_dimensions(data):
    """Extract dimensions from GIF header (bytes 6-10)."""
    if len(data) >= 10 and data[:3] == b'GIF':
        w = int.from_bytes(data[6:8], 'little')
        h = int.from_bytes(data[8:10], 'little')
        return w, h
    return None, None


def _webp_dimensions(data):
    """Extract dimensions from WebP (VP8 chunk)."""
    if len(data) >= 30 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        if data[12:16] == b'VP8 ' and len(data) >= 30:
            w = int.from_bytes(data[26:28], 'little') & 0x3FFF
            h = int.from_bytes(data[28:30], 'little') & 0x3FFF
            return w, h
    return None, None


def _bmp_dimensions(data):
    """Extract dimensions from BMP header."""
    if len(data) >= 26 and data[:2] == b'BM':
        w = int.from_bytes(data[18:22], 'little')
        h = abs(int.from_bytes(data[22:26], 'little', signed=True))
        return w, h
    return None, None


DIMENSION_PARSERS = {
    '.png': _png_dimensions,
    '.jpg': _jpeg_dimensions,
    '.jpeg': _jpeg_dimensions,
    '.gif': _gif_dimensions,
    '.webp': _webp_dimensions,
    '.bmp': _bmp_dimensions,
}


def process_image(file_bytes, extension):
    """Extract image metadata from raw bytes."""
    result = {
        'processor': 'image_processor',
        'raw_size_bytes': len(file_bytes),
        'formatted_size': format_size(len(file_bytes)),
    }

    parser = DIMENSION_PARSERS.get(extension)
    if parser:
        try:
            w, h = parser(file_bytes)
            if w and h:
                result['width'] = w
                result['height'] = h
                result['dimensions'] = f"{w}x{h}"
                result['megapixels'] = round((w * h) / 1_000_000, 2)
            else:
                result['dimensions'] = 'could not parse'
        except Exception as e:
            logger.warning(f"Dimension parse error: {e}")
            result['dimensions'] = 'error'
    else:
        result['dimensions'] = f'no parser for {extension}'

    return result


# ── PDF Processing ───────────────────────────────────────────

def process_pdf(file_bytes):
    """Extract PDF metadata from raw bytes."""
    result = {
        'processor': 'pdf_processor',
        'raw_size_bytes': len(file_bytes),
        'formatted_size': format_size(len(file_bytes)),
    }

    content = file_bytes.decode('latin-1', errors='ignore')

    # Page count — method 1: /Type /Page minus /Type /Pages
    page_count = content.count('/Type /Page') - content.count('/Type /Pages')
    if page_count <= 0:
        # Method 2: /Count N in the page tree
        match = re.search(r'/Count\s+(\d+)', content)
        page_count = int(match.group(1)) if match else -1
    result['page_count'] = max(page_count, 0)

    # PDF version
    if content.startswith('%PDF-'):
        result['pdf_version'] = content[5:8]

    # Encryption
    result['encrypted'] = '/Encrypt' in content

    # Title (if present)
    title_match = re.search(r'/Title\s*\(([^)]*)\)', content)
    if title_match:
        result['title'] = title_match.group(1)

    # Author
    author_match = re.search(r'/Author\s*\(([^)]*)\)', content)
    if author_match:
        result['author'] = author_match.group(1)

    return result


# ── Main Handler ─────────────────────────────────────────────

def handler(event, context):
    """
    Invoked by file-router Lambda.

    Expected payload:
    {
        "bucket": "file-uploads",
        "key": "uploads/photo.png",
        "size": 12345,
        "file_type": "image",
        "extension": ".png",
        "source_lambda": "file-router"
    }
    """
    logger.info("========== FILE PROCESSOR START ==========")
    logger.info(f"Event: {json.dumps(event, default=str)}")

    bucket = event.get('bucket', '')
    key = event.get('key', '')
    file_type = event.get('file_type', 'unknown')
    extension = event.get('extension', '')
    source = event.get('source_lambda', 'unknown')

    if not bucket or not key:
        logger.error("Missing bucket or key in event")
        return {
            'status': 'error',
            'error': 'Missing bucket or key',
        }

    s3 = _s3()

    try:
        # ── Download file from S3 ────────────────────────────
        logger.info(f"Downloading s3://{bucket}/{key}")
        response = s3.get_object(Bucket=bucket, Key=key)
        file_bytes = response['Body'].read()
        content_type = response.get('ContentType', 'application/octet-stream')
        last_modified = response.get('LastModified', None)

        logger.info(f"Downloaded {len(file_bytes)} bytes | ContentType={content_type}")

        # ── Process based on type ────────────────────────────
        if file_type == 'image':
            processing_result = process_image(file_bytes, extension)
        elif file_type == 'pdf':
            processing_result = process_pdf(file_bytes)
        else:
            processing_result = {
                'processor': 'generic',
                'raw_size_bytes': len(file_bytes),
                'formatted_size': format_size(len(file_bytes)),
            }

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
            'processing_result': processing_result,
            'pipeline': {
                'invoked_by': source,
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'processor_function': 'file-processor',
            },
        }

        logger.info(f"========== FILE PROCESSOR END ==========")
        logger.info(f"Result: {json.dumps(result, default=str)}")
        return result

    except s3.exceptions.NoSuchKey:
        logger.error(f"File not found: s3://{bucket}/{key}")
        return {
            'status': 'error',
            'error': f"File not found: s3://{bucket}/{key}",
            'bucket': bucket,
            'key': key,
        }
    except Exception as e:
        logger.error(f"Processing error: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'bucket': bucket,
            'key': key,
        }
