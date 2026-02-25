# ─────────────────────────────────────────────────────────────────
# Custom Lambda Runtime Image
#
# This image is NOT deployed directly as a Lambda (that's Pro only).
# Instead, LocalStack uses it via LAMBDA_RUNTIME_IMAGE_MAPPING to
# provide the execution environment when a python3.11 Lambda is
# invoked. The handler code is deployed separately as a zip package.
#
# Provides: Python 3.11 + Tesseract OCR + PyMuPDF + awslambdaric
# ─────────────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm

# ── System dependencies: Tesseract OCR engine ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN tesseract --version

# ── Python dependencies ──
# awslambdaric = AWS Lambda Runtime Interface Client (required)
# pymupdf      = PDF page rendering
# boto3        = AWS SDK for S3 read/write
RUN pip install --no-cache-dir \
    awslambdaric \
    pymupdf \
    boto3

# Lambda code gets mounted into /var/task by LocalStack
WORKDIR /var/task

# Lambda Runtime Interface Client entrypoint
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["lambda_handler.handler"]
