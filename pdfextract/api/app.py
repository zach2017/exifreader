"""
PDF Image Extractor API
───────────────────────
Accepts PDF uploads, converts each page to a PNG image using PyMuPDF,
stores images in S3 (LocalStack), and publishes an SQS message per page.
"""

import io
import os
import json
import uuid
import logging
from datetime import datetime, timezone

import boto3
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS

# ─── Config ───────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

S3_ENDPOINT   = os.environ.get("S3_ENDPOINT", "http://localhost:4566")
SQS_ENDPOINT  = os.environ.get("SQS_ENDPOINT", "http://localhost:4566")
S3_BUCKET     = os.environ.get("S3_BUCKET", "pdf-images")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL",
    "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/pdf-processing")
AWS_REGION    = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
DPI           = int(os.environ.get("RENDER_DPI", "200"))

# ─── AWS Clients ──────────────────────────────────────────────────────────────
s3_client = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    region_name=AWS_REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

sqs_client = boto3.client(
    "sqs",
    endpoint_url=SQS_ENDPOINT,
    region_name=AWS_REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def render_page_to_png(page: fitz.Page, dpi: int = 200) -> bytes:
    """Render a single PDF page to PNG bytes at the given DPI."""
    zoom = dpi / 72  # 72 is the PDF default DPI
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    return pixmap.tobytes(output="png")


def upload_to_s3(image_bytes: bytes, s3_key: str) -> str:
    """Upload PNG bytes to S3 and return the full S3 URI."""
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=image_bytes,
        ContentType="image/png",
    )
    s3_uri = f"s3://{S3_BUCKET}/{s3_key}"
    logger.info(f"  ✓ Uploaded → {s3_uri}")
    return s3_uri


def send_sqs_message(document_name: str, page_number: int, s3_key: str, s3_uri: str):
    """Send a processing message to the SQS queue."""
    message = {
        "document_name": document_name,
        "page_number": page_number,
        "total_pages": None,  # filled in by caller
        "s3_bucket": S3_BUCKET,
        "s3_key": s3_key,
        "s3_uri": s3_uri,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dpi": DPI,
    }
    return message  # We batch-send after setting total_pages


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({"status": "healthy", "service": "pdf-image-extractor"})


@app.route("/api/upload", methods=["POST"])
def upload_pdf():
    """
    Upload a PDF file.
    - Converts each page to a PNG image
    - Uploads each image to S3
    - Sends an SQS message per page
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided. Use 'file' form field."}), 400

    file = request.files["file"]

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted."}), 400

    # Read PDF into memory
    pdf_bytes = file.read()
    original_name = file.filename
    doc_id = uuid.uuid4().hex[:12]
    base_name = os.path.splitext(original_name)[0]

    logger.info(f"━━━ Processing: {original_name} (id={doc_id}) ━━━")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"Failed to open PDF: {e}")
        return jsonify({"error": f"Invalid PDF file: {str(e)}"}), 400

    total_pages = len(doc)
    logger.info(f"  Pages: {total_pages}")

    results = []

    for page_num in range(total_pages):
        page = doc[page_num]
        page_display = page_num + 1  # 1-indexed for humans

        # 1) Render page → PNG
        logger.info(f"  Rendering page {page_display}/{total_pages} @ {DPI} DPI...")
        png_bytes = render_page_to_png(page, dpi=DPI)

        # 2) Upload to S3
        s3_key = f"documents/{doc_id}/{base_name}/page_{page_display:04d}.png"
        s3_uri = upload_to_s3(png_bytes, s3_key)

        # 3) Build SQS message
        sqs_message = {
            "document_id": doc_id,
            "document_name": original_name,
            "page_number": page_display,
            "total_pages": total_pages,
            "s3_bucket": S3_BUCKET,
            "s3_key": s3_key,
            "s3_uri": s3_uri,
            "image_size_bytes": len(png_bytes),
            "dpi": DPI,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 4) Send to SQS
        sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(sqs_message),
            MessageAttributes={
                "DocumentId": {"DataType": "String", "StringValue": doc_id},
                "PageNumber": {"DataType": "Number", "StringValue": str(page_display)},
            },
        )
        logger.info(f"  ✓ SQS message sent for page {page_display}")

        results.append({
            "page": page_display,
            "s3_key": s3_key,
            "s3_uri": s3_uri,
            "image_size_bytes": len(png_bytes),
        })

    doc.close()

    logger.info(f"━━━ Complete: {total_pages} pages processed ━━━\n")

    return jsonify({
        "status": "success",
        "document_id": doc_id,
        "document_name": original_name,
        "total_pages": total_pages,
        "dpi": DPI,
        "pages": results,
    })


@app.route("/api/queue/stats", methods=["GET"])
def queue_stats():
    """Get SQS queue statistics."""
    try:
        resp = sqs_client.get_queue_attributes(
            QueueUrl=SQS_QUEUE_URL,
            AttributeNames=["All"],
        )
        attrs = resp.get("Attributes", {})
        return jsonify({
            "queue_url": SQS_QUEUE_URL,
            "messages_available": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "messages_in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
            "messages_delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/queue/messages", methods=["GET"])
def peek_messages():
    """Peek at messages in the SQS queue (non-destructive read with short visibility)."""
    max_messages = min(int(request.args.get("max", 10)), 10)
    try:
        resp = sqs_client.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=max_messages,
            VisibilityTimeout=1,  # short so they reappear quickly
            MessageAttributeNames=["All"],
            WaitTimeSeconds=1,
        )
        messages = []
        for msg in resp.get("Messages", []):
            messages.append({
                "message_id": msg["MessageId"],
                "body": json.loads(msg["Body"]),
                "attributes": {
                    k: v["StringValue"]
                    for k, v in msg.get("MessageAttributes", {}).items()
                },
            })
        return jsonify({"messages": messages, "count": len(messages)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/s3/list", methods=["GET"])
def list_s3_objects():
    """List objects in the S3 bucket."""
    prefix = request.args.get("prefix", "documents/")
    try:
        resp = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix, MaxKeys=100)
        objects = []
        for obj in resp.get("Contents", []):
            objects.append({
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            })
        return jsonify({"bucket": S3_BUCKET, "objects": objects, "count": len(objects)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/s3/image/<path:s3_key>", methods=["GET"])
def get_s3_image(s3_key):
    """Proxy an image from S3 for browser preview."""
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        image_bytes = resp["Body"].read()
        from flask import Response
        return Response(image_bytes, mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 404


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
