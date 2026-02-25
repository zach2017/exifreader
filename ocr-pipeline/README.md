# Tesseract OCR — Event-Driven Pipeline

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
