"""
OCR Lambda Handler — Event-driven, triggered by S3 → SQS → Lambda.

This function is NOT a running service. LocalStack starts the container
only when a file is uploaded to S3 and the SQS event source mapping fires.

Flow:
  1. Receive SQS event containing S3 notification
  2. Download the uploaded file from S3
  3. Run Tesseract OCR (images) or PyMuPDF → Tesseract (PDFs)
  4. Write the extracted text as JSON to the results S3 bucket
"""

import base64
import json
import os
import subprocess
import tempfile
import time
import traceback
import urllib.parse

import boto3
import fitz  # PyMuPDF
from botocore.config import Config


# ── AWS clients (endpoint comes from env vars set by docker-compose) ──
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localstack:4566")
RESULT_BUCKET = os.environ.get("RESULT_BUCKET", "ocr-results")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    config=Config(region_name=REGION),
)


def handler(event, context):
    """
    Main Lambda entry point. Receives SQS event wrapping S3 notifications.
    """
    print(f"[Lambda] Invoked with event: {json.dumps(event)[:500]}")

    results = []

    for record in event.get("Records", []):
        try:
            result = process_record(record)
            results.append(result)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[Lambda] ERROR processing record: {e}\n{tb}")
            results.append({"error": str(e), "traceback": tb})

    # If single record, return it directly
    if len(results) == 1:
        return results[0]
    return {"results": results}


def process_record(record):
    """Process a single SQS record containing an S3 event."""

    # ── Parse the S3 event from the SQS message body ──
    body = record.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    s3_records = body.get("Records", [])
    if not s3_records:
        # Maybe this is a direct S3 event (not wrapped in SQS)
        if "s3" in body:
            s3_records = [body]
        else:
            return {"error": "No S3 records found in event", "raw_body": str(body)[:200]}

    s3_event = s3_records[0]
    bucket = s3_event["s3"]["bucket"]["name"]
    raw_key = s3_event["s3"]["object"]["key"]
    key = urllib.parse.unquote_plus(raw_key)

    print(f"[Lambda] Processing s3://{bucket}/{key}")

    # ── Download file from S3 ──
    download_start = time.time()
    obj = s3.get_object(Bucket=bucket, Key=key)
    file_bytes = obj["Body"].read()
    download_ms = round((time.time() - download_start) * 1000, 2)

    filename = key.split("/")[-1]
    file_ext = os.path.splitext(filename)[1].lower()
    file_size = len(file_bytes)

    print(f"[Lambda] Downloaded {filename} ({file_size} bytes) in {download_ms}ms")

    # ── Run OCR based on file type ──
    ocr_start = time.time()

    if file_ext == ".pdf":
        result = ocr_pdf(file_bytes, filename)
    else:
        result = ocr_image(file_bytes, filename)

    ocr_ms = round((time.time() - ocr_start) * 1000, 2)

    # ── Build final result ──
    result["s3_source"] = f"s3://{bucket}/{key}"
    result["download_ms"] = download_ms
    result["total_ocr_ms"] = ocr_ms
    result["file_size_bytes"] = file_size
    result["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ── Write result to S3 results bucket ──
    # Key pattern: results/{job_path}/result.json
    # where job_path mirrors the upload path
    result_key = key.replace("uploads/", "results/", 1) + ".result.json"

    upload_start = time.time()
    s3.put_object(
        Bucket=RESULT_BUCKET,
        Key=result_key,
        Body=json.dumps(result, indent=2),
        ContentType="application/json",
    )
    upload_ms = round((time.time() - upload_start) * 1000, 2)

    result["result_key"] = result_key
    result["result_upload_ms"] = upload_ms

    print(f"[Lambda] Result written to s3://{RESULT_BUCKET}/{result_key} in {upload_ms}ms")

    return result


# ── Image OCR (Tesseract) ──────────────────────────────────────

def ocr_image(image_bytes, filename):
    """Run Tesseract OCR on an image file."""
    suffix = os.path.splitext(filename)[1] or ".png"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        start = time.time()
        result = subprocess.run(
            ["tesseract", tmp_path, "stdout", "--oem", "1", "--psm", "3"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        elapsed_ms = round((time.time() - start) * 1000, 2)

        text = result.stdout.strip()

        if result.returncode != 0 and not text:
            return {
                "error": f"Tesseract failed: {result.stderr.strip()}",
                "filename": filename,
                "processing_time_ms": elapsed_ms,
            }

        return {
            "text": text,
            "filename": filename,
            "word_count": len(text.split()) if text else 0,
            "char_count": len(text),
            "processing_time_ms": elapsed_ms,
            "engine": "tesseract",
        }
    finally:
        os.unlink(tmp_path)


# ── PDF OCR (PyMuPDF → Tesseract) ──────────────────────────────

def ocr_pdf(pdf_bytes, filename, dpi=300):
    """Render each PDF page as an image, then OCR with Tesseract."""

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        pdf_path = tmp.name

    try:
        doc = fitz.open(pdf_path)
        page_count = len(doc)

        pages = []
        full_text_parts = []
        total_words = 0
        total_chars = 0
        total_extract_ms = 0
        total_ocr_ms = 0

        for i, page in enumerate(doc):
            page_start = time.time()

            # Render page to image
            extract_start = time.time()
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            png_bytes = pix.tobytes("png")
            extract_ms = round((time.time() - extract_start) * 1000, 2)
            total_extract_ms += extract_ms

            # Write image for Tesseract
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_tmp:
                img_tmp.write(png_bytes)
                img_path = img_tmp.name

            # OCR the page image
            tesseract_start = time.time()
            result = subprocess.run(
                ["tesseract", img_path, "stdout", "--oem", "1", "--psm", "3"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            ocr_ms = round((time.time() - tesseract_start) * 1000, 2)
            total_ocr_ms += ocr_ms

            os.unlink(img_path)

            text = result.stdout.strip()
            word_count = len(text.split()) if text else 0
            char_count = len(text)
            total_words += word_count
            total_chars += char_count
            full_text_parts.append(text)

            page_ms = round((time.time() - page_start) * 1000, 2)

            pages.append({
                "page": i + 1,
                "text": text,
                "word_count": word_count,
                "char_count": char_count,
                "image_extract_ms": extract_ms,
                "ocr_ms": ocr_ms,
                "page_total_ms": page_ms,
                "image_size_bytes": len(png_bytes),
            })

        doc.close()

        full_text = "\n\n".join(full_text_parts)

        return {
            "text": full_text,
            "filename": filename,
            "page_count": page_count,
            "word_count": total_words,
            "char_count": total_chars,
            "pages": pages,
            "timing": {
                "total_image_extract_ms": round(total_extract_ms, 2),
                "total_ocr_ms": round(total_ocr_ms, 2),
                "avg_extract_per_page_ms": round(total_extract_ms / max(page_count, 1), 2),
                "avg_ocr_per_page_ms": round(total_ocr_ms / max(page_count, 1), 2),
            },
            "dpi": dpi,
            "engine": "pymupdf+tesseract",
        }
    finally:
        os.unlink(pdf_path)
