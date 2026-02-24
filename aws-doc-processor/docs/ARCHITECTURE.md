# AWS Document Processing Pipeline — Architecture & Tutorial

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Component Deep Dive](#component-deep-dive)
4. [Data Flow](#data-flow)
5. [Best Practices for Long-Running Processes](#best-practices)
6. [LocalStack Development Guide](#localstack-guide)
7. [Deployment Guide](#deployment-guide)
8. [Troubleshooting](#troubleshooting)

---

## 1. System Overview

This system is a **serverless document processing pipeline** that accepts file uploads (PDF, Word, Images, Text), extracts text content using OCR and text extraction, stores results in S3, indexes them in Elasticsearch, and provides a searchable web interface.

### Key Technologies

| Component            | Technology                          | Purpose                                    |
|----------------------|-------------------------------------|--------------------------------------------|
| Frontend             | HTML/CSS/JS (Vanilla)               | File upload & search UI                    |
| Object Storage       | AWS S3                              | Store original + processed files           |
| Message Queue        | AWS SQS                             | Decouple processing stages                 |
| Compute              | AWS Lambda                          | File routing, text extraction, OCR         |
| Orchestration        | AWS Step Functions                  | Multi-step PDF processing                  |
| Database             | AWS DynamoDB                        | File metadata & relationships              |
| Search               | Elasticsearch (OpenSearch)          | Full-text search across extracted content  |
| Local Dev            | LocalStack + Docker Compose         | Local AWS emulation                        |
| CI/CD                | GitHub Actions                      | Automated testing & deployment             |

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        HTML FRONTEND                                     │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────┐                     │
│  │  Upload   │  │  File List   │  │  Search Bar    │                     │
│  │  Widget   │  │  (Table)     │  │  (Elastic)     │                     │
│  └─────┬─────┘  └──────┬───────┘  └───────┬────────┘                     │
└────────┼───────────────┼──────────────────┼──────────────────────────────┘
         │               │                  │
         ▼               ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         AWS API GATEWAY                                  │
│  POST /upload     GET /files      GET /search                           │
└────────┬───────────────┬──────────────────┬──────────────────────────────┘
         │               │                  │
         ▼               │                  ▼
┌──────────────┐         │         ┌──────────────────┐
│   S3 Bucket  │         │         │  Elasticsearch   │
│  (uploads)   │         │         │  (OpenSearch)     │
└──────┬───────┘         │         └──────────────────┘
       │                 │
       │ S3 Event        │ DynamoDB Query
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ SQS Queue    │  │  DynamoDB    │
│ (file-router)│  │  (metadata)  │
└──────┬───────┘  └──────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│            LAMBDA: File Router                        │
│                                                      │
│  Inspects file type → routes to correct pipeline:    │
│                                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐ │
│  │  PDF    │  │  WORD   │  │  IMAGE  │  │  OTHER │ │
│  └────┬────┘  └────┬────┘  └────┬────┘  └───┬────┘ │
└───────┼────────────┼────────────┼────────────┼───────┘
        │            │            │            │
        ▼            │            │            │
┌───────────────┐    │            │            │
│ Step Function │    │            │            │
│ (PDF Pipeline)│    │            │            │
│               │    │            │            │
│ 1. Extract    │    │            │            │
│    images→S3  │    │            │            │
│ 2. SQS: needs │    │            │            │
│    OCR images │    │            │            │
│ 3. SQS: needs │    │            │            │
│    text extract│   │            │            │
└───────┬───────┘    │            │            │
        │            │            │            │
        ▼            ▼            │            ▼
┌───────────────────────────┐     │   ┌────────────────────┐
│ SQS: text-extract-queue   │     │   │ SQS: text-extract  │
│                           │     │   │ (for non-text)     │
│ Triggers Lambda:          │     │   └─────────┬──────────┘
│ Text Extractor            │     │             │
└───────────┬───────────────┘     │             │
            │                     │             │
            ▼                     ▼             │
┌───────────────────┐  ┌──────────────────┐     │
│ Lambda:           │  │ SQS: ocr-queue   │     │
│ Text Extractor    │  │                  │     │
│                   │  │ Triggers Lambda: │     │
│ - PDF text layer  │  │ OCR Extractor    │     │
│ - DOCX parsing    │  └────────┬─────────┘     │
│ - Other formats   │           │               │
└─────────┬─────────┘           ▼               │
          │            ┌──────────────────┐      │
          │            │ Lambda:          │      │
          │            │ OCR Extractor    │      │
          │            │                  │      │
          │            │ - Tesseract OCR  │      │
          │            │ - Image→Text     │      │
          │            └────────┬─────────┘      │
          │                     │                │
          ▼                     ▼                ▼
┌─────────────────────────────────────────────────────┐
│                 RESULTS PIPELINE                     │
│                                                      │
│  1. Store extracted .txt → S3                        │
│  2. Update DynamoDB metadata (links to all files)    │
│  3. Index text content → Elasticsearch               │
└─────────────────────────────────────────────────────┘
```

---

## 3. Component Deep Dive

### 3.1 Frontend (HTML/JS)

The frontend is a single-page application with three main features:

- **Upload**: Drag-and-drop or file picker → POST to API Gateway → S3
- **File List**: Table showing all uploaded files with status, extracted files, view/download
- **Search**: Full-text search powered by Elasticsearch

The frontend communicates with the backend exclusively through API Gateway endpoints.

### 3.2 S3 Buckets

Two logical prefixes in one bucket:

| Prefix       | Purpose                                      |
|--------------|----------------------------------------------|
| `uploads/`   | Original uploaded files                      |
| `extracted/` | Extracted text files, images from PDFs       |
| `processed/` | Final processed/converted files              |

**S3 Event Notification**: On `s3:ObjectCreated:*` under `uploads/`, sends message to `file-router-queue`.

### 3.3 SQS Queues

| Queue Name              | Purpose                                          | Consumer              |
|-------------------------|--------------------------------------------------|-----------------------|
| `file-router-queue`     | New file uploaded → route by type                | Lambda: File Router   |
| `text-extract-queue`    | File needs text extraction (PDF, DOCX, etc.)     | Lambda: Text Extractor|
| `ocr-queue`             | Image needs OCR text extraction                  | Lambda: OCR Extractor |

Each queue has a **Dead Letter Queue (DLQ)** for failed messages after 3 retries.

### 3.4 Lambda Functions

#### File Router Lambda
- **Trigger**: `file-router-queue` (SQS)
- **Logic**: 
  1. Read file metadata from S3
  2. Determine file type (PDF, DOCX, image, text, other)
  3. For PDF → Start Step Function execution
  4. For DOCX/other docs → Send to `text-extract-queue`
  5. For images → Send to `ocr-queue`
  6. For plain text → Store directly, update DynamoDB
  7. Create initial DynamoDB record

#### Text Extractor Lambda
- **Trigger**: `text-extract-queue` (SQS)
- **Logic**:
  1. Download file from S3
  2. Extract text based on format:
     - PDF: Use `pdftotext` (poppler) for text layer
     - DOCX: Parse XML content with `python-docx`
     - Other: Use `textract` or format-specific libraries
  3. Save extracted `.txt` to S3 `extracted/` prefix
  4. Update DynamoDB with extracted file link
  5. Index text in Elasticsearch

#### OCR Extractor Lambda
- **Trigger**: `ocr-queue` (SQS)
- **Logic**:
  1. Download image from S3
  2. Run Tesseract OCR
  3. Save extracted `.txt` to S3 `extracted/` prefix
  4. Update DynamoDB with extracted file link
  5. Index text in Elasticsearch

### 3.5 Step Functions (PDF Pipeline)

The PDF pipeline is a state machine because PDFs require multi-step processing:

```
StartState
    │
    ▼
ExtractImagesFromPDF ──── Save images to S3
    │
    ▼
ParallelProcessing
    ├── SendOCRMessages ──── For each extracted image → SQS ocr-queue
    └── SendTextExtract ──── For text layer → SQS text-extract-queue
    │
    ▼
UpdateMetadata ──── Update DynamoDB with all extracted file links
    │
    ▼
EndState
```

### 3.6 DynamoDB Schema

**Table: `document-metadata`**

| Attribute          | Type   | Description                              |
|--------------------|--------|------------------------------------------|
| `file_id` (PK)    | String | UUID for the upload                      |
| `original_key`     | String | S3 key of original file                  |
| `filename`         | String | Original filename                        |
| `file_type`        | String | MIME type                                |
| `file_size`        | Number | Size in bytes                            |
| `upload_time`      | String | ISO 8601 timestamp                       |
| `status`           | String | PENDING / PROCESSING / COMPLETED / ERROR |
| `extracted_files`  | List   | List of S3 keys for extracted content    |
| `extracted_text_key`| String| S3 key for the main extracted text file  |
| `processing_steps` | List   | Audit trail of processing steps          |

### 3.7 Elasticsearch Index

**Index: `documents`**

```json
{
  "mappings": {
    "properties": {
      "file_id":        { "type": "keyword" },
      "filename":       { "type": "text" },
      "content":        { "type": "text", "analyzer": "standard" },
      "file_type":      { "type": "keyword" },
      "upload_time":    { "type": "date" },
      "s3_key":         { "type": "keyword" },
      "extracted_from": { "type": "keyword" }
    }
  }
}
```

---

## 4. Data Flow — Complete Walkthrough

### Scenario: User Uploads a PDF

1. **User** drags `report.pdf` into the frontend upload widget
2. **Frontend** sends `POST /upload` with the file → **API Gateway** → **S3** `uploads/abc-123/report.pdf`
3. **S3 Event** fires → message sent to **`file-router-queue`**
4. **File Router Lambda** picks up message:
   - Reads `report.pdf` metadata
   - Detects: `application/pdf`
   - Creates DynamoDB record: `{ file_id: "abc-123", status: "PROCESSING" }`
   - Starts **Step Function** execution with `{ file_id, s3_key }`
5. **Step Function** executes:
   - **Step 1 — ExtractImages**: Downloads PDF, extracts 3 embedded images, saves to `extracted/abc-123/img-1.png`, `img-2.png`, `img-3.png`
   - **Step 2a — SendOCRMessages**: Sends 3 messages to `ocr-queue` (one per image)
   - **Step 2b — SendTextExtract**: Sends 1 message to `text-extract-queue` for the PDF text layer
6. **Text Extractor Lambda** processes the PDF:
   - Extracts text layer → saves `extracted/abc-123/report.txt`
   - Updates DynamoDB, indexes in Elasticsearch
7. **OCR Extractor Lambda** processes each image (3 invocations):
   - Runs Tesseract → saves `extracted/abc-123/img-1-ocr.txt`, etc.
   - Updates DynamoDB, indexes in Elasticsearch
8. **Frontend** polls `GET /files` → shows `report.pdf` with status "COMPLETED" and links to all extracted files
9. **User** searches "quarterly revenue" → Elasticsearch returns matching documents

---

## 5. Best Practices for Long-Running Processes

### 5.1 Lambda Timeout Strategy

| Process              | Typical Duration | Strategy                                |
|----------------------|------------------|-----------------------------------------|
| File routing         | < 5s             | Standard Lambda (15s timeout)           |
| Text extraction      | 5-30s            | Lambda (60s timeout)                    |
| OCR (single image)   | 10-120s          | Lambda (300s timeout)                   |
| OCR (large document) | 2-15 min         | Step Functions + chunked processing     |
| PDF image extraction | 5-60s            | Lambda (120s timeout)                   |

### 5.2 Why Step Functions for PDF?

PDFs require **multiple processing stages** that can fail independently:
- Image extraction might succeed but OCR might fail on one image
- Step Functions provide **built-in retry**, **error handling**, and **parallel processing**
- Each step is independently retryable without re-running the entire pipeline
- Visual debugging in the AWS Console shows exactly where failures occur

### 5.3 SQS Best Practices

- **Visibility Timeout**: Set to 6x your Lambda timeout (e.g., Lambda=60s → Visibility=360s)
- **Dead Letter Queues**: Always configure DLQ with `maxReceiveCount: 3`
- **Batch Size**: Use batch size of 1 for OCR (heavy processing), up to 10 for lightweight routing
- **FIFO vs Standard**: Use Standard queues (we don't need ordering, and need higher throughput)

### 5.4 Lambda Best Practices for Heavy Processing

1. **Lambda Layers**: Package Tesseract, Poppler, and heavy dependencies as Lambda Layers
2. **Memory = CPU**: Lambda CPU scales linearly with memory. For OCR, use 1536MB-3008MB
3. **/tmp Storage**: Lambda provides 512MB (configurable to 10GB) of ephemeral storage in `/tmp`
4. **Connection Pooling**: Reuse SDK clients outside the handler for connection reuse
5. **Provisioned Concurrency**: For predictable latency, use provisioned concurrency on OCR Lambdas
6. **Reserved Concurrency**: Limit OCR Lambda concurrency to prevent throttling downstream services

### 5.5 Handling Files Larger Than Lambda Limits

For files > 250MB (Lambda payload limit):
- Use **S3 presigned URLs** for direct upload (bypasses API Gateway 10MB limit)
- Lambda reads from S3 using streaming (never load entire file in memory)
- For very large PDFs (100+ pages), use Step Functions to process page ranges in parallel

### 5.6 Idempotency

- Use `file_id` as idempotency key
- DynamoDB conditional writes prevent duplicate processing
- SQS message deduplication prevents duplicate triggers

---

## 6. LocalStack Development Guide

### 6.1 What is LocalStack?

LocalStack is a local AWS cloud emulator that runs in Docker. It provides the same APIs as AWS services, allowing you to develop and test without an AWS account or incurring costs.

### 6.2 Services Used

| Service        | LocalStack Support | Notes                          |
|----------------|--------------------|--------------------------------|
| S3             | ✅ Full            | Complete S3 API                |
| SQS            | ✅ Full            | Standard + FIFO queues         |
| Lambda         | ✅ Full            | Python, Node.js runtimes       |
| Step Functions | ✅ Full            | Full ASL support               |
| DynamoDB       | ✅ Full            | Complete API                   |
| API Gateway    | ✅ Full            | REST APIs                      |
| Elasticsearch  | ✅ Partial         | Basic operations               |

### 6.3 Running Locally

```bash
# Start all services
docker-compose up -d

# Check health
curl http://localhost:4566/_localstack/health

# View logs
docker-compose logs -f localstack

# Tear down
docker-compose down -v
```

### 6.4 AWS CLI with LocalStack

```bash
# Configure alias
alias awslocal='aws --endpoint-url=http://localhost:4566'

# List S3 buckets
awslocal s3 ls

# List SQS queues
awslocal sqs list-queues

# Invoke Lambda
awslocal lambda invoke --function-name file-router output.json
```

---

## 7. Deployment Guide

### 7.1 Prerequisites

- Docker & Docker Compose
- AWS CLI v2
- Python 3.11+
- Node.js 18+ (for Lambda bundling)
- Terraform or AWS CDK (for production deployment)

### 7.2 Local Development

```bash
git clone <repo-url>
cd aws-doc-processor
docker-compose up -d
./infrastructure/scripts/init-localstack.sh
# Open http://localhost:8080 in browser
```

### 7.3 Production Deployment

The GitHub Actions workflow handles:
1. Run tests
2. Build Lambda packages
3. Deploy infrastructure (CloudFormation/Terraform)
4. Deploy Lambda code
5. Run integration tests

---

## 8. Troubleshooting

| Issue                          | Solution                                           |
|--------------------------------|----------------------------------------------------|
| Lambda timeout on large files  | Increase memory (more CPU) and timeout              |
| SQS messages stuck             | Check visibility timeout vs Lambda timeout          |
| OCR quality poor               | Increase image DPI, preprocess (denoise, deskew)    |
| Elasticsearch not indexing     | Check cluster health, index mappings                |
| S3 event not triggering        | Verify notification configuration on bucket         |
| Step Function stuck            | Check execution history in console/LocalStack       |
| DynamoDB throttling            | Switch to on-demand capacity mode                   |

---

*Document Version: 1.0 | Last Updated: 2025*
