# OCR Pipeline — LocalStack + Go Lambda + Tesseract

## Architecture

```
Browser ──► S3 (ocr-uploads) ──► Lambda (Go+Tesseract) ──► S3 (ocr-output)
  ▲                                       │                      │
  │                                       ▼                      │
  │                                   SQS (ocr-results)          │
  │                                                              │
  └──────── polls .txt file ◄────────────────────────────────────┘
  └──────── polls SQS messages
```

## Quick Start

```bash
# 1) Build Lambda binary
make build

# 2) Start services (LocalStack auto-runs setup script)
make up

# 3) Open browser
open http://localhost:8080

# 4) Run tests
make test
```

## How It Works

1. **Build step** compiles Go binary → `lambda/dist/function.zip`
2. **LocalStack starts**, auto-runs `scripts/setup-aws.sh` via init hooks
3. Setup creates: S3 buckets, SQS queue, Lambda function (with real binary), S3→Lambda trigger
4. **Upload an image** via the web form or directly to `s3://ocr-uploads/`
5. Lambda downloads image, runs Tesseract OCR
6. **If text found**: uploads `.txt` to `ocr-output`, sends SQS message
7. **If no text**: nothing happens (no file, no message)
8. **Web UI** polls S3 for the `.txt` file and SQS for the notification message

## Key Fixes vs Common Pitfalls

- Lambda uses `provided.al2023` runtime with actual Go binary (not a Docker image)
- `AWS_ENDPOINT_URL=http://host.docker.internal:4566` for Lambda→LocalStack communication
- Setup runs inside LocalStack using `awslocal` (no external AWS CLI needed)
- S3 notifications use JSON format via `put-bucket-notification-configuration`
- Both S3 buckets have CORS configured for browser access
- Tests use pure HTTP fetch (no AWS CLI dependency)
