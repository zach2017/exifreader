# OCR Document Processor

> **LocalStack + Lambda + FastAPI + Tesseract + PostgreSQL**

A complete serverless-style OCR pipeline running entirely on Docker.
Upload images/PDFs → S3 triggers Lambda → API extracts text via Tesseract → saves to S3 + Postgres.

---

## Architecture

```
┌──────────┐   upload    ┌────────────────────┐   S3 Event    ┌────────────────┐
│  Browser  │ ─────────► │  API Server        │ ◄──────────── │  LocalStack    │
│  (Nginx)  │            │  (FastAPI)         │               │  ┌──────────┐  │
│  :3000    │   /api/*   │  :8000             │   trigger     │  │  Lambda  │  │
└──────────┘ ──proxy──►  │  ┌──────────────┐  │ ◄──────────── │  └──────────┘  │
                         │  │  Tesseract   │  │               │  ┌──────────┐  │
                         │  │  OCR Engine  │  │  get/put obj  │  │    S3    │  │
                         │  └──────────────┘  │ ◄───────────► │  └──────────┘  │
                         └────────┬───────────┘               └────────────────┘
                                  │ save text                        :4566
                                  ▼
                         ┌────────────────────┐
                         │    PostgreSQL       │
                         │    :5432            │
                         │  ┌──────────────┐   │
                         │  │  documents   │   │
                         │  │  proc_log    │   │
                         │  └──────────────┘   │
                         └────────────────────┘
```

## Flow

1. **User uploads** a file via the HTML form (Nginx → API `/upload`)
2. **API Server** stores the file in S3 (`uploads/{doc_id}/filename`) and registers it in Postgres as `pending`
3. **S3 event notification** fires on `uploads/*` prefix → invokes **Lambda**
4. **Lambda** extracts `doc_id` from the S3 key and calls `POST /ocr/process` on the API server
5. **API Server** downloads the file from S3, runs **Tesseract OCR**, then:
   - Saves extracted text to S3 (`text/{doc_id}/extracted.txt`)
   - Updates Postgres with text, word count, page count, status
6. **User** sees results in the document list and can view extracted text

## Quick Start

```bash
# Clone and start everything
cd ocr-solution
docker compose up --build -d

# Wait ~30s for LocalStack to initialize, then open:
#   Frontend: http://localhost:3000
#   API Docs: http://localhost:8000/docs
```

## Services

| Service      | Port  | Description                           |
|-------------|-------|---------------------------------------|
| `frontend`  | 3000  | Nginx serving HTML + proxying API     |
| `api-server`| 8000  | FastAPI + Tesseract OCR engine        |
| `localstack`| 4566  | S3 bucket + Lambda function           |
| `postgres`  | 5432  | Document metadata + extracted text    |

## Configuration

All services use environment variables from `.env`:

| Variable                | Default                                  |
|------------------------|------------------------------------------|
| `AWS_REGION`           | `us-east-1`                              |
| `AWS_ACCESS_KEY_ID`    | `test`                                   |
| `AWS_SECRET_ACCESS_KEY`| `test`                                   |
| `S3_ENDPOINT`          | `http://localstack:4566`                 |
| `S3_BUCKET`            | `ocr-documents`                          |
| `POSTGRES_HOST`        | `postgres`                               |
| `POSTGRES_PORT`        | `5432`                                   |
| `POSTGRES_DB`          | `ocr_db`                                 |
| `POSTGRES_USER`        | `ocruser`                                |
| `POSTGRES_PASSWORD`    | `ocrpass123`                             |
| `API_BASE_URL`         | `http://api-server:8000`                 |

## Database Schema

**`documents`** — main storage table:
- `doc_id` (UUID) — unique document identifier
- `original_filename`, `content_type`, `file_size_bytes`
- `s3_key_original` / `s3_key_text` — S3 locations
- `extracted_text` — full OCR output
- `ocr_status` — `pending` → `processing` → `completed` / `failed`
- `page_count`, `word_count`
- timestamps: `created_at`, `updated_at`, `processed_at`

**`processing_log`** — audit trail of every processing stage

## API Endpoints

| Method | Endpoint                  | Description                  |
|--------|--------------------------|------------------------------|
| POST   | `/upload`                | Upload a document            |
| POST   | `/ocr/process`           | Trigger OCR (called by Lambda) |
| GET    | `/documents`             | List all documents           |
| GET    | `/documents/{doc_id}`    | Get document details + text  |
| GET    | `/documents/{doc_id}/text` | Get extracted text only    |
| GET    | `/health`                | Health check + Tesseract ver |

## Supported File Types

- **Images**: PNG, JPG, JPEG, TIFF, BMP, GIF, WebP
- **Documents**: PDF (converted to images at 300 DPI, then OCR'd per page)
