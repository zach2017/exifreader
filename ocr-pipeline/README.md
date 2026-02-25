# Tesseract OCR Pipeline — LocalStack + S3 + SQS + Lambda

A fully containerized OCR pipeline using Docker Compose with LocalStack (S3 + SQS),
a Tesseract-based Lambda function, and a polished HTML frontend.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser  (http://localhost:3000)                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  HTML + Tailwind CSS + JavaScript                         │  │
│  │  Upload file → Display OCR results                        │  │
│  └─────────────────────┬─────────────────────────────────────┘  │
└────────────────────────┼────────────────────────────────────────┘
                         │ POST /api/scan
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Nginx Reverse Proxy  (port 3000)                               │
│  Static files + /api/ → gateway:8080                            │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  API Gateway  (Flask, port 8080)                                │
│                                                                 │
│  1. Upload file ──────────────► S3 Bucket (ocr-uploads)         │
│  2. Send job message ─────────► SQS Queue (ocr-jobs)            │
│  3. Consume SQS message                                        │
│  4. Fetch file from S3                                          │
│  5. Invoke Lambda ────────────► OCR Lambda (port 9000)          │
│  6. Return OCR text to browser                                  │
└─────────────────────────────────────────────────────────────────┘
                          │                    │
                          ▼                    ▼
┌───────────────────────────────┐  ┌──────────────────────────────┐
│  LocalStack  (port 4566)      │  │  OCR Lambda  (port 9000)     │
│                               │  │                              │
│  • S3 bucket: ocr-uploads     │  │  • Tesseract OCR (images)    │
│  • SQS queue: ocr-jobs        │  │  • PyMuPDF → Tesseract (PDF) │
│  • S3 → SQS event notify     │  │  • Flask invoke endpoint     │
└───────────────────────────────┘  └──────────────────────────────┘
```

## Quick Start

```bash
# Clone / navigate to the project directory
cd project

# Build and start all services
docker compose up --build

# Open the UI
open http://localhost:3000
```

The init script automatically creates the S3 bucket, SQS queue, and wires
S3 event notifications to SQS on startup.

## Services

| Service      | Port  | Description                              |
|-------------|-------|------------------------------------------|
| `frontend`  | 3000  | Nginx serving HTML + proxying `/api/`    |
| `gateway`   | 8080  | Flask API bridging S3, SQS, and Lambda   |
| `ocr-lambda`| 9000  | Tesseract OCR service (image + PDF)      |
| `localstack`| 4566  | S3 + SQS (with event notifications)      |

## API Endpoints

| Method | Path           | Description                                     |
|--------|---------------|-------------------------------------------------|
| POST   | `/api/scan`    | One-shot: upload → S3 → SQS → Lambda → result  |
| POST   | `/api/upload`  | Upload file to S3 + enqueue SQS message         |
| POST   | `/api/process` | Read SQS → fetch S3 → invoke Lambda             |
| GET    | `/api/health`  | Health check for all services                    |
| GET    | `/api/queue`   | SQS queue depth                                  |
| GET    | `/api/files`   | List S3 uploads                                  |

## Supported File Types

- **Images**: PNG, JPG, JPEG, TIFF, BMP, GIF, WebP
- **PDF**: Multi-page PDFs (each page rendered at 300 DPI then OCR'd)

## Pipeline Flow

1. **Upload** — File sent from browser to Gateway
2. **S3 Store** — Gateway stores file in `s3://ocr-uploads/uploads/{job_id}/{filename}`
3. **SQS Enqueue** — Job message sent to `ocr-jobs` queue
4. **SQS Consume** — Gateway reads the job message back
5. **S3 Fetch** — Gateway retrieves the file from S3
6. **Lambda Invoke** — File sent (base64) to the OCR Lambda
7. **OCR** — Tesseract extracts text (or PyMuPDF renders PDF pages first)
8. **Return** — Extracted text + timing metrics returned to browser

## Troubleshooting

```bash
# Check service health
curl http://localhost:8080/api/health

# List S3 bucket contents
aws --endpoint-url=http://localhost:4566 s3 ls s3://ocr-uploads/ --recursive

# Check SQS queue depth
aws --endpoint-url=http://localhost:4566 sqs get-queue-attributes \
    --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ocr-jobs \
    --attribute-names All

# View logs
docker compose logs -f gateway
docker compose logs -f ocr-lambda
```
