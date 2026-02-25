"""
API Gateway — bridges the HTML frontend with LocalStack (S3 + SQS) and the OCR Lambda.

Flow:
  1. POST /api/upload   → Upload file to S3, send SQS message
  2. POST /api/process  → Read SQS message, fetch from S3, invoke Lambda, return OCR text
  3. POST /api/scan     → One-shot: upload → S3 → SQS → Lambda → return result
  4. GET  /api/health   → Health check
  5. GET  /api/queue    → Peek at SQS messages
"""

import base64
import json
import os
import time
import uuid
from datetime import datetime

import boto3
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from botocore.config import Config

app = Flask(__name__)
CORS(app)

# ── Config ──────────────────────────────────────────────────────
LOCALSTACK_URL = os.environ.get("LOCALSTACK_URL", "http://localhost:4566")
LAMBDA_URL = os.environ.get("LAMBDA_URL", "http://ocr-lambda:9000")
S3_BUCKET = os.environ.get("S3_BUCKET", "ocr-uploads")
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


def get_queue_url():
    resp = sqs.get_queue_url(QueueName=SQS_QUEUE)
    return resp["QueueUrl"]


def invoke_lambda(function_name, payload):
    """Call the OCR Lambda service."""
    url = f"{LAMBDA_URL}/2015-03-31/functions/{function_name}/invocations"
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


# ── Health ──────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    """Check health of all services."""
    checks = {}

    # LocalStack
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
        checks["s3"] = "ok"
    except Exception as e:
        checks["s3"] = f"error: {e}"

    try:
        get_queue_url()
        checks["sqs"] = "ok"
    except Exception as e:
        checks["sqs"] = f"error: {e}"

    # Lambda
    try:
        r = requests.get(f"{LAMBDA_URL}/health", timeout=5)
        checks["lambda"] = "ok" if r.status_code == 200 else f"status {r.status_code}"
    except Exception as e:
        checks["lambda"] = f"error: {e}"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return jsonify({"status": status, "checks": checks}), 200


# ── Upload to S3 + send SQS message ────────────────────────────
@app.route("/api/upload", methods=["POST"])
def upload():
    """Upload a file to S3 and enqueue an SQS job."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    filename = file.filename
    file_bytes = file.read()
    file_ext = os.path.splitext(filename)[1].lower()
    job_id = str(uuid.uuid4())
    s3_key = f"uploads/{job_id}/{filename}"

    # Upload to S3
    content_type = file.content_type or "application/octet-stream"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=file_bytes,
        ContentType=content_type,
        Metadata={"job-id": job_id, "original-filename": filename},
    )

    # Determine which Lambda function to invoke
    if file_ext == ".pdf":
        function_name = "pdf-ocr"
    else:
        function_name = "ocr-service"

    # Send SQS message
    queue_url = get_queue_url()
    message_body = json.dumps({
        "job_id": job_id,
        "s3_bucket": S3_BUCKET,
        "s3_key": s3_key,
        "filename": filename,
        "file_type": file_ext,
        "function_name": function_name,
        "content_type": content_type,
        "file_size": len(file_bytes),
        "timestamp": datetime.utcnow().isoformat(),
    })

    sqs.send_message(QueueUrl=queue_url, MessageBody=message_body)

    return jsonify({
        "job_id": job_id,
        "s3_key": s3_key,
        "filename": filename,
        "file_size": len(file_bytes),
        "function_name": function_name,
        "message": "File uploaded to S3 and job queued in SQS",
    }), 200


# ── Process: read SQS → fetch S3 → invoke Lambda ───────────────
@app.route("/api/process", methods=["POST"])
def process():
    """Read one SQS message, fetch file from S3, invoke Lambda OCR, return result."""
    data = request.get_json(silent=True) or {}
    target_job_id = data.get("job_id")

    queue_url = get_queue_url()

    # Poll SQS for matching message
    msg = None
    receipt_handle = None

    for _ in range(3):  # retry a few times
        resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=2,
        )
        messages = resp.get("Messages", [])

        for m in messages:
            body = json.loads(m["Body"])

            # S3 event notification format (from LocalStack auto-notification)
            if "Records" in body:
                # This is the S3 event notification — skip it, we use our custom messages
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"])
                continue

            if target_job_id and body.get("job_id") != target_job_id:
                continue

            msg = body
            receipt_handle = m["ReceiptHandle"]
            break

        if msg:
            break
        time.sleep(0.5)

    if not msg:
        return jsonify({"error": "No matching job found in queue. Try again."}), 404

    # Delete message from queue
    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

    # Fetch file from S3
    s3_key = msg["s3_key"]
    s3_obj = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
    file_bytes = s3_obj["Body"].read()
    file_b64 = base64.b64encode(file_bytes).decode("utf-8")

    # Build Lambda payload
    function_name = msg.get("function_name", "ocr-service")
    filename = msg.get("filename", "unknown")

    if function_name == "pdf-ocr":
        payload = {"pdf": file_b64, "filename": filename, "dpi": 300}
    elif function_name == "pdf-extract":
        payload = {"pdf": file_b64, "filename": filename}
    else:
        payload = {"image": file_b64, "filename": filename}

    # Invoke Lambda
    start = time.time()
    result = invoke_lambda(function_name, payload)
    invoke_ms = round((time.time() - start) * 1000, 2)

    result["job_id"] = msg["job_id"]
    result["s3_key"] = s3_key
    result["lambda_invoke_ms"] = invoke_ms
    result["function_name"] = function_name

    return jsonify(result), 200


# ── One-shot scan: upload + process in a single request ─────────
@app.route("/api/scan", methods=["POST"])
def scan():
    """Upload → S3 → SQS → Lambda → return OCR result in one call."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    pipeline_start = time.time()

    filename = file.filename
    file_bytes = file.read()
    file_ext = os.path.splitext(filename)[1].lower()
    job_id = str(uuid.uuid4())
    s3_key = f"uploads/{job_id}/{filename}"
    content_type = file.content_type or "application/octet-stream"

    # ── Step 1: Upload to S3 ──
    s3_start = time.time()
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=file_bytes,
        ContentType=content_type,
        Metadata={"job-id": job_id, "original-filename": filename},
    )
    s3_ms = round((time.time() - s3_start) * 1000, 2)

    # ── Step 2: Send to SQS ──
    if file_ext == ".pdf":
        function_name = "pdf-ocr"
    else:
        function_name = "ocr-service"

    sqs_start = time.time()
    queue_url = get_queue_url()
    sqs_message = {
        "job_id": job_id,
        "s3_bucket": S3_BUCKET,
        "s3_key": s3_key,
        "filename": filename,
        "function_name": function_name,
        "timestamp": datetime.utcnow().isoformat(),
    }
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(sqs_message))
    sqs_ms = round((time.time() - sqs_start) * 1000, 2)

    # ── Step 3: Read from SQS (consume own message) ──
    consume_start = time.time()
    consumed = False
    for _ in range(5):
        resp = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
        )
        for m in resp.get("Messages", []):
            body = json.loads(m["Body"])
            # Skip S3 auto-notifications
            if "Records" in body:
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"])
                continue
            if body.get("job_id") == job_id:
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"])
                consumed = True
                break
        if consumed:
            break
    consume_ms = round((time.time() - consume_start) * 1000, 2)

    # ── Step 4: Fetch from S3 + invoke Lambda ──
    fetch_start = time.time()
    s3_obj = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
    file_bytes_from_s3 = s3_obj["Body"].read()
    file_b64 = base64.b64encode(file_bytes_from_s3).decode("utf-8")
    fetch_ms = round((time.time() - fetch_start) * 1000, 2)

    if function_name == "pdf-ocr":
        payload = {"pdf": file_b64, "filename": filename, "dpi": 300}
    else:
        payload = {"image": file_b64, "filename": filename}

    lambda_start = time.time()
    result = invoke_lambda(function_name, payload)
    lambda_ms = round((time.time() - lambda_start) * 1000, 2)

    pipeline_ms = round((time.time() - pipeline_start) * 1000, 2)

    result["job_id"] = job_id
    result["s3_key"] = s3_key
    result["function_name"] = function_name
    result["pipeline"] = {
        "total_ms": pipeline_ms,
        "s3_upload_ms": s3_ms,
        "sqs_send_ms": sqs_ms,
        "sqs_consume_ms": consume_ms,
        "s3_fetch_ms": fetch_ms,
        "lambda_invoke_ms": lambda_ms,
    }

    return jsonify(result), 200


# ── Queue inspector ─────────────────────────────────────────────
@app.route("/api/queue", methods=["GET"])
def queue_status():
    """Peek at SQS queue attributes."""
    queue_url = get_queue_url()
    attrs = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]

    return jsonify({
        "queue": SQS_QUEUE,
        "messages_available": int(attrs.get("ApproximateNumberOfMessages", 0)),
        "messages_in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
    }), 200


# ── List S3 uploads ─────────────────────────────────────────────
@app.route("/api/files", methods=["GET"])
def list_files():
    """List files in the S3 bucket."""
    resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="uploads/")
    files = []
    for obj in resp.get("Contents", []):
        files.append({
            "key": obj["Key"],
            "size": obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
        })
    return jsonify({"bucket": S3_BUCKET, "files": files}), 200


if __name__ == "__main__":
    print("=" * 60)
    print("  API Gateway running on :8080")
    print(f"  LocalStack: {LOCALSTACK_URL}")
    print(f"  Lambda:     {LAMBDA_URL}")
    print(f"  S3 Bucket:  {S3_BUCKET}")
    print(f"  SQS Queue:  {SQS_QUEUE}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=8080, debug=True)
