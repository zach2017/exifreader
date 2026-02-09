FROM localstack/localstack:latest

# Install Tesseract OCR and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    zip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify tesseract is available
RUN tesseract --version && which tesseract
