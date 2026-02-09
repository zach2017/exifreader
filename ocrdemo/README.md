# OCR Extract — LocalStack Lambda OCR Service

## Quick Start

```bash
# Extract the zip, then:
cd ocr-app
docker compose up --build
```

Open **http://localhost:8080** — wait ~20s for LocalStack to deploy the Lambda.

## Architecture

```
Browser (HTML/Tailwind/JS)
  → Nginx :8080 (static files + reverse proxy)
    → LocalStack :4566 (Lambda: ocr-service)
      → Tesseract OCR engine
```

## Project Structure

```
ocr-app/
├── docker-compose.yml          # Orchestrates web + localstack
├── app/index.html              # Frontend: Tailwind CSS + JS upload form
├── nginx/default.conf          # Static files + proxy /api/ocr → Lambda
├── lambda/handler.py           # Python Lambda: Tesseract OCR
├── localstack/Dockerfile       # LocalStack + Tesseract installed
└── init/setup.sh               # Auto-deploys Lambda on startup
```

## Troubleshooting

```bash
# Check Lambda is deployed
curl http://localhost:4566/2015-03-31/functions/ocr-service

# View logs
docker compose logs localstack
```
