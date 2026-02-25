"""
API Gateway — bridges the HTML frontend with LocalStack services.

The gateway does NOT invoke Lambda directly. Instead:
  1. Uploads the file to S3  (which triggers S3 → SQS → Lambda automatically)
  2. Polls the S3 results bucket until Lambda writes the OCR result
  3. Returns the result to the frontend

Endpoints:
  POST /api/scan      → Upload to S3, poll for result, return OCR text
  POST /api/upload    → Upload to S3 only (async — Lambda runs in background)
  GET  /api/result    → Check/poll for a specific job result
  GET  /api/health    → Health check
  GET  /api/queue     → SQS queue depth
  GET  /api/files     → List S3 uploads
"""

import json
import os
import time
import uuid

import boto3
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from botocore.config import Config
from botocore.exceptions import ClientError

app = Flask(__name__)
CORS(app)

# ── Config ──────────────────────────────────────────────────────
LOCALSTACK_URL = os.environ.get("LOCALSTACK_URL", "http://localstack:4566")
UPLOAD_BUCKET = os.environ.get("UPLOAD_BUCKET", "ocr-uploads")
RESULT_BUCKET = os.environ.get("RESULT_BUCKET", "ocr-results")
SQS_QUEUE = os.environ.get("SQS_QUEUE", "ocr-jobs")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

boto_config = Config(region_name=REGION)

s3 = boto3.client(
    "s3",
    endpoint_url=LOCALSTACK_URL,
    aws_access_key_id="test",
    aws_secret_access_key="test",
    config=boto_config,
)

sqs = boto3.client(
    "sqs",
    endpoint_url=LOCALSTACK_URL,
    aws_access_key_id="test",
    aws_secret_access_key="test",
    config=boto_config,
)

lam = boto3.client(
    "lambda",
    endpoint_url=LOCALSTACK_URL,
    aws_access_key_id="test",
    aws_secret_access_key="test",
    config=boto_config,
)


def get_queue_url():
    return sqs.get_queue_url(QueueName=SQS_QUEUE)["QueueUrl"]


# ── Health ──────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    checks = {}

    try:
        s3.head_bucket(Bucket=UPLOAD_BUCKET)
        checks["s3_uploads"] = "ok"
    except Exception as e:
        checks["s3_uploads"] = f"error: {e}"

    try:
        s3.head_bucket(Bucket=RESULT_BUCKET)
        checks["s3_results"] = "ok"
    except Exception as e:
        checks["s3_results"] = f"error: {e}"

    try:
        get_queue_url()
        checks["sqs"] = "ok"
    except Exception as e:
        checks["sqs"] = f"error: {e}"

    try:
        resp = lam.get_function(FunctionName="ocr-processor")
        state = resp["Configuration"]["State"]
        checks["lambda"] = f"ok ({state})"
    except Exception as e:
        checks["lambda"] = f"error: {e}"

    status = "ok" if all("ok" in v for v in checks.values()) else "degraded"
    return jsonify({"status": status, "checks": checks}), 200


# ── Upload file to S3 (triggers Lambda automatically) ──────────
@app.route("/api/upload", methods=["POST"])
def upload():
    """Upload to S3. Lambda is triggered automatically via S3 → SQS → Lambda."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    filename = file.filename
    file_bytes = file.read()
    job_id = str(uuid.uuid4())
    s3_key = f"uploads/{job_id}/{filename}"
    content_type = file.content_type or "application/octet-stream"

    # Upload to S3 — this triggers the entire pipeline automatically
    s3.put_object(
        Bucket=UPLOAD_BUCKET,
        Key=s3_key,
        Body=file_bytes,
        ContentType=content_type,
        Metadata={"job-id": job_id, "original-filename": filename},
    )

    # The result will appear at this key once Lambda finishes
    result_key = s3_key.replace("uploads/", "results/", 1) + ".result.json"

    return jsonify({
        "job_id": job_id,
        "s3_key": s3_key,
        "result_key": result_key,
        "filename": filename,
        "file_size": len(file_bytes),
        "message": "File uploaded to S3. Lambda will process it automatically via S3 → SQS → Lambda.",
    }), 200


# ── Poll for result ─────────────────────────────────────────────
@app.route("/api/result", methods=["GET"])
def get_result():
    """Check if Lambda has written the OCR result to S3."""
    result_key = request.args.get("key")
    if not result_key:
        return jsonify({"error": "Missing 'key' query parameter"}), 400

    try:
        obj = s3.get_object(Bucket=RESULT_BUCKET, Key=result_key)
        data = json.loads(obj["Body"].read().decode("utf-8"))
        return jsonify({"status": "complete", "result": data}), 200
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return jsonify({"status": "pending"}), 202
        raise


# ── One-shot scan: upload + poll until result ───────────────────
@app.route("/api/scan", methods=["POST"])
def scan():
    """
    Upload file to S3, then poll S3 results bucket until Lambda finishes.
    The Lambda is triggered automatically by: S3 upload → SQS → Lambda.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    pipeline_start = time.time()

    filename = file.filename
    file_bytes = file.read()
    job_id = str(uuid.uuid4())
    s3_key = f"uploads/{job_id}/{filename}"
    content_type = file.content_type or "application/octet-stream"

    # ── Step 1: Upload to S3 ──
    s3_upload_start = time.time()
    s3.put_object(
        Bucket=UPLOAD_BUCKET,
        Key=s3_key,
        Body=file_bytes,
        ContentType=content_type,
        Metadata={"job-id": job_id, "original-filename": filename},
    )
    s3_upload_ms = round((time.time() - s3_upload_start) * 1000, 2)
    print(f"[Gateway] Uploaded s3://{UPLOAD_BUCKET}/{s3_key} in {s3_upload_ms}ms")

    # ── Step 2: Poll for result (Lambda is triggered automatically) ──
    result_key = s3_key.replace("uploads/", "results/", 1) + ".result.json"

    print(f"[Gateway] Waiting for result at s3://{RESULT_BUCKET}/{result_key}")

    poll_start = time.time()
    result_data = None
    max_wait = 90  # seconds
    poll_interval = 1.0  # seconds

    while (time.time() - poll_start) < max_wait:
        try:
            obj = s3.get_object(Bucket=RESULT_BUCKET, Key=result_key)
            result_data = json.loads(obj["Body"].read().decode("utf-8"))
            break
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                time.sleep(poll_interval)
                # Increase interval slightly to reduce polling pressure
                poll_interval = min(poll_interval * 1.1, 3.0)
                continue
            raise

    poll_ms = round((time.time() - poll_start) * 1000, 2)
    pipeline_ms = round((time.time() - pipeline_start) * 1000, 2)

    if result_data is None:
        return jsonify({
            "error": "Timed out waiting for Lambda to process the file. "
                     "Check docker compose logs for the localstack and lambda containers.",
            "job_id": job_id,
            "s3_key": s3_key,
            "result_key": result_key,
            "pipeline": {
                "total_ms": pipeline_ms,
                "s3_upload_ms": s3_upload_ms,
                "poll_ms": poll_ms,
            },
        }), 504

    # ── Merge pipeline timing into result ──
    result_data["job_id"] = job_id
    result_data["s3_key"] = s3_key
    result_data["pipeline"] = {
        "total_ms": pipeline_ms,
        "s3_upload_ms": s3_upload_ms,
        "lambda_cold_start_and_process_ms": poll_ms,
    }

    # Include Lambda-internal timing if available
    if "download_ms" in result_data:
        result_data["pipeline"]["lambda_s3_download_ms"] = result_data["download_ms"]
    if "total_ocr_ms" in result_data:
        result_data["pipeline"]["lambda_ocr_ms"] = result_data["total_ocr_ms"]
    if "result_upload_ms" in result_data:
        result_data["pipeline"]["lambda_result_upload_ms"] = result_data["result_upload_ms"]

    print(f"[Gateway] Pipeline complete in {pipeline_ms}ms")

    return jsonify(result_data), 200


# ── Queue inspector ─────────────────────────────────────────────
@app.route("/api/queue", methods=["GET"])
def queue_status():
    queue_url = get_queue_url()
    attrs = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        ],
    )["Attributes"]

    return jsonify({
        "queue": SQS_QUEUE,
        "messages_available": int(attrs.get("ApproximateNumberOfMessages", 0)),
        "messages_in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
    }), 200


# ── List S3 uploads ─────────────────────────────────────────────
@app.route("/api/files", methods=["GET"])
def list_files():
    resp = s3.list_objects_v2(Bucket=UPLOAD_BUCKET, Prefix="uploads/")
    files = []
    for obj in resp.get("Contents", []):
        files.append({
            "key": obj["Key"],
            "size": obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
        })
    return jsonify({"bucket": UPLOAD_BUCKET, "files": files}), 200


# ── Lambda status (for dashboard) ──────────────────────────────
@app.route("/api/lambda-status", methods=["GET"])
def lambda_status():
    try:
        resp = lam.get_function(FunctionName="ocr-processor")
        config = resp["Configuration"]
        return jsonify({
            "function_name": config["FunctionName"],
            "state": config.get("State", "Unknown"),
            "runtime": config.get("PackageType", "Unknown"),
            "memory_mb": config.get("MemorySize", 0),
            "timeout_s": config.get("Timeout", 0),
            "last_modified": config.get("LastModified", ""),
            "code_size": config.get("CodeSize", 0),
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("=" * 60)
    print("  API Gateway running on :8080")
    print(f"  LocalStack:    {LOCALSTACK_URL}")
    print(f"  Upload bucket: {UPLOAD_BUCKET}")
    print(f"  Result bucket: {RESULT_BUCKET}")
    print(f"  SQS queue:     {SQS_QUEUE}")
    print("")
    print("  Lambda is NOT running — it starts on S3 upload.")
    print("  Flow: S3 upload → SQS → Lambda → S3 result")
    print("=" * 60)
    app.run(host="0.0.0.0", port=8080, debug=True)
