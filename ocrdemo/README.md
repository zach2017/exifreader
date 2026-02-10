# OCR Extract — Lambda OCR Service

## Quick Start

```bash
cd ocr-app
docker compose up --build
```

Open **http://localhost:8080** — ready in ~10 seconds.

## Architecture

```
Browser (HTML/Tailwind/JS)
  → Nginx :8080 (static + reverse proxy /api/ocr)
    → Lambda Service :9000 (Python + Tesseract OCR)
      POST /2015-03-31/functions/ocr-service/invocations
```

## Project Structure

```
ocr-app/
├── docker-compose.yml
├── app/index.html              # Tailwind CSS frontend + JS callOcrLambda()
├── nginx/default.conf          # Static files + proxy /api/ocr → Lambda
└── lambda/
    ├── Dockerfile              # Python 3.11 + Tesseract OCR
    ├── handler.py              # Lambda handler (same as AWS Lambda format)
    └── server.py               # Lambda-compatible invoke endpoint
```
