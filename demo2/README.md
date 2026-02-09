# 🔍 OCR Extract — PDF & Image Text Extraction Stack

Fully containerized OCR pipeline: **Docker Compose** → **LocalStack Lambda** → **Tesseract OCR**

## Architecture

```
┌─────────────┐  POST   ┌──────────────┐  invoke  ┌────────────────────────┐
│   Frontend   │────────▶│   Backend    │─────────▶│   LocalStack Lambda    │
│   Nginx +    │◀────────│   Flask      │◀─────────│   (separate container) │
│   Tailwind   │  JSON   │   :5000      │          │   Tesseract + PyPDF2   │
│   :8080      │         └──────────────┘          └────────────────────────┘
└─────────────┘                │                            │
                               │                            │
                        ┌──────┴──────┐              ┌──────┴──────┐
                        │  LocalStack │              │  Docker     │
                        │  :4566      │──── spawns ──│  Container  │
                        └─────────────┘              │  (lambda-   │
                                                     │   ocr-      │
                                                     │   python311)│
                                                     └─────────────┘
```

## How It Works (LocalStack 3.x)

> **Important**: LocalStack 3.0+ removed `LAMBDA_EXECUTOR=local`. Lambdas now run in
> **separate Docker containers** spawned by LocalStack via the Docker socket.

1. **Custom Lambda image** (`lambda-ocr-python311`) extends the official
   `public.ecr.aws/lambda/python:3.11` with Tesseract OCR + Poppler
2. `LAMBDA_RUNTIME_IMAGE_MAPPING` tells LocalStack to use this image
   instead of the stock runtime image
3. `LAMBDA_DOCKER_NETWORK=ocr-net` ensures Lambda containers can reach LocalStack
4. The **deployer** service packages the handler + deps into a zip, creates
   the function, and **polls until State=Active** (async creation in 3.x)
5. Backend only starts after deployer confirms the function is Active

## Quick Start

```bash
# Build everything and start (first run takes ~2-3 min for image pulls)
docker compose up --build

# Watch the logs — look for "✓ OCR Stack Ready!"
# Then open → http://localhost:8080
```

Or use the helper script:
```bash
chmod +x start.sh && ./start.sh
```

## Verify Everything Is Working

```bash
chmod +x verify.sh && ./verify.sh
```

This checks: LocalStack health, Lambda function state, Docker image existence,
backend connectivity, and frontend accessibility.

## Services

| Service       | Port   | Description                                       |
|--------------|--------|---------------------------------------------------|
| frontend     | 8080   | Nginx + Tailwind CSS upload form                  |
| backend      | 5000   | Flask API → Lambda invocation                     |
| localstack   | 4566   | AWS emulator (Lambda, IAM)                        |
| deployer     | —      | One-shot: deploys Lambda, verifies Active state   |
| lambda-image | —      | One-shot: builds custom Docker image with Tesseract|

## Supported Files

| Type | Extensions       | Method                                   |
|------|-----------------|------------------------------------------|
| PDF  | `.pdf`          | PyPDF2 native text → fallback OCR        |
| TIFF | `.tiff`, `.tif` | Tesseract OCR (multi-frame supported)    |
| PNG  | `.png`          | Tesseract OCR                            |
| JPEG | `.jpg`, `.jpeg` | Tesseract OCR                            |

## Troubleshooting

### "Resource not found" error
```bash
# Check if function exists and its state:
aws --endpoint-url=http://localhost:4566 lambda get-function \
    --function-name ocr-extract

# List all functions:
aws --endpoint-url=http://localhost:4566 lambda list-functions

# Check deployer logs:
docker compose logs deployer
```

### Function stuck in "Pending" state
LocalStack 3.x creates functions asynchronously. The deployer waits for Active,
but if something went wrong:
```bash
# Check LocalStack logs for errors:
docker compose logs localstack | grep -i error

# Verify the custom image exists:
docker image inspect lambda-ocr-python311
```

### Lambda container can't reach LocalStack
Ensure `LAMBDA_DOCKER_NETWORK=ocr-net` is set and the network name matches:
```bash
docker network ls | grep ocr
```

### First invocation is slow
The first Lambda invocation creates a new container — this can take 10-30s.
Subsequent invocations reuse the warm container.

## Cleanup

```bash
docker compose down -v          # stop + remove volumes
docker rmi lambda-ocr-python311 # remove custom image
```
