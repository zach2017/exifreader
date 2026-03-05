# PDF → Image Extractor (LocalStack + S3 + SQS + PyMuPDF)

A containerized solution that extracts individual pages from uploaded PDFs as high-resolution PNG images, stores them in S3, and publishes per-page processing events to SQS — all running locally via LocalStack.

## Architecture

```
┌─────────────┐       POST /api/upload        ┌──────────────────┐
│   Browser    │ ──────────────────────────▶   │  Flask API       │
│   (Nginx)    │                               │  + PyMuPDF       │
│   :3000      │  ◀── JSON results ──────────  │  :8000           │
└─────────────┘                               └──────┬───┬───────┘
                                                      │   │
                                         page images  │   │  messages
                                                      ▼   ▼
                                              ┌───────────────────┐
                                              │   LocalStack      │
                                              │   :4566           │
                                              │                   │
                                              │  ┌─────┐ ┌─────┐ │
                                              │  │ S3  │ │ SQS │ │
                                              │  └─────┘ └─────┘ │
                                              └───────────────────┘
```

## Services

| Service     | Port   | Description                              |
|-------------|--------|------------------------------------------|
| Frontend    | `3000` | Nginx serving HTML UI + API proxy        |
| API Server  | `8000` | Flask + PyMuPDF PDF processing           |
| LocalStack  | `4566` | S3 bucket (`pdf-images`) + SQS queue     |

## Quick Start

```bash
# Clone / enter project directory
cd project

# Make init script executable
chmod +x scripts/init-aws.sh

# Start everything
docker compose up --build -d

# Open the UI
open http://localhost:3000
```

## How It Works

1. **Upload** a PDF via the web UI (drag & drop or file picker)
2. **API server** receives the file and opens it with PyMuPDF
3. **Each page** is rendered to a PNG image at 200 DPI
4. **Images are uploaded** to S3 under `documents/{doc_id}/{name}/page_NNNN.png`
5. **An SQS message** is published per page containing:
   ```json
   {
     "document_id": "a1b2c3d4e5f6",
     "document_name": "report.pdf",
     "page_number": 1,
     "total_pages": 10,
     "s3_bucket": "pdf-images",
     "s3_key": "documents/a1b2c3d4e5f6/report/page_0001.png",
     "s3_uri": "s3://pdf-images/documents/a1b2c3d4e5f6/report/page_0001.png",
     "image_size_bytes": 245760,
     "dpi": 200,
     "timestamp": "2026-03-05T12:00:00+00:00"
   }
   ```
6. **UI shows** results table with S3 keys, sizes, image previews, and SQS messages

## API Endpoints

| Method | Endpoint                    | Description                        |
|--------|-----------------------------|------------------------------------|
| POST   | `/api/upload`               | Upload PDF, extract pages          |
| GET    | `/api/s3/list`              | List objects in S3 bucket          |
| GET    | `/api/s3/image/<s3_key>`    | Proxy/preview an image from S3     |
| GET    | `/api/queue/stats`          | Get SQS queue statistics           |
| GET    | `/api/queue/messages`       | Peek at SQS messages               |
| GET    | `/health`                   | Health check                       |

## Configuration (Environment Variables)

| Variable          | Default                          | Description           |
|-------------------|----------------------------------|-----------------------|
| `S3_ENDPOINT`     | `http://localstack:4566`         | S3 endpoint URL       |
| `SQS_ENDPOINT`    | `http://localstack:4566`         | SQS endpoint URL      |
| `S3_BUCKET`       | `pdf-images`                     | Target S3 bucket      |
| `RENDER_DPI`      | `200`                            | Image render quality  |

## Verifying with AWS CLI

```bash
# List S3 objects
aws --endpoint-url=http://localhost:4566 s3 ls s3://pdf-images/ --recursive

# Read SQS messages
aws --endpoint-url=http://localhost:4566 sqs receive-message \
  --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/pdf-processing

# Queue attributes
aws --endpoint-url=http://localhost:4566 sqs get-queue-attributes \
  --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/pdf-processing \
  --attribute-names All
```

## Cleanup

```bash
docker compose down -v
```
