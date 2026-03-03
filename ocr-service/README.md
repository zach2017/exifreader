# OCR Document Processing Pipeline

A microservices-based document processing system built with Go, Docker Compose, and LocalStack (S3 + SQS).

## Architecture

```
┌─────────────────┐       ┌──────────────┐       ┌─────────────────────┐
│   Upload Form   │──────▶│  S3: uploads │       │  SQS: file-processing│
│  (localhost:8080)│       └──────────────┘       └──────────┬──────────┘
│                 │──────────────────────────────────────────▶│
└─────────────────┘                                          │
                                                             ▼
                                                ┌────────────────────────┐
                                                │  Text Extract Service  │
                                                │                        │
                                                │  PDF  → pdftotext      │
                                                │  Word → pandoc/antiword│
                                                │  RTF  → unrtf/pandoc   │
                                                │  Image→ send to OCR    │
                                                └────────┬───────────────┘
                                                         │
                              ┌───────────────────┬──────┴──────────┐
                              │                   │                 │
                              ▼                   ▼                 ▼
                    ┌──────────────────┐  ┌──────────────┐  ┌───────────────────┐
                    │ S3: extracted-text│  │ S3: tmp-files│  │ SQS: ocr-processing│
                    │ (.txt files)     │  │ (PDF images) │  └────────┬──────────┘
                    └──────────────────┘  └──────────────┘           │
                                                                     ▼
                                                          ┌──────────────────┐
                                                          │   OCR Service    │
                                                          │   (Tesseract)    │
                                                          └────────┬─────────┘
                                                                   │
                                                    ┌──────────────┴──────────────┐
                                                    ▼                             ▼
                                          ┌──────────────────────┐  ┌───────────────────┐
                                          │S3: tmp-extracted-text│  │ SQS: ocr-complete │
                                          │ (OCR .txt files)     │  └───────────────────┘
                                          └──────────────────────┘
```

## Services

### 1. Upload Service (port 8080)
- Serves HTML drag-and-drop upload form
- Uploads files to S3 `uploads` bucket
- Sends `file_uploaded` message to SQS `file-processing` queue

### 2. Text Extract Service
- Polls `file-processing` SQS queue
- **PDF files**: Extracts text via `pdftotext` → saves to `extracted-text` bucket, extracts embedded images via `pdfimages` → uploads to `tmp-files` bucket → sends `ocr_needed` for each image
- **Word files** (.doc/.docx): Extracts text via `pandoc`/`antiword` → saves to `extracted-text` bucket
- **RTF files**: Extracts text via `unrtf`/`pandoc` → saves to `extracted-text` bucket
- **Image files**: Sends `ocr_needed` message to `ocr-processing` queue

### 3. OCR Service
- Polls `ocr-processing` SQS queue
- Downloads image from S3
- Runs Tesseract OCR (eng language, 300 DPI for PDFs)
- Saves extracted text to `tmp-extracted-text` bucket
- Sends `ocr_complete` message to `ocr-complete` queue

## S3 Buckets

| Bucket | Purpose |
|--------|---------|
| `uploads` | Original uploaded files |
| `extracted-text` | Text extracted from PDF/Word/RTF |
| `tmp-files` | Intermediate files (images from PDFs) |
| `tmp-extracted-text` | OCR-extracted text from images |

## SQS Queues

| Queue | Message Types |
|-------|--------------|
| `file-processing` | `file_uploaded` |
| `ocr-processing` | `ocr_needed` |
| `ocr-complete` | `ocr_complete` |

## Message Formats

### file_uploaded
```json
{
  "type": "file_uploaded",
  "document_id": "uuid",
  "filename": "report.pdf",
  "content_type": "application/pdf",
  "s3_key": "uuid/uuid.pdf",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### ocr_needed
```json
{
  "type": "ocr_needed",
  "document_id": "uuid",
  "document_type": "png",
  "s3_bucket": "uploads",
  "s3_key": "uuid/uuid.png",
  "image_index": 0,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### ocr_complete
```json
{
  "type": "ocr_complete",
  "document_id": "uuid",
  "s3_bucket": "tmp-extracted-text",
  "s3_key": "uuid.txt",
  "image_index": 0,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

## Quick Start

```bash
# Start everything
make up

# Open browser
open http://localhost:8080

# Watch logs
make logs

# Check results
make list-extracted
make list-ocr
```

## Useful Commands

```bash
make up              # Build and start all services
make down            # Stop and remove containers + volumes
make logs            # Follow all service logs
make logs-extract    # Follow text-extract service logs
make logs-ocr        # Follow OCR service logs
make list-buckets    # List all S3 buckets
make list-extracted  # List files in extracted-text bucket
make list-ocr        # List files in tmp-extracted-text bucket
make check-queues    # Show SQS queue depths

# Get extracted text for a document
make get-text DOC_ID=<your-uuid>
make get-ocr-text DOC_ID=<your-uuid>
```

## Processing Flow Examples

### PDF Upload
1. File uploaded to `s3://uploads/{docId}/{docId}.pdf`
2. Text Extract Service: `pdftotext` → `s3://extracted-text/{docId}.txt`
3. Text Extract Service: `pdfimages` → `s3://tmp-files/{docId}/image-001.png`
4. OCR Service: `tesseract` → `s3://tmp-extracted-text/{docId}-image-001.txt`
5. `ocr_complete` sent to SQS

### Image Upload (PNG/JPEG)
1. File uploaded to `s3://uploads/{docId}/{docId}.png`
2. Text Extract Service sends `ocr_needed` to SQS
3. OCR Service: `tesseract` → `s3://tmp-extracted-text/{docId}.txt`
4. `ocr_complete` sent to SQS

### Word/RTF Upload
1. File uploaded to `s3://uploads/{docId}/{docId}.docx`
2. Text Extract Service: `pandoc` → `s3://extracted-text/{docId}.txt`

## Requirements
- Docker & Docker Compose
- AWS CLI (optional, for inspection commands)
