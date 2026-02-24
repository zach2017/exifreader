FROM python:3.11-slim

# Install tesseract for OCR + system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install ALL Lambda dependencies
RUN pip install --no-cache-dir \
    boto3 \
    pdfplumber \
    python-docx \
    beautifulsoup4 \
    openpyxl \
    python-pptx \
    PyPDF2 \
    pytesseract \
    Pillow

WORKDIR /app

COPY poller.py /app/poller.py

CMD ["python", "-u", "/app/poller.py"]
