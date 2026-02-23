# AWS Lambda OCR Handler — Deep Dive, S3 Integration, LocalStack & Step Functions

---

## Table of Contents

1. [Line-by-Line Code Explanation](#1-line-by-line-code-explanation)
2. [How the Lambda Accepts Input](#2-how-the-lambda-accepts-input)
3. [Modified Handler with S3 Support](#3-modified-handler-with-s3-support)
4. [LocalStack Docker Compose Setup](#4-localstack-docker-compose-setup)
5. [Step Function — Filter by Document Type](#5-step-function--filter-by-document-type)
6. [Official References & Links](#6-official-references--links)

---

## 1. Line-by-Line Code Explanation

### 1.1 — Imports

```python
import json          # Serialize/deserialize JSON payloads (stdlib)
import base64        # Encode/decode Base64 binary data (stdlib)
import time          # Measure elapsed wall-clock time (stdlib)
import subprocess    # Spawn external processes — here, Tesseract CLI (stdlib)
import tempfile      # Create secure temporary files in /tmp (stdlib)
import os            # File path manipulation, file deletion (stdlib)
```

**Why these matter in Lambda:**

| Module | Lambda Relevance |
|--------|-----------------|
| `json` | Every Lambda event and response is JSON. API Gateway proxy events arrive as JSON strings inside the `body` field. |
| `base64` | API Gateway automatically Base64-encodes binary payloads (images, PDFs). You must decode them before processing. |
| `time` | Lambda bills in 1 ms increments. Tracking processing time helps you optimize cost and set appropriate timeouts. |
| `subprocess` | Tesseract is a C++ binary. Lambda supports custom binaries via Layers or container images. `subprocess.run` shells out to it. |
| `tempfile` | Lambda provides a writable `/tmp` directory (up to 10 GB configurable). Temp files let you bridge between in-memory data and CLI tools that expect file paths. |
| `os` | `os.unlink()` deletes temp files. Critical in Lambda because `/tmp` persists across warm invocations — without cleanup you risk filling the disk. |

> **Ref:** [Python Standard Library](https://docs.python.org/3/library/) · [Lambda /tmp storage](https://docs.aws.amazon.com/lambda/latest/dg/configuration-ephemeral-storage.html)

---

### 1.2 — Function Signature

```python
def lambda_handler(event, context):
    """OCR Lambda handler - extracts text from uploaded images."""
```

- **`event`** — A Python `dict` containing the input payload. Its structure depends on
  the invocation source (API Gateway, S3 trigger, Step Functions, direct `Invoke`, etc.).
- **`context`** — A `LambdaContext` object with runtime metadata:
  - `context.function_name` — the function's name
  - `context.memory_limit_in_mb` — allocated memory
  - `context.get_remaining_time_in_millis()` — time left before timeout
  - `context.aws_request_id` — unique ID for this invocation (useful for tracing)

The function name **must match** the `Handler` setting in your Lambda configuration.
If your file is `handler.py` and the function is `lambda_handler`, the Handler value
is `handler.lambda_handler`.

> **Ref:** [Lambda Python handler](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html) · [Context object](https://docs.aws.amazon.com/lambda/latest/dg/python-context.html)

---

### 1.3 — Input Detection: API Gateway vs. Direct Invocation

```python
try:
    # Support both direct invocation and API Gateway proxy format
    if "body" in event and "httpMethod" in event:
```

This is a **duck-typing check**. When API Gateway uses **Lambda Proxy Integration**, it
wraps the HTTP request into a standardized envelope:

```json
{
  "httpMethod": "POST",
  "body": "{\"image\": \"base64...\", \"filename\": \"scan.png\"}",
  "isBase64Encoded": false,
  "headers": { ... },
  "pathParameters": { ... },
  "queryStringParameters": { ... }
}
```

If `httpMethod` and `body` are both present → it's an API Gateway proxy event.
Otherwise → it's a direct invocation (the payload IS the data).

> **Ref:** [API Gateway proxy integration](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html)

---

### 1.4 — Extracting & Decoding the Body

```python
        body = event.get("body", "")
        if event.get("isBase64Encoded", False):
            body = base64.b64decode(body).decode("utf-8")
        payload = json.loads(body) if isinstance(body, str) else body
```

**Step by step:**

1. **`event.get("body", "")`** — Safely retrieves the body. The body is a JSON *string*,
   not a dict, in proxy integration mode.

2. **`isBase64Encoded` check** — When API Gateway receives binary content (e.g.,
   `Content-Type: application/octet-stream` or multipart), it Base64-encodes the body
   and sets this flag to `true`. We decode it back to a UTF-8 string before parsing.

3. **`json.loads(body)`** — Parses the JSON string into a Python dict.
   The `isinstance(body, str)` guard prevents double-parsing if body is already a dict
   (defensive programming).

```python
    else:
        payload = event
```

For direct invocations (SDK `invoke()`, Step Functions, test console), the `event` dict
IS the payload — no unwrapping needed.

---

### 1.5 — Extracting Input Fields

```python
        image_data = payload.get("image", "")
        filename = payload.get("filename", "unknown")

        if not image_data:
            return {"error": "No image data provided"}
```

The function expects a payload shaped like:

```json
{
  "image": "<base64-encoded image data>",
  "filename": "receipt.png"
}
```

- **`image`** — The raw Base64 string of the image bytes.
- **`filename`** — Used to determine the file extension (`.png`, `.jpg`, `.tiff`).
  Defaults to `"unknown"` so the code won't crash if omitted.

The early return with an error dict is a **guard clause** — fail fast with a clear message.

---

### 1.6 — Stripping the Data URL Prefix

```python
        # Strip data URL prefix if present (e.g. "data:image/png;base64,...")
        if "," in image_data:
            image_data = image_data.split(",", 1)[1]
```

Browsers and front-end frameworks often encode images as **Data URLs**:

```
data:image/png;base64,iVBORw0KGgoAAAANSUhEU...
```

The actual Base64 data starts **after the comma**. `split(",", 1)[1]` extracts
everything after the first comma, discarding the MIME prefix.

The `1` in `split(",", 1)` limits to one split — important because Base64 data
can legitimately contain commas in rare edge cases (though standard Base64 uses
`A-Za-z0-9+/=` only, this is still good defensive practice).

> **Ref:** [Data URLs (MDN)](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs)

---

### 1.7 — Decoding Image Bytes

```python
        image_bytes = base64.b64decode(image_data)
```

Converts the Base64 string to raw binary bytes. For a 1 MB image, the Base64 string
is ~1.33 MB (Base64 has ~33% overhead). The decoded `bytes` object is the actual
image file content.

> **Ref:** [base64.b64decode](https://docs.python.org/3/library/base64.html#base64.b64decode)

---

### 1.8 — Writing to a Temporary File

```python
        suffix = os.path.splitext(filename)[1] or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name
```

**Why a temp file?** Tesseract is a command-line tool that expects a *file path*
as input — it can't read from stdin for image data. So we bridge the gap.

**Breakdown:**

| Expression | What It Does |
|-----------|-------------|
| `os.path.splitext(filename)[1]` | Extracts the file extension: `"receipt.png"` → `".png"` |
| `or ".png"` | Falls back to `.png` if filename has no extension |
| `NamedTemporaryFile(suffix=suffix, delete=False)` | Creates a temp file like `/tmp/tmpXXXXXX.png`. `delete=False` prevents auto-deletion when the `with` block exits — we need the file to persist until Tesseract reads it |
| `tmp.write(image_bytes)` | Writes the raw binary image data to disk |
| `tmp.name` | The full path, e.g., `/tmp/tmp8f3k2x.png` |

> **Warning:** Lambda's `/tmp` persists between warm invocations. Always clean up
> temp files (see 1.11) or you'll accumulate garbage across invocations.
>
> **Ref:** [tempfile.NamedTemporaryFile](https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile) · [Lambda execution environment](https://docs.aws.amazon.com/lambda/latest/dg/running-lambda-code.html)

---

### 1.9 — Running Tesseract OCR

```python
        start_time = time.time()

        result = subprocess.run(
            ["tesseract", tmp_path, "stdout", "--oem", "1", "--psm", "3"],
            capture_output=True,
            text=True,
            timeout=30
        )

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
```

**The Tesseract command explained:**

```
tesseract <input_file> stdout --oem 1 --psm 3
```

| Argument | Meaning |
|----------|---------|
| `tmp_path` | Input image file path |
| `stdout` | Output destination — writing to stdout instead of a file lets us capture it in Python |
| `--oem 1` | **OCR Engine Mode 1** = LSTM neural network only (most accurate). Options: 0=Legacy, 1=LSTM, 2=Legacy+LSTM, 3=Default |
| `--psm 3` | **Page Segmentation Mode 3** = Fully automatic page segmentation (no OSD). Tesseract analyzes the layout and finds text blocks automatically |

**`subprocess.run` parameters:**

| Parameter | Purpose |
|-----------|---------|
| `capture_output=True` | Captures both `stdout` (the OCR text) and `stderr` (errors/warnings) |
| `text=True` | Returns strings instead of bytes — decodes stdout/stderr using the system encoding |
| `timeout=30` | Kills the process after 30 seconds. Critical in Lambda to avoid hitting the function timeout and wasting money |

**Timing:**

- `time.time()` returns seconds as a float → we convert to milliseconds for readability.
- `round(..., 2)` gives us 2 decimal places, e.g., `1245.67` ms.

> **Ref:** [Tesseract CLI](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html) · [subprocess.run](https://docs.python.org/3/library/subprocess.html#subprocess.run) · [Tesseract OEM/PSM](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)

---

### 1.10 — Cleanup

```python
        os.unlink(tmp_path)
```

Deletes the temporary image file from `/tmp`. This is essential because:

1. Lambda reuses execution environments (warm starts). Without cleanup, `/tmp` fills up.
2. The ephemeral storage has a configurable limit (512 MB–10 GB). Orphaned files eat into it.
3. Sensitive image data should not linger on disk longer than necessary.

> **Ref:** [os.unlink](https://docs.python.org/3/library/os.html#os.unlink)

---

### 1.11 — Processing Results

```python
        extracted_text = result.stdout.strip()

        if result.returncode != 0 and not extracted_text:
            return {
                "error": "Tesseract OCR failed: " + result.stderr.strip(),
                "processing_time_ms": elapsed_ms
            }
```

- **`result.stdout.strip()`** — The OCR output text, with leading/trailing whitespace removed.
- **Error check logic:** Tesseract sometimes returns a non-zero exit code but still
  produces partial output. The `and not extracted_text` condition means: only treat it
  as a failure if *both* the exit code is bad AND no text was extracted. This is pragmatic —
  partial results are often still useful.

---

### 1.12 — Success Response

```python
        return {
            "text": extracted_text,
            "processing_time_ms": elapsed_ms,
            "filename": filename,
            "text_length": len(extracted_text),
            "word_count": len(extracted_text.split()) if extracted_text else 0
        }
```

| Field | Purpose |
|-------|---------|
| `text` | The extracted OCR text |
| `processing_time_ms` | How long Tesseract took (for monitoring/optimization) |
| `filename` | Echo back the original filename (useful for batch processing pipelines) |
| `text_length` | Character count — quick quality indicator |
| `word_count` | Word count via `split()` — splits on any whitespace. The ternary guard avoids calling `.split()` on an empty string (which would return `['']`, giving count 1 instead of 0) |

Lambda automatically serializes this dict to JSON for the caller.

---

### 1.13 — Global Exception Handler

```python
    except Exception as e:
        return {"error": str(e)}
```

Catches any unhandled exception and returns it as an error message. This prevents
Lambda from raising an unhandled exception (which would show up as a 502 in API Gateway
and trigger retries for async invocations).

**Production improvement:** You'd want to add `logging` and re-raise critical errors
so CloudWatch and X-Ray can track them properly.

---

## 2. How the Lambda Accepts Input

The handler supports **two invocation patterns**:

### Pattern A: API Gateway Proxy Integration (HTTP)

```
Client → API Gateway → Lambda
```

```bash
curl -X POST https://abc123.execute-api.us-east-1.amazonaws.com/prod/ocr \
  -H "Content-Type: application/json" \
  -d '{
    "image": "iVBORw0KGgoAAAANSUhEU...",
    "filename": "receipt.png"
  }'
```

API Gateway wraps this into a proxy event with `httpMethod`, `body`, `headers`, etc.
The handler detects this and extracts the body.

### Pattern B: Direct Invocation (SDK / Step Functions / Console)

```bash
aws lambda invoke \
  --function-name ocr-function \
  --payload '{"image": "iVBORw0KGgo...", "filename": "scan.jpg"}' \
  response.json
```

Here `event` IS the payload directly — no unwrapping needed.

### Input Schema

```json
{
  "image": "string (required) — Base64-encoded image data, with or without data URL prefix",
  "filename": "string (optional) — Original filename, used for file extension detection"
}
```

### Limitation of Current Design

The image data is embedded **inline** in the payload. This has hard limits:

| Invocation Method | Max Payload Size |
|-------------------|-----------------|
| Synchronous (RequestResponse) | 6 MB |
| Asynchronous (Event) | 256 KB |
| API Gateway | 10 MB (request body) |

For anything larger, you need **S3 references** — which leads us to the next section.

> **Ref:** [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) · [API Gateway limits](https://docs.aws.amazon.com/apigateway/latest/developerguide/limits.html)

---

## 3. Modified Handler with S3 Support

Below is the enhanced handler that accepts either inline Base64 data (original behavior)
**or** an S3 reference (`bucket` + `key`):

```python
import json
import base64
import time
import subprocess
import tempfile
import os
import boto3
from botocore.exceptions import ClientError

# Initialize S3 client outside the handler for connection reuse across warm starts
# Ref: https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html
s3_client = boto3.client("s3")


def lambda_handler(event, context):
    """
    OCR Lambda handler — extracts text from images.

    Accepts two input modes:
      1. Inline:  { "image": "<base64>", "filename": "scan.png" }
      2. S3 ref:  { "bucket": "my-bucket", "key": "uploads/scan.png" }

    When invoked by S3 Event Notifications the event contains a "Records" array;
    this handler also supports that format.
    """

    try:
        # ──────────────────────────────────────────────
        # STEP 1: Normalize the input payload
        # ──────────────────────────────────────────────

        # API Gateway Proxy Integration wraps the real payload inside "body"
        if "body" in event and "httpMethod" in event:
            body = event.get("body", "")
            if event.get("isBase64Encoded", False):
                body = base64.b64decode(body).decode("utf-8")
            payload = json.loads(body) if isinstance(body, str) else body

        # S3 Event Notification format — triggered when a file lands in S3
        # Ref: https://docs.aws.amazon.com/lambda/latest/dg/with-s3.html
        elif "Records" in event and event["Records"][0].get("eventSource") == "aws:s3":
            record = event["Records"][0]["s3"]
            payload = {
                "bucket": record["bucket"]["name"],
                "key": record["object"]["key"],
            }

        # Direct invocation / Step Functions
        else:
            payload = event

        # ──────────────────────────────────────────────
        # STEP 2: Get the image bytes
        # ──────────────────────────────────────────────

        bucket = payload.get("bucket")
        key = payload.get("key")
        image_data = payload.get("image", "")
        filename = payload.get("filename", "unknown")

        if bucket and key:
            # ── S3 Mode ──
            # Download file from S3 into memory
            # Ref: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_object.html
            try:
                s3_response = s3_client.get_object(Bucket=bucket, Key=key)
                image_bytes = s3_response["Body"].read()
                filename = os.path.basename(key)  # e.g., "uploads/scan.png" → "scan.png"

                # Get the content type from S3 metadata for validation
                content_type = s3_response.get("ContentType", "")
                print(f"[S3] Downloaded s3://{bucket}/{key} "
                      f"({len(image_bytes)} bytes, {content_type})")

            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                return {
                    "error": f"S3 error ({error_code}): {e.response['Error']['Message']}",
                    "bucket": bucket,
                    "key": key,
                }

        elif image_data:
            # ── Inline Base64 Mode (original behavior) ──
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]
            image_bytes = base64.b64decode(image_data)

        else:
            return {"error": "Provide either 'bucket'+'key' or 'image' (base64)"}

        # ──────────────────────────────────────────────
        # STEP 3: Write to temp file & run Tesseract
        # ──────────────────────────────────────────────

        suffix = os.path.splitext(filename)[1] or ".png"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        start_time = time.time()

        result = subprocess.run(
            ["tesseract", tmp_path, "stdout", "--oem", "1", "--psm", "3"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        # Always clean up
        os.unlink(tmp_path)

        extracted_text = result.stdout.strip()

        if result.returncode != 0 and not extracted_text:
            return {
                "error": "Tesseract OCR failed: " + result.stderr.strip(),
                "processing_time_ms": elapsed_ms,
            }

        # ──────────────────────────────────────────────
        # STEP 4: Return results
        # ──────────────────────────────────────────────

        response = {
            "text": extracted_text,
            "processing_time_ms": elapsed_ms,
            "filename": filename,
            "text_length": len(extracted_text),
            "word_count": len(extracted_text.split()) if extracted_text else 0,
        }

        # Include S3 source info if applicable
        if bucket and key:
            response["source"] = f"s3://{bucket}/{key}"

        return response

    except Exception as e:
        return {"error": str(e)}
```

### Key Changes Explained

**1. `boto3` client initialization outside the handler:**

```python
s3_client = boto3.client("s3")
```

This is an **AWS best practice**. Code outside the handler runs once when Lambda
initializes (cold start). On subsequent warm invocations, the client is reused —
saving ~200-400 ms of connection setup each time.

> **Ref:** [Lambda best practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)

**2. S3 Event Notification support:**

When S3 triggers Lambda directly (e.g., on `s3:ObjectCreated:*`), the event looks like:

```json
{
  "Records": [
    {
      "eventSource": "aws:s3",
      "s3": {
        "bucket": { "name": "my-bucket" },
        "object": { "key": "uploads/receipt.png" }
      }
    }
  ]
}
```

The handler now detects this format and extracts `bucket` and `key`.

**3. IAM permissions required:**

The Lambda execution role needs this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::your-bucket-name/*"
    }
  ]
}
```

> **Ref:** [Lambda execution role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html) · [S3 GetObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)

**4. Sample invocations for the new S3 mode:**

```bash
# Direct invocation with S3 reference
aws lambda invoke \
  --function-name ocr-function \
  --payload '{"bucket": "my-docs", "key": "scans/receipt.png"}' \
  response.json

# Or via API Gateway
curl -X POST https://abc.execute-api.us-east-1.amazonaws.com/prod/ocr \
  -d '{"bucket": "my-docs", "key": "scans/receipt.png"}'
```

---

## 4. LocalStack Docker Compose Setup

### 4.1 — Directory Structure

```
project/
├── docker-compose.yml
├── lambda/
│   ├── handler.py              # The modified handler above
│   └── requirements.txt
├── step-function/
│   └── definition.json         # Step Function ASL definition
├── sample-docs/                # Sample files to upload to S3
│   ├── invoice.png
│   ├── receipt.jpg
│   ├── contract.pdf
│   ├── spreadsheet.xlsx
│   ├── readme.txt
│   └── report.docx
└── init-scripts/
    └── setup.sh                # Bootstrap script — creates bucket, uploads files, deploys Lambda & Step Function
```

### 4.2 — docker-compose.yml

```yaml
# docker-compose.yml
# Ref: https://docs.localstack.cloud/getting-started/installation/#docker-compose

version: "3.8"

services:
  localstack:
    image: localstack/localstack:latest
    container_name: localstack
    ports:
      - "4566:4566"           # LocalStack Gateway — all AWS services on one port
      - "4510-4559:4510-4559" # External service port range
    environment:
      # Core config
      - SERVICES=s3,lambda,stepfunctions,iam,sts,logs
      - DEBUG=1
      - LAMBDA_EXECUTOR=docker       # Run Lambdas in separate Docker containers
      - LAMBDA_REMOTE_DOCKER=false   # Use local Docker socket
      - DOCKER_HOST=unix:///var/run/docker.sock

      # Persistence — data survives container restarts
      - PERSISTENCE=1
      - DATA_DIR=/var/lib/localstack/data

    volumes:
      # Docker socket — required for Lambda containers
      - "/var/run/docker.sock:/var/run/docker.sock"

      # Persistent data
      - "localstack-data:/var/lib/localstack"

      # Mount init script — LocalStack auto-runs *.sh files in this directory on startup
      # Ref: https://docs.localstack.cloud/references/init-hooks/
      - "./init-scripts:/etc/localstack/init/ready.d"

      # Mount sample docs so the init script can upload them
      - "./sample-docs:/tmp/sample-docs"

      # Mount lambda code
      - "./lambda:/tmp/lambda-code"

      # Mount step function definition
      - "./step-function:/tmp/step-function"

volumes:
  localstack-data:
```

### 4.3 — init-scripts/setup.sh

```bash
#!/bin/bash
# =============================================================
# LocalStack Init Script
# Runs automatically when LocalStack is "ready"
# =============================================================

set -euo pipefail

ENDPOINT="http://localhost:4566"
BUCKET="document-processing-bucket"
REGION="us-east-1"

echo "=========================================="
echo "  Setting up LocalStack resources..."
echo "=========================================="

# ─────────────────────────────────────────────
# 1. Create S3 Bucket
# ─────────────────────────────────────────────
echo "[1/5] Creating S3 bucket: ${BUCKET}"
awslocal s3 mb "s3://${BUCKET}" --region ${REGION} 2>/dev/null || true

# ─────────────────────────────────────────────
# 2. Create sample documents of various types
# ─────────────────────────────────────────────
echo "[2/5] Uploading sample documents..."

# Create sample text files if sample-docs directory is empty
if [ ! -f /tmp/sample-docs/readme.txt ]; then
    mkdir -p /tmp/sample-docs
    echo "This is a plain text file." > /tmp/sample-docs/readme.txt
    echo '{"name": "test", "value": 42}' > /tmp/sample-docs/data.json
    echo "col1,col2,col3\na,b,c\n1,2,3" > /tmp/sample-docs/report.csv

    # Create a minimal valid PNG (1x1 red pixel)
    echo -n -e '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82' > /tmp/sample-docs/invoice.png

    # Minimal JPEG (1x1 white pixel)
    python3 -c "
import struct, sys
# Minimal valid JPEG
data = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
    0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
    0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
    0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
    0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
    0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
    0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
    0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
    0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
    0x09, 0x0A, 0x0B, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F,
    0x00, 0x7B, 0x40, 0x1B, 0xFF, 0xD9
])
sys.stdout.buffer.write(data)
" > /tmp/sample-docs/receipt.jpg

    # Create a minimal PDF
    python3 -c "
pdf = b'''%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 12 Tf 100 700 Td (Sample PDF Document) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000360 00000 n 
trailer<</Size 6/Root 1 0 R>>
startxref
431
%%EOF'''
import sys; sys.stdout.buffer.write(pdf)
" > /tmp/sample-docs/contract.pdf

    echo "Created synthetic sample files."
fi

# Upload ALL sample documents with correct content types
declare -A CONTENT_TYPES=(
    ["png"]="image/png"
    ["jpg"]="image/jpeg"
    ["jpeg"]="image/jpeg"
    ["gif"]="image/gif"
    ["tiff"]="image/tiff"
    ["tif"]="image/tiff"
    ["bmp"]="image/bmp"
    ["pdf"]="application/pdf"
    ["txt"]="text/plain"
    ["csv"]="text/csv"
    ["json"]="application/json"
    ["xlsx"]="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ["docx"]="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

for file in /tmp/sample-docs/*; do
    if [ -f "$file" ]; then
        basename=$(basename "$file")
        ext="${basename##*.}"
        ext_lower=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
        content_type="${CONTENT_TYPES[$ext_lower]:-application/octet-stream}"

        awslocal s3 cp "$file" "s3://${BUCKET}/uploads/${basename}" \
            --content-type "$content_type" \
            --region ${REGION}

        echo "  ✓ Uploaded: uploads/${basename} (${content_type})"
    fi
done

# ─────────────────────────────────────────────
# 3. Create IAM Role for Lambda
# ─────────────────────────────────────────────
echo "[3/5] Creating IAM role..."

awslocal iam create-role \
    --role-name lambda-ocr-role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }' 2>/dev/null || true

awslocal iam put-role-policy \
    --role-name lambda-ocr-role \
    --policy-name s3-read \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:HeadObject"],
            "Resource": "arn:aws:s3:::'"${BUCKET}"'/*"
        }]
    }' 2>/dev/null || true

# ─────────────────────────────────────────────
# 4. Package and Deploy Lambda
# ─────────────────────────────────────────────
echo "[4/5] Deploying Lambda function..."

cd /tmp/lambda-code
zip -j /tmp/ocr-lambda.zip handler.py 2>/dev/null

awslocal lambda create-function \
    --function-name ocr-processor \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --role arn:aws:iam::000000000000:role/lambda-ocr-role \
    --zip-file fileb:///tmp/ocr-lambda.zip \
    --timeout 60 \
    --memory-size 512 \
    --region ${REGION} 2>/dev/null || \
awslocal lambda update-function-code \
    --function-name ocr-processor \
    --zip-file fileb:///tmp/ocr-lambda.zip \
    --region ${REGION}

# ─────────────────────────────────────────────
# 5. Create Step Function
# ─────────────────────────────────────────────
echo "[5/5] Creating Step Function..."

# Create Step Functions execution role
awslocal iam create-role \
    --role-name stepfunctions-role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "states.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }' 2>/dev/null || true

awslocal iam put-role-policy \
    --role-name stepfunctions-role \
    --policy-name invoke-lambda \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["lambda:InvokeFunction"],
            "Resource": "*"
        }]
    }' 2>/dev/null || true

awslocal stepfunctions create-state-machine \
    --name document-processing-pipeline \
    --definition "$(cat /tmp/step-function/definition.json)" \
    --role-arn arn:aws:iam::000000000000:role/stepfunctions-role \
    --region ${REGION} 2>/dev/null || \
awslocal stepfunctions update-state-machine \
    --state-machine-arn arn:aws:states:${REGION}:000000000000:stateMachine:document-processing-pipeline \
    --definition "$(cat /tmp/step-function/definition.json)"

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "=========================================="
echo ""
echo "  S3 Bucket:       ${BUCKET}"
echo "  Lambda:          ocr-processor"
echo "  Step Function:   document-processing-pipeline"
echo ""
echo "  Test commands:"
echo "    awslocal s3 ls s3://${BUCKET}/uploads/"
echo "    awslocal lambda invoke --function-name ocr-processor --payload '{\"bucket\":\"${BUCKET}\",\"key\":\"uploads/invoice.png\"}' /tmp/out.json && cat /tmp/out.json"
echo "    awslocal stepfunctions start-execution --state-machine-arn arn:aws:states:${REGION}:000000000000:stateMachine:document-processing-pipeline --input '{\"bucket\":\"${BUCKET}\",\"key\":\"uploads/contract.pdf\"}'"
echo ""
```

> **Make this executable:** `chmod +x init-scripts/setup.sh`

### 4.4 — Verifying the Setup

```bash
# Start LocalStack
docker compose up -d

# Wait for it to be ready (~10-20 seconds)
docker logs -f localstack

# List files in the bucket
awslocal s3 ls s3://document-processing-bucket/uploads/

# Expected output:
#   2025-01-01 00:00:00        125 contract.pdf
#   2025-01-01 00:00:00         30 data.json
#   2025-01-01 00:00:00         67 invoice.png
#   2025-01-01 00:00:00        154 receipt.jpg
#   2025-01-01 00:00:00         27 readme.txt
#   2025-01-01 00:00:00         23 report.csv
```

> **Ref:** [LocalStack Docker Compose](https://docs.localstack.cloud/getting-started/installation/#docker-compose) · [awslocal CLI](https://docs.localstack.cloud/user-guide/integrations/aws-cli/#localstack-aws-cli-awslocal)

---

## 5. Step Function — Filter by Document Type

The Step Function receives a document reference and uses a **Choice state** to route
only PDFs and images to the OCR Lambda. All other file types are routed to a
"not supported" pass-through state.

### 5.1 — step-function/definition.json (Amazon States Language)

```json
{
  "Comment": "Document Processing Pipeline — routes PDFs and images to OCR Lambda, skips unsupported types",
  "StartAt": "ExtractFileExtension",
  "States": {

    "ExtractFileExtension": {
      "Type": "Pass",
      "Comment": "Extracts the file extension from the S3 key for routing decisions. Uses intrinsic functions to parse the key string.",
      "Parameters": {
        "bucket.$": "$.bucket",
        "key.$": "$.key",
        "file_extension.$": "States.ArrayGetItem(States.StringSplit($.key, '.'), States.MathAdd(States.ArrayLength(States.StringSplit($.key, '.')), -1))"
      },
      "ResultPath": "$",
      "Next": "NormalizeExtension"
    },

    "NormalizeExtension": {
      "Type": "Pass",
      "Comment": "Lowercases the extension for consistent matching",
      "Parameters": {
        "bucket.$": "$.bucket",
        "key.$": "$.key",
        "file_extension.$": "States.StringToJson(States.Format('\"{}\"', $.file_extension))",
        "extension_lower.$": "$.file_extension"
      },
      "ResultPath": "$",
      "Next": "IsDocumentProcessable"
    },

    "IsDocumentProcessable": {
      "Type": "Choice",
      "Comment": "Routes documents based on file extension. Only PDFs and image types proceed to OCR.",
      "Choices": [
        {
          "Comment": "── PDF files ──",
          "Variable": "$.extension_lower",
          "StringEquals": "pdf",
          "Next": "ProcessWithOCR"
        },
        {
          "Comment": "── PNG images ──",
          "Variable": "$.extension_lower",
          "StringEquals": "png",
          "Next": "ProcessWithOCR"
        },
        {
          "Comment": "── JPEG images (.jpg) ──",
          "Variable": "$.extension_lower",
          "StringEquals": "jpg",
          "Next": "ProcessWithOCR"
        },
        {
          "Comment": "── JPEG images (.jpeg) ──",
          "Variable": "$.extension_lower",
          "StringEquals": "jpeg",
          "Next": "ProcessWithOCR"
        },
        {
          "Comment": "── TIFF images (.tiff) ──",
          "Variable": "$.extension_lower",
          "StringEquals": "tiff",
          "Next": "ProcessWithOCR"
        },
        {
          "Comment": "── TIFF images (.tif) ──",
          "Variable": "$.extension_lower",
          "StringEquals": "tif",
          "Next": "ProcessWithOCR"
        },
        {
          "Comment": "── BMP images ──",
          "Variable": "$.extension_lower",
          "StringEquals": "bmp",
          "Next": "ProcessWithOCR"
        },
        {
          "Comment": "── GIF images ──",
          "Variable": "$.extension_lower",
          "StringEquals": "gif",
          "Next": "ProcessWithOCR"
        }
      ],
      "Default": "DocumentTypeNotSupported"
    },

    "ProcessWithOCR": {
      "Type": "Task",
      "Comment": "Invokes the OCR Lambda with the S3 bucket and key. The Lambda downloads the file, runs Tesseract, and returns extracted text.",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "ocr-processor",
        "Payload": {
          "bucket.$": "$.bucket",
          "key.$": "$.key"
        }
      },
      "ResultSelector": {
        "statusCode": 200,
        "ocr_result.$": "$.Payload"
      },
      "ResultPath": "$.processing_result",
      "Retry": [
        {
          "ErrorEquals": ["Lambda.ServiceException", "Lambda.TooManyRequestsException"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "ProcessingFailed"
        }
      ],
      "Next": "ProcessingComplete"
    },

    "DocumentTypeNotSupported": {
      "Type": "Pass",
      "Comment": "Handles unsupported document types gracefully. Returns metadata about what was skipped and why.",
      "Parameters": {
        "status": "SKIPPED",
        "reason": "Document type not supported for OCR processing",
        "supported_types": ["pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "gif"],
        "file": {
          "bucket.$": "$.bucket",
          "key.$": "$.key",
          "detected_extension.$": "$.extension_lower"
        }
      },
      "End": true
    },

    "ProcessingComplete": {
      "Type": "Pass",
      "Comment": "Terminal success state",
      "Parameters": {
        "status": "COMPLETED",
        "file": {
          "bucket.$": "$.bucket",
          "key.$": "$.key"
        },
        "result.$": "$.processing_result.ocr_result"
      },
      "End": true
    },

    "ProcessingFailed": {
      "Type": "Pass",
      "Comment": "Terminal failure state — captures error details for debugging",
      "Parameters": {
        "status": "FAILED",
        "file": {
          "bucket.$": "$.bucket",
          "key.$": "$.key"
        },
        "error.$": "$.error_info"
      },
      "End": true
    }
  }
}
```

### 5.2 — Step Function Flow Diagram

```
                    ┌─────────────────────┐
                    │  Input:             │
                    │  { bucket, key }    │
                    └─────────┬───────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │ ExtractFileExtension│
                    │ (Pass + Intrinsics) │
                    └─────────┬───────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │ NormalizeExtension   │
                    └─────────┬───────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │ IsDocumentProcessable│
                    │      (Choice)       │
                    └───┬─────────────┬───┘
                        │             │
            ┌───────────┘             └────────────┐
            │ pdf/png/jpg/                         │ Default
            │ jpeg/tiff/bmp/gif                    │ (xlsx/docx/txt/csv...)
            ▼                                      ▼
  ┌──────────────────┐              ┌──────────────────────────┐
  │  ProcessWithOCR  │              │ DocumentTypeNotSupported  │
  │  (Lambda:invoke) │              │ (Pass — returns SKIPPED)  │
  └────┬─────────┬───┘              └──────────────────────────┘
       │         │
   ┌───┘         └───┐
   │ Success         │ Catch
   ▼                 ▼
┌──────────────┐  ┌──────────────────┐
│ Processing   │  │ ProcessingFailed │
│ Complete     │  │ (Pass — error)   │
└──────────────┘  └──────────────────┘
```

### 5.3 — Key Concepts in the Step Function

**Choice State** — The routing logic. It evaluates `$.extension_lower` against known
processable types. Each `StringEquals` comparison checks one extension. The `Default`
branch catches everything else.

> **Ref:** [Choice state](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-choice-state.html)

**Intrinsic Functions** — `States.StringSplit`, `States.ArrayGetItem`, `States.ArrayLength`,
and `States.MathAdd` are used to extract the file extension from the S3 key without
needing a Lambda just for parsing.

> **Ref:** [Intrinsic functions](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-intrinsic-functions.html)

**Retry & Catch** — The `ProcessWithOCR` state has automatic retry for transient Lambda
errors (throttling, service exceptions) with exponential backoff (2s → 4s → 8s). Non-retryable
errors fall through to `Catch` which routes to `ProcessingFailed`.

> **Ref:** [Error handling in Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)

**`ResultSelector` & `ResultPath`** — `ResultSelector` reshapes the Lambda response.
`ResultPath` controls where in the overall state object the result is placed (here,
under `$.processing_result`), preserving the original input.

> **Ref:** [Input and output processing](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-input-output-filtering.html)

### 5.4 — Testing the Step Function

```bash
# ── Test with a PDF (should be PROCESSED) ──
awslocal stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:000000000000:stateMachine:document-processing-pipeline \
  --input '{"bucket":"document-processing-bucket","key":"uploads/contract.pdf"}'

# ── Test with a PNG (should be PROCESSED) ──
awslocal stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:000000000000:stateMachine:document-processing-pipeline \
  --input '{"bucket":"document-processing-bucket","key":"uploads/invoice.png"}'

# ── Test with a .txt file (should be SKIPPED) ──
awslocal stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:000000000000:stateMachine:document-processing-pipeline \
  --input '{"bucket":"document-processing-bucket","key":"uploads/readme.txt"}'

# ── Test with a .xlsx file (should be SKIPPED) ──
awslocal stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:000000000000:stateMachine:document-processing-pipeline \
  --input '{"bucket":"document-processing-bucket","key":"uploads/spreadsheet.xlsx"}'

# ── Check execution result ──
awslocal stepfunctions describe-execution \
  --execution-arn <execution-arn-from-above>
```

---

## 6. Official References & Links

### AWS Documentation

| Topic | Link |
|-------|------|
| Lambda Python Handler | https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html |
| Lambda Context Object | https://docs.aws.amazon.com/lambda/latest/dg/python-context.html |
| Lambda Execution Environment | https://docs.aws.amazon.com/lambda/latest/dg/running-lambda-code.html |
| Lambda Best Practices | https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html |
| Lambda Quotas (Payload Limits) | https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html |
| Lambda Ephemeral Storage (/tmp) | https://docs.aws.amazon.com/lambda/latest/dg/configuration-ephemeral-storage.html |
| Lambda Execution Role | https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html |
| Lambda with S3 | https://docs.aws.amazon.com/lambda/latest/dg/with-s3.html |
| API Gateway Proxy Integration | https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html |
| S3 GetObject API | https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html |
| Step Functions Developer Guide | https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html |
| Step Functions Choice State | https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-choice-state.html |
| Step Functions Intrinsic Functions | https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-intrinsic-functions.html |
| Step Functions Error Handling | https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html |
| Boto3 S3 Client | https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html |

### Python Standard Library

| Module | Link |
|--------|------|
| json | https://docs.python.org/3/library/json.html |
| base64 | https://docs.python.org/3/library/base64.html |
| subprocess | https://docs.python.org/3/library/subprocess.html |
| tempfile | https://docs.python.org/3/library/tempfile.html |
| os | https://docs.python.org/3/library/os.html |
| time | https://docs.python.org/3/library/time.html |

### External Tools

| Tool | Link |
|------|------|
| Tesseract OCR | https://tesseract-ocr.github.io/tessdoc/ |
| Tesseract CLI Usage | https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html |
| LocalStack Docs | https://docs.localstack.cloud/ |
| LocalStack Docker Setup | https://docs.localstack.cloud/getting-started/installation/#docker-compose |
| LocalStack Init Hooks | https://docs.localstack.cloud/references/init-hooks/ |