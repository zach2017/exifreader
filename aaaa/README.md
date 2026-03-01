# OCR Image Pipeline — LocalStack + Go Lambda + Tesseract

A fully containerized OCR pipeline using LocalStack for AWS service emulation, a Go Lambda function with Tesseract OCR, and Playwright for E2E testing.

## Architecture

```
┌──────────┐     ┌─────────────┐     ┌─────────────────────┐     ┌──────────┐
│ Web Form │────▶│ S3 (uploads)│────▶│ Lambda (Go+Tesseract)│────▶│ S3 (output)│
│ :8080    │     │             │     │                     │     │ .txt files │
└──────────┘     └─────────────┘     └──────────┬──────────┘     └────────────┘
                                                │
                                                ▼
                                          ┌──────────┐
                                          │   SQS    │
                                          │ messages │
                                          └──────────┘
```

**Flow:**
1. User uploads an image via the web form (or directly to S3)
2. S3 event notification triggers the Lambda function
3. Lambda downloads the image, runs Tesseract OCR
4. **If text is found:** uploads `{name}.txt` to output bucket + sends SQS message
5. **If no text:** does nothing (no file, no message)

## Services

| Service         | Port  | Description                           |
|-----------------|-------|---------------------------------------|
| `localstack`    | 4566  | S3, SQS, Lambda emulation            |
| `web`           | 8080  | HTML upload form (Nginx)              |
| `lambda-builder`| —     | Builds the Go+Tesseract Docker image  |
| `setup`         | —     | Creates AWS resources in LocalStack   |
| `tests`         | —     | Playwright E2E test suite             |

## Quick Start

```bash
# Start all services
docker compose up --build -d

# Wait for setup to complete
docker compose logs -f setup

# Open the web UI
open http://localhost:8080

# Run tests
docker compose run --rm tests
```

## Running Tests

### Go Unit Tests (Lambda)

```bash
cd lambda
go test -v ./...
```

### Playwright E2E Tests

```bash
docker compose run --rm tests
```

Tests verify:
- Web form loads with correct UI elements
- File selection/removal behavior
- Image upload triggers OCR pipeline
- Text images produce `.txt` output + SQS message
- Blank images produce no output and no message
- Non-image files are ignored
- Multiple image formats (PNG, JPEG) are supported

## Project Structure

```
├── docker-compose.yml          # All services
├── lambda/
│   ├── Dockerfile              # Go build + Tesseract runtime
│   ├── main.go                 # Lambda handler (S3 → OCR → S3 + SQS)
│   ├── main_test.go            # Unit tests with mocked AWS clients
│   └── go.mod
├── web/
│   ├── Dockerfile              # Nginx
│   ├── index.html              # Upload form
│   └── nginx.conf
├── scripts/
│   └── setup-aws.sh            # Creates buckets, queue, lambda, triggers
├── tests/
│   ├── Dockerfile              # Playwright + AWS CLI + ImageMagick
│   ├── playwright.config.ts
│   ├── specs/
│   │   └── ocr-pipeline.spec.ts
│   └── helpers/
│       └── aws-helpers.ts      # S3/SQS utilities for tests
└── README.md
```
