FROM python:3.11-slim-bookworm

# ── Install Tesseract OCR engine + PDF tools ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN tesseract --version

# ── Python dependencies ──
RUN pip install --no-cache-dir \
    pymupdf \
    boto3 \
    awslambdaric

WORKDIR /app
COPY lambda_handler.py .

# AWS Lambda Runtime Interface Client entrypoint
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["lambda_handler.handler"]
