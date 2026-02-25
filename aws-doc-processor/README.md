# 📄 DocProc — AWS Serverless Document Processing Pipeline

A complete serverless document processing system that accepts file uploads, automatically extracts text using OCR and parsing, stores metadata, and provides full-text search — all running locally with **LocalStack** and deployable to **AWS**.

![Architecture: S3 → SQS → Lambda → Step Functions → DynamoDB → Elasticsearch](docs/architecture-banner.png)

---

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/your-org/aws-doc-processor.git
cd aws-doc-processor

# 2. Start all services (LocalStack, Elasticsearch, Frontend)
docker-compose up -d

# 3. Wait for initialization (~30 seconds)
docker-compose logs -f localstack  # Watch for "All AWS Resources Initialized!"

# 4. Open the web interface
open http://localhost:8080
```

That's it! Upload a file and watch the pipeline process it.

---

## 📋 What Does This System Do?

1. **Upload** any document (PDF, Word, Image, Text, Excel, PowerPoint)
2. **Classify** the file type automatically
3. **Route** to the correct processing pipeline:
   - **PDF** → Step Functions orchestrates image extraction + text extraction + OCR in parallel
   - **Word/Excel/PPT** → Text extraction Lambda
   - **Images** → OCR Lambda (Tesseract)
   - **Plain text** → Direct storage
4. **Store** extracted text in S3, metadata in DynamoDB
5. **Index** all text in Elasticsearch for full-text search
6. **View** results in the web interface with download and search

---

## 🏗 Architecture

```
Frontend (nginx:8080) → S3 Upload → SQS → File Router Lambda
                                           │
                        ┌──────────────────┼──────────────────┐
                        │                  │                  │
                    PDF (Step Fn)    DOCX/XLSX/etc        Images
                    │   │              │                    │
              Extract  Text         Text Extract        OCR (Tesseract)
              Images   Extract        Lambda               Lambda
                │                      │                    │
                ▼                      ▼                    ▼
            OCR Queue            S3 + DynamoDB         S3 + DynamoDB
                │                + Elasticsearch       + Elasticsearch
                ▼
          OCR Lambda → S3 + DynamoDB + Elasticsearch
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the complete technical deep-dive.

---

## 🗂 Project Structure

```
aws-doc-processor/
├── docker-compose.yml              # LocalStack + Elasticsearch + nginx
├── frontend/
│   ├── index.html                  # Upload, file list, and search UI
│   └── nginx.conf                  # Reverse proxy config
├── lambdas/
│   ├── file-router/                # Routes files by type
│   │   ├── handler.py
│   │   └── requirements.txt
│   ├── text-extractor/             # Extracts text from documents
│   │   ├── handler.py
│   │   └── requirements.txt
│   └── ocr-extractor/              # OCR for images
│       ├── handler.py
│       └── requirements.txt
├── step-functions/
│   └── pdf-pipeline.asl.json       # PDF processing state machine
├── infrastructure/
│   └── localstack/
│       └── init-aws.sh             # Creates all AWS resources
├── .github/
│   └── workflows/
│       └── ci-cd.yml               # CI/CD pipeline
├── tests/
│   ├── test_unit.py                # Unit tests (mocked)
│   └── test_integration.py         # Integration tests (LocalStack)
└── docs/
    └── ARCHITECTURE.md             # Full architecture documentation
```

---

## 🔧 Services & Ports

| Service        | Port  | URL                            |
|----------------|-------|--------------------------------|
| Frontend       | 8080  | http://localhost:8080           |
| LocalStack     | 4566  | http://localhost:4566           |
| Elasticsearch  | 9200  | http://localhost:9200           |

---

## 📖 How Each Component Works

### File Router Lambda

The entry point for all uploaded files. Triggered by SQS when a new file appears in S3.

```python
# Classification logic (simplified)
if file_type == 'pdf':
    start_step_function(file_id, s3_key)     # Multi-step PDF pipeline
elif file_type in ('word', 'excel', 'ppt'):
    send_to_sqs('text-extract-queue', ...)   # Text extraction
elif file_type == 'image':
    send_to_sqs('ocr-queue', ...)            # OCR processing
elif file_type == 'text':
    store_directly(file_id, s3_key)          # No processing needed
```

### Step Functions (PDF Pipeline)

Orchestrates complex PDF processing with parallel branches:

1. **Extract Images** → Downloads PDF, extracts embedded images, saves to S3
2. **Parallel Branch A** → Send each image to OCR queue
3. **Parallel Branch B** → Send PDF to text extraction queue
4. **Update Metadata** → Mark processing status in DynamoDB

### Text Extractor Lambda

Handles text extraction from various document formats:
- **PDF**: `pdfplumber` extracts text layers
- **DOCX**: `python-docx` parses XML content
- **XLSX**: `openpyxl` reads cell values
- **PPTX**: `python-pptx` extracts slide text
- **HTML**: `BeautifulSoup` strips tags

### OCR Extractor Lambda

Handles image-to-text conversion:
1. **Preprocess**: Grayscale → contrast enhancement → denoise → deskew
2. **OCR**: Tesseract with `--oem 3 --psm 3` (LSTM + auto page segmentation)
3. **Store**: Save extracted text to S3, index in Elasticsearch

---

## 🧪 Testing

```bash
# Unit tests (no services required)
pip install pytest moto boto3
pytest tests/test_unit.py -v

# Integration tests (requires LocalStack running)
docker-compose up -d
pytest tests/test_integration.py -v
```

---

## 📝 Best Practices Implemented

### Lambda Performance
- **Memory = CPU**: OCR Lambda uses 2048MB for more CPU power
- **Connection reuse**: boto3 clients initialized outside handler
- **Temp storage**: Files processed in /tmp, cleaned up after

### Fault Tolerance
- **DLQ on every queue**: Failed messages retry 3x, then go to Dead Letter Queue
- **Step Function retry**: Each step retries 2x with exponential backoff
- **Catch blocks**: Failures update DynamoDB status to ERROR

### Scalability
- **Decoupled via SQS**: Each stage processes independently
- **Parallel processing**: Step Functions process OCR and text extraction simultaneously
- **On-demand DynamoDB**: Auto-scales with no capacity planning

### Security (Production)
- **S3 presigned URLs**: For uploads > 10MB (bypasses API Gateway limit)
- **IAM least privilege**: Each Lambda gets only required permissions
- **VPC**: Lambda functions in private subnet with NAT gateway

---

## 🚢 Deploying to AWS

### Prerequisites
- AWS account with appropriate permissions
- AWS CLI configured with credentials
- S3 bucket for Lambda deployment packages

### Steps

1. Set GitHub repository secrets:
   ```
   AWS_ACCESS_KEY_ID
   AWS_SECRET_ACCESS_KEY
   ```

2. Push to `main` branch — GitHub Actions will:
   - Run all tests
   - Package Lambda functions
   - Deploy via CloudFormation

3. Or deploy manually:
   ```bash
   # Package
   cd lambdas/file-router && zip -r ../../dist/file-router.zip .
   
   # Deploy
   aws lambda update-function-code \
     --function-name file-router \
     --zip-file fileb://dist/file-router.zip
   ```

---

## 🔍 Using the Search

The search uses Elasticsearch with fuzzy matching:

```
# In the Search tab, try:
"quarterly revenue"     → Finds documents mentioning revenue
"project timeline"      → Finds project-related documents
"invoice 2024"          → Finds invoices from 2024
```

Search returns highlighted excerpts showing where matches were found.

---

## 🛠 Development

### Adding a New File Format

1. Add MIME type to `MIME_CATEGORIES` in `file-router/handler.py`
2. Add extraction function in `text-extractor/handler.py`
3. Add the format badge to `frontend/index.html`
4. Add test case in `tests/test_unit.py`

### Modifying the Step Function

1. Edit `step-functions/pdf-pipeline.asl.json`
2. The ASL (Amazon States Language) definition is deployed during `init-aws.sh`
3. Use the [Step Functions visual editor](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-amazon-states-language.html) for complex changes

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
