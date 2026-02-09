FROM localstack/localstack:latest

# Install Tesseract OCR and dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
