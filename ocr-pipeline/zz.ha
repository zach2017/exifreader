"""
Lambda handler triggered by S3 bucket events.
Extracts the document ID (object key) from the S3 event
and calls an external API service with it.
"""

import json
import os
import urllib.request
import urllib.error
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# API service URL — inside Docker network, use the container name
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api-service:8080")


def handler(event, context):
    """
    S3 event structure:
    {
        "Records": [
            {
                "s3": {
                    "bucket": { "name": "my-bucket" },
                    "object": { "key": "documents/abc123.pdf", "size": 1024 }
                },
                "eventName": "ObjectCreated:Put"
            }
        ]
    }
    """
    logger.info("Received event: %s", json.dumps(event))

    results = []

    for record in event.get("Records", []):
        s3_info = record.get("s3", {})
        bucket_name = s3_info.get("bucket", {}).get("name", "")
        object_key = s3_info.get("object", {}).get("key", "")
        object_size = s3_info.get("object", {}).get("size", 0)
        event_name = record.get("eventName", "")

        # Extract document ID from the object key
        # e.g., "documents/abc123.pdf" -> "abc123.pdf"
        #        or use the full key as the document ID
        document_id = object_key.split("/")[-1] if "/" in object_key else object_key

        logger.info(
            "Processing: bucket=%s, key=%s, document_id=%s, event=%s",
            bucket_name, object_key, document_id, event_name,
        )

        # Call the external API service
        try:
            result = call_api_service(
                document_id=document_id,
                bucket_name=bucket_name,
                object_key=object_key,
                object_size=object_size,
            )
            results.append({
                "document_id": document_id,
                "status": "success",
                "api_response": result,
            })
        except Exception as e:
            logger.error("Failed to call API for document %s: %s", document_id, str(e))
            results.append({
                "document_id": document_id,
                "status": "error",
                "error": str(e),
            })

    response = {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"Processed {len(results)} document(s)",
            "results": results,
        }),
    }

    logger.info("Response: %s", json.dumps(response))
    return response


def call_api_service(document_id: str, bucket_name: str, object_key: str, object_size: int) -> dict:
    """
    Call the external API service with the document information.
    Uses urllib (available in Lambda without extra dependencies).
    """
    url = f"{API_BASE_URL}/api/documents/process"

    payload = json.dumps({
        "document_id": document_id,
        "bucket": bucket_name,
        "key": object_key,
        "size": object_size,
        "source": "s3-lambda-trigger",
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Source": "localstack-lambda",
    }

    logger.info("Calling API: POST %s with document_id=%s", url, document_id)

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_body = resp.read().decode("utf-8")
            logger.info("API response (%d): %s", resp.status, response_body)
            return json.loads(response_body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        logger.error("API HTTP error %d: %s", e.code, error_body)
        raise RuntimeError(f"API returned {e.code}: {error_body}")
    except urllib.error.URLError as e:
        logger.error("API connection error: %s", str(e.reason))
        raise RuntimeError(f"Cannot reach API: {e.reason}")