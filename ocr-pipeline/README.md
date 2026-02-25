# Tesseract OCR — Event-Driven Pipeline

Fully containerized OCR pipeline using Docker Compose. The Lambda function is **not a running service** — it cold-starts only when a file is uploaded to S3.

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
                      │  (Docker image, cold-starts here)   │
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

**Key point:** There is no always-running Lambda container. LocalStack manages the Lambda lifecycle — it starts the container when an SQS message arrives and stops it after execution.

## Quick Start

```bash
docker compose up --build
```

Then open **http://localhost:3000**

The `init-aws` container (built with **AWS CLI v2**) automatically:
- Creates S3 buckets (`ocr-uploads`, `ocr-results`)
- Creates the SQS queue (`ocr-jobs`)
- Deploys the Lambda function from the `ocr-lambda:latest` Docker image
- Wires S3 → SQS event notification
- Wires SQS → Lambda event source mapping
- Runs a verification step to confirm all resources are live

## Services

| Service       | Port | Lifecycle     | Description                            |
|--------------|------|---------------|----------------------------------------|
| `localstack` | 4566 | Always on     | S3 + SQS + Lambda runtime (latest)    |
| `gateway`    | 8080 | Always on     | Flask API (upload + poll for results)  |
| `frontend`   | 3000 | Always on     | Nginx serving HTML                     |
| `lambda-build`| —   | Build & exit  | Builds the `ocr-lambda:latest` image   |
| `init-aws`   | —    | Run & exit    | AWS CLI v2 — deploys resources         |
| Lambda container | — | **On-demand** | Started by LocalStack, not by Compose  |

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

# Check Lambda state
curl http://localhost:8080/api/lambda-status | python3 -m json.tool

# View Lambda logs (LocalStack manages the container)
docker compose logs -f localstack | grep -i lambda

# List S3 contents
aws --endpoint-url=http://localhost:4566 s3 ls s3://ocr-uploads/ --recursive
aws --endpoint-url=http://localhost:4566 s3 ls s3://ocr-results/ --recursive

# Manually invoke Lambda for testing
aws --endpoint-url=http://localhost:4566 lambda invoke \
    --function-name ocr-processor \
    --payload '{"Records":[{"body":"{\"Records\":[{\"s3\":{\"bucket\":{\"name\":\"ocr-uploads\"},\"object\":{\"key\":\"uploads/test/sample.png\"}}}]}"}]}' \
    /dev/stdout

# Check SQS
aws --endpoint-url=http://localhost:4566 sqs get-queue-attributes \
    --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ocr-jobs \
    --attribute-names All

# View gateway logs
docker compose logs -f gateway
```

## How the Cold Start Works

1. You upload a file via the browser
2. Gateway PUTs the file into `s3://ocr-uploads/uploads/{job_id}/{filename}`
3. S3 automatically sends an event notification to the `ocr-jobs` SQS queue
4. The SQS → Lambda event source mapping triggers the `ocr-processor` function
5. **LocalStack starts the `ocr-lambda:latest` Docker container** (cold start)
6. Lambda downloads the file from S3, runs Tesseract, writes result to `s3://ocr-results/`
7. **Container stops after execution**
8. Gateway polls `s3://ocr-results/` and returns the OCR text to the browser
