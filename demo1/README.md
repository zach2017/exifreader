# PDF Metadata, Image & OCR Extractor

Upload a PDF to extract metadata, custom fields, and images — then benchmark two OCR strategies:

1. **Lambda Per-Image OCR** — Each extracted image is sent to an AWS Lambda function (running on LocalStack) that uses Tesseract to extract text. Timing is recorded for each invocation.
2. **Direct Tesseract OCR** — Each PDF page is rendered as an image and processed by Tesseract directly in the backend. Timing is recorded per page.

## Architecture

```
┌─────────┐     ┌──────────┐     ┌─────────────┐
│  nginx  │────▶│  Flask   │────▶│ LocalStack  │
│ :8080   │     │ backend  │     │  Lambda     │
└─────────┘     │ +Tesseract│     │ +Tesseract  │
                └──────────┘     └─────────────┘
```

- **nginx** — static frontend + reverse proxy to backend
- **Flask backend** — PDF parsing (PyMuPDF), image extraction, direct Tesseract OCR, Lambda invocation via boto3
- **LocalStack** — emulates AWS Lambda; runs `ocr-extract-text` function with Tesseract

## Quick Start

```bash
docker compose up --build
```

Then open http://localhost:8080

1. Upload a PDF
2. View metadata, custom fields, and extracted images
3. Click **Run OCR Benchmark** to compare Lambda vs Direct OCR timing

## Services

| Service     | Port | Description                              |
|-------------|------|------------------------------------------|
| web         | 8080 | Nginx frontend                           |
| backend     | 5000 | Flask API (internal)                     |
| localstack  | 4566 | LocalStack (Lambda + Tesseract)          |

## API Endpoints

| Method | Path                              | Description                        |
|--------|-----------------------------------|------------------------------------|
| GET    | `/api/health`                     | Health check                       |
| POST   | `/api/extract`                    | Upload PDF, extract metadata/images|
| POST   | `/api/ocr/<job_id>`               | Run OCR benchmark for a job        |
| GET    | `/api/images/<job_id>/<filename>` | Serve extracted image              |
| GET    | `/api/images/<job_id>/download-all`| Download all images as zip        |

## Files

```
├── docker-compose.yml          # 3-service compose (web, backend, localstack)
├── Dockerfile                  # Backend: Python + PyMuPDF + Tesseract
├── Dockerfile.localstack       # Custom LocalStack with Tesseract
├── app.py                      # Flask backend with OCR benchmark
├── index.html                  # Frontend UI
├── nginx.conf                  # Nginx reverse proxy config
├── requirements.txt            # Python dependencies
├── lambda_ocr/
│   ├── handler.py              # Lambda function (Tesseract OCR)
│   └── Dockerfile              # (reference, not used by compose)
├── init-scripts/
│   └── deploy-lambda.sh        # Auto-deploys Lambda on LocalStack startup
├── create_samples.py           # Generate sample PDFs
└── samples/                    # Sample PDFs with embedded images
```
