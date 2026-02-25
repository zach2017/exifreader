FROM python:3.11-slim-bookworm

# Install Tesseract OCR + PDF tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify
RUN tesseract --version && which tesseract

# Install Python deps
RUN pip install --no-cache-dir flask pymupdf

WORKDIR /app
COPY handler.py .
COPY pdf_handler.py .
COPY pdf_ocr_handler.py .
COPY server.py .

EXPOSE 9000

CMD ["python", "server.py"]
