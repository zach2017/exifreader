# OCR Extract - PDF and Image Text Extraction

LocalStack Community Edition - no Pro features needed.

## Approach

Lambda Layers do not reliably extract to /opt in LocalStack Community.
LAMBDA_RUNTIME_IMAGE_MAPPING is Pro-only.

Solution: bundle tesseract and poppler binaries directly into the
Lambda function zip. The zip extracts to /var/task/ in the container:

    /var/task/handler.py
    /var/task/bin/tesseract
    /var/task/bin/pdftoppm
    /var/task/lib/*.so
    /var/task/share/tessdata/eng.traineddata
    /var/task/PyPDF2/...

The handler references /var/task/bin/tesseract directly.
No layers. No custom images. No Pro features.

## Quick Start

    docker compose up --build
    # Wait for "OCR Stack Ready!"
    # Open http://localhost:8080

## Startup Order

1. layer-builder - amazonlinux:2 installs tesseract via EPEL, packages binaries
2. localstack - starts with Docker socket
3. deployer - merges binaries + handler into one zip, deploys function
4. backend - Flask API
5. frontend - Nginx + Tailwind

## Troubleshooting

    docker compose logs layer-builder
    docker compose logs deployer
    docker compose logs localstack 2>&1 | tail -50

    aws --endpoint-url=http://localhost:4566 lambda get-function \
        --function-name ocr-extract

## Cleanup

    docker compose down -v
