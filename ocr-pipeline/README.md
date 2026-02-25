# Tesseract OCR — Event-Driven Pipeline

# Running a Lambda with a Custom Tesseract OCR Image on LocalStack (Free Tier)

## Overview

LocalStack's **free tier** supports Lambda functions backed by **custom Docker images**. You'll build a container image with Tesseract OCR, push it to a **local ECR emulation**, and create the Lambda from that image URI.

---

## Step 1: Project Structure

```
my-lambda/
├── app.py
├── Dockerfile
└── deploy.sh
```

## Step 2: Lambda Handler (`app.py`)

```python
import subprocess
import json
import base64
import os

def handler(event, context):
    # Decode the base64-encoded image from the event
    image_data = base64.b64decode(event["image_base64"])

    tmp_path = "/tmp/input.png"
    with open(tmp_path, "wb") as f:
        f.write(image_data)

    # Run Tesseract OCR
    result = subprocess.run(
        ["tesseract", tmp_path, "stdout", "-l", "eng"],
        capture_output=True, text=True
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "text": result.stdout.strip(),
            "errors": result.stderr.strip()
        })
    }
```

## Step 3: Dockerfile

```dockerfile
# Use the official AWS Lambda Python base image
FROM public.ecr.aws/lambda/python:3.11

# Install Tesseract OCR and dependencies
RUN yum install -y \
    tesseract \
    tesseract-langpack-eng \
    && yum clean all

# (If tesseract isn't in the AL2 yum repo, build from source or use Amazon Linux extras)
# Alternative: use a Debian-based approach below 👇

COPY app.py ${LAMBDA_TASK_ROOT}/

CMD ["app.handler"]
```

### Alternative Dockerfile (Debian-based — more reliable for Tesseract)

```dockerfile
# --- Build stage ---
FROM python:3.11-slim as build

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# --- Final image using AWS Lambda RIE ---
FROM python:3.11-slim

# Install the Lambda Runtime Interface Client
RUN pip install awslambdaric

# Install tesseract in final image
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /var/task
COPY app.py .

# The entrypoint for container-image Lambdas
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["app.handler"]
```

## Step 4: Deploy Script (`deploy.sh`)

```bash
#!/bin/bash
set -e

LOCALSTACK_URL="http://localhost:4566"
REGION="us-east-1"
FUNCTION_NAME="tesseract-ocr-lambda"
IMAGE_NAME="tesseract-lambda"
REPO_NAME="my-lambda-repo"

# ---------------------------------------------------
# 1. Build the Docker image
# ---------------------------------------------------
docker build -t ${IMAGE_NAME}:latest .

# ---------------------------------------------------
# 2. Create an ECR repository in LocalStack
# ---------------------------------------------------
awslocal ecr create-repository --repository-name ${REPO_NAME} 2>/dev/null || true

# ---------------------------------------------------
# 3. Tag and push to LocalStack's ECR
# ---------------------------------------------------
# LocalStack ECR endpoint format:
ECR_URI="localhost.localstack.cloud:4510/${REPO_NAME}"

docker tag ${IMAGE_NAME}:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest

# ---------------------------------------------------
# 4. Create the Lambda function from the image
# ---------------------------------------------------
awslocal lambda create-function \
    --function-name ${FUNCTION_NAME} \
    --package-type Image \
    --code ImageUri="${ECR_URI}:latest" \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --timeout 60 \
    --memory-size 512

echo "✅ Lambda '${FUNCTION_NAME}' created successfully!"
```

## Step 5: Invoke It

```bash
# Create a base64-encoded test payload
IMAGE_B64=$(base64 -w 0 sample.png)

awslocal lambda invoke \
    --function-name tesseract-ocr-lambda \
    --payload "{\"image_base64\": \"${IMAGE_B64}\"}" \
    output.json

cat output.json | python -m json.tool
```

---

## Key Points for LocalStack Free Tier

| Concern | Solution |
|---|---|
| **Lambda container images** | ✅ Supported in free tier |
| **ECR push** | Use `localhost.localstack.cloud:4510` as the registry |
| **No Pro features needed** | `package-type Image` + ECR works on Community |
| **Docker-in-Docker** | Make sure LocalStack has access to Docker socket (`-v /var/run/docker.sock:/var/run/docker.sock`) |

## LocalStack `docker-compose.yml`

```yaml
version: "3.8"
services:
  localstack:
    image: localstack/localstack:latest
    ports:
      - "4566:4566"
      - "4510-4559:4510-4559"   # ECR port range
    environment:
      - SERVICES=lambda,ecr
      - LAMBDA_EXECUTOR=docker    # runs each Lambda in its own container
      - DOCKER_HOST=unix:///var/run/docker.sock
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./localstack-data:/var/lib/localstack
```

> **Critical**: `LAMBDA_EXECUTOR=docker` (or `docker-reuse`) tells LocalStack to spin up real containers for each Lambda invocation — this is what allows your custom image with Tesseract to actually run.

---

## Troubleshooting

- **`tesseract` not found at runtime** — Verify with `docker run --rm <image> tesseract --version`
- **Timeout errors** — Increase `--timeout` and `--memory-size`; OCR can be heavy
- **Push fails** — Ensure ports `4510-4559` are exposed and you're using `localhost.localstack.cloud` (not `localhost`)
- **Install `awslocal`** — `pip install awscli-local` (a thin wrapper around `aws --endpoint-url`)

Fully containerized OCR pipeline using Docker Compose. The Lambda function is **not a running service** — it cold-starts only when a file is uploaded to S3.

Works with **LocalStack Community Edition** (free).

## Architecture

```
 ┌──────────────┐
 │   Browser    │  http://localhost:3000
 │  (HTML/JS)   │
 └──────┬───────┘
        │ POST /api/scan
        ▼
 ┌──────────────┐     ┌─────────────────────────────────────────────┐
 │    Nginx     │────▶│  API Gateway  (Flask :8080)                 │
 │   (:3000)    │     │                                             │
 └──────────────┘     │  1. Upload file to S3                       │
                      │  2. Poll S3 results bucket until done       │
                      │  3. Return OCR text to browser              │
                      └─────────┬───────────────────────────────────┘
                                │ put-object
                                ▼
                      ┌─────────────────────┐
                      │  S3: ocr-uploads    │
                      │    (LocalStack)     │
                      └─────────┬───────────┘
                                │ S3 Event Notification (automatic)
                                ▼
                      ┌─────────────────────┐
                      │  SQS: ocr-jobs      │
                      │    (LocalStack)     │
                      └─────────┬───────────┘
                                │ Event Source Mapping (automatic)
                                ▼
                      ┌─────────────────────────────────────┐
                      │  Lambda: ocr-processor              │
                      │  (cold-starts here, not running)    │
                      │                                     │
                      │  Runtime: python3.11                │
                      │  Image:   ocr-lambda-runtime:latest │
                      │                                     │
                      │  • Downloads file from S3           │
                      │  • Tesseract OCR (images)           │
                      │  • PyMuPDF → Tesseract (PDFs)       │
                      │  • Writes result JSON to S3         │
                      └─────────┬───────────────────────────┘
                                │ put-object
                                ▼
                      ┌─────────────────────┐
                      │  S3: ocr-results    │
                      │    (LocalStack)     │
                      └─────────────────────┘
                                │
                    Gateway polls this ↑ and returns to browser
```

## Quick Start

```bash
docker compose up --build
```

Then open **http://localhost:3000**

## How Lambda Deployment Works (Community Edition)

LocalStack Community does **not** support `--package-type Image` (container image Lambdas — that's Pro only). This project works around it:

1. **`lambda-build`** builds `ocr-lambda-runtime:latest` — a Docker image with Python 3.11, Tesseract OCR, PyMuPDF, and the AWS Lambda Runtime Interface Client.

2. **`LAMBDA_RUNTIME_IMAGE_MAPPING`** in docker-compose tells LocalStack:
   *"When a `python3.11` Lambda is invoked, use `ocr-lambda-runtime:latest` as the execution environment."*
   This is a **free feature** — it replaces the base runtime image, not the deployment method.

3. **`init-aws`** packages the handler as a **zip file** and deploys it with `--runtime python3.11`. This is the standard free deployment method.

4. When a file hits S3, LocalStack starts a container from `ocr-lambda-runtime:latest`, mounts the zip code into it, and runs the handler. Tesseract is available because it's in the runtime image.

```
┌───────────────────────────────────────────────────┐
│  What you'd do in AWS (Pro)                       │
│  --package-type Image --code ImageUri=...         │
│                                                   │
│  What we do instead (Community, free)             │
│  --runtime python3.11 --zip-file fileb://...      │
│  + LAMBDA_RUNTIME_IMAGE_MAPPING for Tesseract     │
└───────────────────────────────────────────────────┘
```

## Services

| Service       | Port | Lifecycle     | Description                                      |
|--------------|------|---------------|--------------------------------------------------|
| `localstack` | 4566 | Always on     | S3 + SQS + Lambda runtime (latest)               |
| `gateway`    | 8080 | Always on     | Flask API (upload + poll for results)             |
| `frontend`   | 3000 | Always on     | Nginx serving HTML                                |
| `lambda-build`| —   | Build & exit  | Builds `ocr-lambda-runtime:latest` image          |
| `init-aws`   | —    | Run & exit    | AWS CLI v2 — zips handler, deploys to LocalStack  |
| Lambda       | —    | **On-demand** | Cold-started by LocalStack on S3 upload           |

## API Endpoints

| Method | Path               | Description                                    |
|--------|-------------------|------------------------------------------------|
| POST   | `/api/scan`        | Upload → wait for Lambda → return OCR text     |
| POST   | `/api/upload`      | Upload to S3 only (async)                      |
| GET    | `/api/result?key=` | Poll for a specific job's result               |
| GET    | `/api/health`      | Health check (S3, SQS, Lambda)                 |
| GET    | `/api/queue`       | SQS queue depth                                |
| GET    | `/api/files`       | List S3 uploads                                |
| GET    | `/api/lambda-status` | Lambda function configuration                |

## Supported File Types

- **Images:** PNG, JPG, JPEG, TIFF, BMP, GIF, WebP
- **PDF:** Multi-page (each page rendered at 300 DPI, then OCR'd)

## Troubleshooting

```bash
# Check all services
curl http://localhost:8080/api/health | python3 -m json.tool

# Check Lambda status
curl http://localhost:8080/api/lambda-status | python3 -m json.tool

# View LocalStack Lambda logs
docker compose logs -f localstack 2>&1 | grep -i lambda

# List S3 contents
aws --endpoint-url=http://localhost:4566 s3 ls s3://ocr-uploads/ --recursive
aws --endpoint-url=http://localhost:4566 s3 ls s3://ocr-results/ --recursive

# Check SQS queue depth
aws --endpoint-url=http://localhost:4566 sqs get-queue-attributes \
    --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ocr-jobs \
    --attribute-names All

# Manually invoke Lambda
aws --endpoint-url=http://localhost:4566 lambda invoke \
    --function-name ocr-processor \
    --payload '{"Records":[{"body":"{\"Records\":[{\"s3\":{\"bucket\":{\"name\":\"ocr-uploads\"},\"object\":{\"key\":\"uploads/test/sample.png\"}}}]}"}]}' \
    /dev/stdout

# View gateway logs
docker compose logs -f gateway

# Rebuild everything from scratch
docker compose down -v && docker compose up --build
```
