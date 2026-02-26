"""
Lambda function triggered by S3 upload event.
Extracts the doc_id from the S3 key and calls the OCR API server.
"""

import json
import os
import urllib.request
import urllib.error
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api-server:8000")


def handler(event, context):
    """Handle S3 event notification – trigger OCR processing."""
    logger.info(f"Received event: {json.dumps(event)}")

    results = []

    for record in event.get("Records", []):
        s3_key = record["s3"]["object"]["key"]
        bucket = record["s3"]["bucket"]["name"]
        logger.info(f"Processing s3://{bucket}/{s3_key}")

        # Extract doc_id from key pattern: uploads/{doc_id}/filename
        parts = s3_key.split("/")
        if len(parts) < 3 or parts[0] != "uploads":
            logger.warning(f"Skipping unexpected key pattern: {s3_key}")
            results.append({"s3_key": s3_key, "status": "skipped", "reason": f"Key pattern not matched: {s3_key}"})
            continue

        doc_id = parts[1]
        logger.info(f"Extracted doc_id={doc_id}, calling OCR API")

        # Call OCR API server
        try:
            payload = json.dumps({"doc_id": doc_id}).encode("utf-8")
            req = urllib.request.Request(
                f"{API_BASE_URL}/ocr/process",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                logger.info(f"OCR API response: {body}")
                results.append({"doc_id": doc_id, "status": "success", "response": body})

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else str(e)
            logger.error(f"OCR API HTTP error for {doc_id}: {e.code} – {error_body}")
            results.append({
                "doc_id": doc_id,
                "status": "error",
                "http_code": e.code,
                "error": error_body,
            })

        except Exception as e:
            logger.error(f"OCR API call failed for {doc_id}: {e}")
            results.append({"doc_id": doc_id, "status": "error", "error": str(e)})

    return {
        "statusCode": 200,
        "body": json.dumps({"processed": len(results), "results": results}),
    }
