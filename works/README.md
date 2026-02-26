# OCR Document Processor

> **LocalStack + Lambda + FastAPI + Tesseract + PostgreSQL**

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

## Quick Start

```bash
docker compose up --build -d

# Wait ~30s for LocalStack init, then open:
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

## Startup Order

```
postgres (healthy) → api-server (healthy) → localstack (runs init-aws.sh) → frontend
```

LocalStack depends on `api-server` being healthy so that the Lambda function
can reach the API server when triggered by S3 events.

## Configuration

All services use `.env` environment variables:

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

**`documents`** table:
- `doc_id` (UUID, unique) — document identifier
- `original_filename`, `content_type`, `file_size_bytes`
- `s3_key_original` / `s3_key_text` — S3 locations
- `extracted_text` — full OCR output
- `ocr_status` — `pending` → `processing` → `completed` / `failed` (CHECK constraint)
- `page_count`, `word_count`
- `created_at`, `updated_at` (auto-trigger), `processed_at`

**`processing_log`** table — audit trail with FK to documents

## API Endpoints

| Method | Endpoint                  | Description                  |
|--------|--------------------------|------------------------------|
| GET    | `/health`                | Health check + connectivity  |
| POST   | `/upload`                | Upload a document            |
| POST   | `/ocr/process`           | Trigger OCR (called by Lambda) |
| GET    | `/documents`             | List all documents           |
| GET    | `/documents/{doc_id}`    | Full document details + text |
| GET    | `/documents/{doc_id}/text` | Extracted text only        |

## Testing

The project includes a comprehensive pytest test suite covering S3 operations,
OCR logic, Lambda handler, API endpoints, and database schema.

### Run tests in Docker (recommended)

```bash
./run-tests.sh docker
# or
docker compose -f docker-compose.test.yml up --abort-on-container-exit --exit-code-from test-runner
```

### Run unit tests only (no Postgres needed)

```bash
./run-tests.sh unit
```

### Run all tests locally

```bash
pip install -r tests/requirements.txt
./run-tests.sh local
```

### Test coverage

| File              | Tests                                          |
|-------------------|------------------------------------------------|
| `test_s3.py`      | Bucket creation, object CRUD, roundtrips       |
| `test_ocr.py`     | Tesseract image OCR, file types, edge cases    |
| `test_lambda.py`  | Event parsing, doc_id extraction, error handling|
| `test_api.py`     | All API endpoints, upload→process→verify cycle |
| `test_database.py`| Schema validation, CRUD, constraints, triggers |

## S3 Bucket Verification

The LocalStack init script (`localstack-init/ready.d/init-aws.sh`) performs:

1. Waits for S3 + Lambda services via health endpoint
2. Creates the S3 bucket (handles `us-east-1` vs other regions)
3. **Verifies** with write → read → delete roundtrip test
4. Packages and deploys the Lambda function
5. Waits for Lambda to reach Active state + smoke test invoke
6. Configures S3 → Lambda event notification
7. Verifies notification is active

The API server also has `ensure_bucket_exists()` with retry logic (10 attempts,
3s delay) on startup in case LocalStack isn't ready yet.
