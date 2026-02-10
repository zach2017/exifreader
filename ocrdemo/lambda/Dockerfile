FROM python:3.11-slim-bookworm

# Install Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify
RUN tesseract --version && which tesseract

# Install Flask for Lambda-compatible invoke endpoint
RUN pip install --no-cache-dir flask

WORKDIR /app
COPY handler.py .
COPY server.py .

EXPOSE 9000

# Runs a thin server that accepts Lambda invoke format: POST /2015-03-31/functions/ocr-service/invocations
CMD ["python", "server.py"]
