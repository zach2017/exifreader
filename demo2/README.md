# 🔍 OCR Extract — PDF & Image Text Extraction

LocalStack **Community Edition** — no Pro features needed.

## The Problem (and fix)

| Runtime    | OS Base              | Tesseract available? |
|-----------|----------------------|----------------------|
| python3.11 | Amazon Linux **2023** | ❌ NOT in any repo   |
| python3.9  | Amazon Linux **2**    | ✅ EPEL has it       |

So we use **python3.9 runtime** + build the layer on **amazonlinux:2** → guaranteed binary compatibility.

## Architecture

```
 User → Frontend (Nginx :8080)
           ↓ POST /api/extract
        Backend (Flask :5000)
           ↓ lambda.invoke()
        LocalStack (:4566)
           ↓ spawns container
        Lambda Container (python3.9 / AL2)
           ├── handler.py + Python deps (from zip)
           └── /opt/ (from Layer)
               ├── bin/tesseract, bin/pdftoppm
               ├── lib/*.so
               └── share/tessdata/eng.traineddata
```

## Quick Start

```bash
docker compose up --build
# Wait for "✓ OCR Stack Ready!" → http://localhost:8080
```

## Startup Order

1. **layer-builder** — `amazonlinux:2` installs tesseract via EPEL, packages binaries into layer.zip
2. **localstack** — starts with Docker socket mounted
3. **deployer** — publishes layer, creates function (python3.9), waits for Active state
4. **backend** — Flask API, starts after deployer confirms Active
5. **frontend** — Nginx + Tailwind CSS upload form

## Troubleshooting

```bash
# Check deployer output
docker compose logs deployer

# Check Lambda state
aws --endpoint-url=http://localhost:4566 lambda get-function \
    --function-name ocr-extract

# Check layer-builder output
docker compose logs layer-builder

# Check LocalStack Lambda logs
docker compose logs localstack 2>&1 | tail -50
```

## Cleanup

```bash
docker compose down -v
```
